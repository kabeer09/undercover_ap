"""The UnderCover Agent."""

import json
import os
import uuid
from collections import Counter
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from agent.tools import QUEUE_TOOLS, TOOLS, request

load_dotenv(override=True)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME, or DeepSeek V4.1 Flash by default."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
        max_completion_tokens=4000,
    )


class BackendError(Exception):
    """The backend refused a request the agent's run depends on."""


def call_backend(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Call the backend and return its JSON, raising if it refuses."""
    response = request(method, path, body)
    if response.is_error:
        raise BackendError(f"{response.status_code}: {response.json()['detail']}")
    return response.json()


def steps(message: AnyMessage) -> list[tuple[str, str]]:
    """Turn one message from the agent's run into steps for the dashboard."""
    if isinstance(message, ToolMessage):
        return [("tool_result", f"{message.name}: {message.text}")]
    found = []
    if message.text:
        found.append(("message", message.text))
    if isinstance(message, AIMessage):
        for call in message.tool_calls:
            args = ", ".join(f"{k}={json.dumps(v)}" for k, v in call["args"].items())
            found.append(("tool_call", f"{call['name']}({args})"))
    return found


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Work one claim, recording each step with the backend, and return the reply."""
    call_backend("POST", f"/api/claims/{claim_id}/start", {"thread_id": thread_id})
    instructions = call_backend("GET", "/api/instructions")["text"]
    agent = create_agent(
        llm or model(),
        tools=TOOLS,
        system_prompt=instructions,
        checkpointer=InMemorySaver(),
    )
    states = agent.stream(
        {"messages": [{"role": "user", "content": f"Claim {claim_id}"}]},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="values",
    )
    messages = next(states)["messages"]
    for state in states:
        for message in state["messages"][len(messages) :]:
            for kind, content in steps(message):
                call_backend(
                    "POST",
                    f"/api/claims/{claim_id}/steps",
                    {"kind": kind, "content": content},
                )
        messages = state["messages"]
    return messages[-1].text


def set_todo(claim_id: str, status: str) -> None:
    """Move the to-do item for a claim in the current run, if it has one."""
    run_data = call_backend("GET", "/api/runs/current")
    for todo in run_data["todos"]:
        if todo["claim_id"] == claim_id:
            call_backend("POST", f"/api/todos/{todo['todo_id']}", {"status": status})
            return


def work_claim(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Give one claim to a fresh helper and report its decision, payout or problem."""
    set_todo(claim_id, "in_progress")
    try:
        reply = run(claim_id, str(uuid.uuid4()), llm)
    except Exception as error:  # a failed claim must not stop the run
        call_backend(
            "POST",
            f"/api/claims/{claim_id}/failure",
            {"reason": str(error)},
        )
        return f"{claim_id} failed: {error}"
    set_todo(claim_id, "done")
    claim = call_backend("GET", f"/api/claims/{claim_id}")
    decision = claim["decision"]
    if decision is None:
        return f"{claim_id} undecided: {reply}"
    return f"{claim_id} {decision['decision']} ${decision['payout']:,.2f}"


def missed_claims(cap: int = 0) -> list[str]:
    """List waiting claims still inside the run's cap before it finishes."""
    waiting = [
        claim["claim_id"]
        for claim in call_backend("GET", "/api/claims")
        if claim["status"] == "waiting"
    ]
    if cap:
        worked = len(call_backend("GET", "/api/runs/current")["todos"])
        waiting = waiting[: max(0, cap - worked)]
    return waiting


def run_queue(cap: int = 0, llm: BaseChatModel | None = None) -> str:
    """Start one run, work the queue with fresh helpers and finish with a summary."""
    started = call_backend("POST", "/api/runs", {"cap": cap})
    queue_llm = llm or model()

    def helper(claim_id: str) -> str:
        """Decide one claim with a fresh helper and reply in one line."""
        return work_claim(claim_id, queue_llm)

    helper_tool = tool(helper)
    helper_tool.name = "work_claim"
    agent = create_agent(
        queue_llm,
        tools=[*QUEUE_TOOLS, helper_tool],
        system_prompt=call_backend("GET", "/api/instructions/queue")["text"],
        checkpointer=InMemorySaver(),
    )
    task = f"Work the queue, capped at {cap or 'all waiting'} claims."
    states = agent.stream(
        {"messages": [{"role": "user", "content": task}]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
        stream_mode="values",
    )
    messages = next(states)["messages"]
    for state in states:
        messages = state["messages"]
    summary = messages[-1].text

    for claim_id in missed_claims(cap):
        line = work_claim(claim_id, queue_llm)
        summary = f"{summary}\n{line}" if summary else line
    call_backend(
        "POST",
        f"/api/runs/{started['run_id']}/finish",
        {"summary": summary or "No claims worked"},
    )
    print(summary, flush=True)
    return summary


def work_queue() -> None:
    """Work every waiting claim, printing each decision and a count."""
    outcomes: Counter[str] = Counter()
    for claim in call_backend("GET", "/api/claims"):
        if claim["status"] != "waiting":
            continue
        claim_id = claim["claim_id"]
        try:
            reply = work_claim(claim_id)
        except Exception as error:
            print(f"{claim_id}  failed: {error}", flush=True)
            outcomes["failed"] += 1
            continue
        decision = call_backend("GET", f"/api/claims/{claim_id}")["decision"]
        if decision is None:
            print(f"{claim_id}  {reply}", flush=True)
            outcomes["undecided"] += 1
        else:
            outcome = decision["decision"]
            print(f"{claim_id}  {outcome}  ${decision['payout']:,.2f}", flush=True)
            outcomes[outcome] += 1
    counts = ", ".join(f"{outcomes[name]} {name}" for name in sorted(outcomes))
    print(f"Worked {outcomes.total()} claims: {counts or 'none waiting'}")
