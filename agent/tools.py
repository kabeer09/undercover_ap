"""The agent's tools, each named after the backend operation it calls."""

from typing import Any, Literal

import httpx
from langchain_core.tools import tool

BACKEND_URL = "http://localhost:8000"


def backend() -> httpx.Client:
    """Return a client for the UnderCover backend."""
    return httpx.Client(base_url=BACKEND_URL, timeout=30)


def request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    """Send one request to the backend."""
    with backend() as client:
        return client.request(method, path, json=body, params=params)


def reply(response: httpx.Response) -> str:
    """Give the model the backend's answer, or its reason for refusing."""
    if response.is_success:
        return response.text
    return f"Refused with status {response.status_code}: {response.text}"


@tool
def get_claim(claim_id: str) -> str:
    """Get one claim in full: the story, the items claimed and the documents."""
    return reply(request("GET", f"/api/claims/{claim_id}"))


@tool
def get_policy(policy_id: str) -> str:
    """Get a policy: the plan, add-ons, purchase date, trip and travelers."""
    return reply(request("GET", f"/api/policies/{policy_id}"))


@tool
def get_claim_history(customer_id: str) -> str:
    """Get a customer's earlier claims, with the outcome and the amount paid."""
    return reply(request("GET", f"/api/customers/{customer_id}/claims"))


@tool
def record_decision(
    claim_id: str,
    decision: Literal["approve", "decline", "refer"],
    payout: float,
    section: str,
    reason: str,
) -> str:
    """Record the decision on a claim; an approval over the limit waits for sign-off."""
    body = {
        "decision": decision,
        "payout": payout,
        "section": section,
        "reason": reason,
    }
    return reply(request("POST", f"/api/claims/{claim_id}/decision", body))


@tool
def pay_claim(claim_id: str, amount: float) -> str:
    """Pay an approved claim its payout, unless it needs a handler's sign-off."""
    return reply(request("POST", f"/api/claims/{claim_id}/payment", {"amount": amount}))


@tool
def get_sections(names: str) -> str:
    """Get only the named sections of the policy wording and the claims manual."""
    response = request("GET", "/api/sections", None, {"names": names})
    return reply(response)


@tool
def list_claims() -> str:
    """List the waiting claims and what has been decided on them."""
    return reply(request("GET", "/api/claims"))


@tool
def add_todo(claim_id: str, content: str) -> str:
    """Add one claim to the current run's to-do list."""
    run = call("GET", "/api/runs/current")
    return reply(
        request(
            "POST",
            f"/api/runs/{run['run_id']}/todos",
            {"claim_id": claim_id, "content": content},
        )
    )


@tool
def update_todo(claim_id: str, status: str) -> str:
    """Update the to-do item for one claim in the current run."""
    run = call("GET", "/api/runs/current")
    for todo in run["todos"]:
        if todo["claim_id"] == claim_id:
            return reply(
                request("POST", f"/api/todos/{todo['todo_id']}", {"status": status})
            )
    return f"No to-do item for {claim_id}"


@tool
def check_queue() -> str:
    """List the claims still waiting in the queue."""
    return reply(request("GET", "/api/claims"))


@tool
def finish_run(summary: str) -> str:
    """Finish the current run with a short summary for the handlers."""
    run = call("GET", "/api/runs/current")
    return reply(
        request("POST", f"/api/runs/{run['run_id']}/finish", {"summary": summary})
    )


def call(method: str, path: str) -> Any:
    """Call the backend and return its JSON, raising if it refuses."""
    response = request(method, path)
    if response.is_error:
        raise RuntimeError(f"{response.status_code}: {response.text}")
    return response.json()


TOOLS = [
    get_claim,
    get_policy,
    get_claim_history,
    get_sections,
    record_decision,
    pay_claim,
]
QUEUE_TOOLS = [list_claims, add_todo, update_todo, check_queue, finish_run]
