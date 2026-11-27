"""The models the agent works with, through OpenRouter, with the key in
OPENROUTER_API_KEY. Each model call's cost comes back in its usage.

Set LOCAL_MODEL to run against a model on a local Ollama server instead; OpenRouter
remains the default so the normal (and tested) behaviour is unchanged.
"""

import os
from typing import NamedTuple

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LOCAL_BASE_URL = "http://localhost:11434/v1"
# A model at its own default, with no reasoning effort sent, as the backend
# records it. OpenAI's "none" is a real level of its own.
NO_REASONING_EFFORT = "default"
RETRIES = 5


def chat_model(model: str, reasoning_effort: str, timeout: int) -> ChatOpenAI:
    """A model on OpenRouter at a reasoning effort, giving up on a call after the
    timeout in seconds and retrying it RETRIES times. With LOCAL_MODEL set, use a
    local Ollama model instead."""
    local_model = os.getenv("LOCAL_MODEL")
    if local_model:
        return ChatOpenAI(
            model=local_model,
            base_url=LOCAL_BASE_URL,
            api_key=SecretStr("ollama"),
            timeout=timeout,
            max_retries=RETRIES,
        )
    return ChatOpenAI(
        model=model,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=(
            None if reasoning_effort == NO_REASONING_EFFORT else reasoning_effort
        ),
        timeout=timeout,
        max_retries=RETRIES,
    )


class Usage(NamedTuple):
    """A model call's tokens and its cost in US dollars."""

    input_tokens: int
    output_tokens: int
    cost: float


def usage_of(reply: BaseMessage) -> Usage:
    """A reply's tokens and cost. OpenRouter reports both; local models are free."""
    usage = reply.response_metadata.get("token_usage", {})
    if os.getenv("LOCAL_MODEL"):
        return Usage(
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            0.0,
        )
    return Usage(usage["prompt_tokens"], usage["completion_tokens"], usage["cost"])
