"""The models the agent works with, through OpenRouter, with the key in
OPENROUTER_API_KEY. Each model call's cost comes back in its usage."""

import os
from typing import NamedTuple

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

OPENROUTER_BASE_URL = "http://localhost:11434/v1"
# A model at its own default, with no reasoning effort sent, as the backend
# records it. OpenAI's "none" is a real level of its own.
NO_REASONING_EFFORT = "default"
RETRIES = 5


def chat_model(model: str, reasoning_effort: str, timeout: int) -> ChatOpenAI:
    """A model on OpenRouter at a reasoning effort, giving up on a call after the
    timeout in seconds and retrying it RETRIES times."""
    return ChatOpenAI(
        model=os.getenv("LOCAL_MODEL", "qwen2.5:7b"),
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None,
        timeout=timeout,
        max_retries=RETRIES,
    )


class Usage(NamedTuple):
    """A model call's tokens and its cost in US dollars."""

    input_tokens: int
    output_tokens: int
    cost: float


def usage_of(reply: BaseMessage) -> Usage:
    """A reply's tokens and cost, as OpenRouter reports them."""
    usage = reply.response_metadata.get("token_usage", {})
    return Usage(
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        usage.get("cost", 0.0),
    )
