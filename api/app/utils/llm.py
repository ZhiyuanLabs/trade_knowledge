"""
Centralized LLM client.
Supports Azure AI Foundry (Grok default), xAI, OpenAI.
Auth pattern: OpenAI(base_url=endpoint, api_key=key)

Azure AI Foundry compatibility:
  - Accepts the resource root:
      https://<resource>.services.ai.azure.com/models
  - Or the full portal target URL:
      https://<resource>.services.ai.azure.com/models/chat/completions?api-version=...

Timeout behaviour:
  LLM_TIMEOUT  — per-request timeout in seconds (default: 30)
  On APITimeoutError the exception propagates — callers are responsible
  for their own fallback (all nodes already have try/except blocks).
"""

import os
from urllib.parse import parse_qs, urlparse, urlunparse
from openai import OpenAI, APITimeoutError, APIConnectionError, APIStatusError
from dotenv import load_dotenv
from app.utils.logger import get_logger
from app.utils.events import emit, clip, get_trace

load_dotenv()

log = get_logger(__name__)

_client: OpenAI | None = None
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))


def _normalize_azure_foundry_endpoint(base_url: str, api_version: str) -> tuple[str, str]:
    """
    Normalize Azure AI Foundry endpoints for the OpenAI SDK.

    The SDK appends `/chat/completions` internally, so we normalize the
    Azure portal target URL back to the base `/models` path and keep the
    api-version as a separate default query parameter.
    """
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query)

    normalized_api_version = query.get("api-version", [api_version])[0]

    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]

    normalized_base_url = urlunparse(
        parsed._replace(path=path, params="", query="", fragment="")
    ).rstrip("/")

    return normalized_base_url, normalized_api_version


def _build_client() -> OpenAI:
    provider = os.getenv("LLM_PROVIDER", "azure_foundry").lower()

    if provider == "azure_foundry":
        api_key = os.getenv("AZURE_FOUNDRY_API_KEY")
        base_url = os.getenv("AZURE_FOUNDRY_BASE_URL")
        api_version = os.getenv("AZURE_FOUNDRY_API_VERSION", "2024-05-01-preview")
        if not api_key or not base_url:
            raise EnvironmentError(
                "AZURE_FOUNDRY_API_KEY and AZURE_FOUNDRY_BASE_URL must be set."
            )
        normalized_base_url, normalized_api_version = _normalize_azure_foundry_endpoint(
            base_url,
            api_version,
        )
        return OpenAI(
            base_url=normalized_base_url,
            api_key=api_key,
            default_query={"api-version": normalized_api_version},
            timeout=LLM_TIMEOUT,
        )

    elif provider == "xai":
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            raise EnvironmentError("XAI_API_KEY is not set.")
        return OpenAI(
            base_url="https://api.x.ai/v1",
            api_key=api_key,
            timeout=LLM_TIMEOUT,
        )

    elif provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY is not set.")
        return OpenAI(
            api_key=api_key,
            timeout=LLM_TIMEOUT,
        )

    raise ValueError(f"Unknown LLM_PROVIDER: '{provider}'")


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = _build_client()
    return _client


def get_model() -> str:
    return os.getenv("LLM_MODEL", "grok-3")


def _preview(messages: list[dict]) -> tuple[str, str]:
    """Pull the system/user text for the UI trace."""
    system_prompt = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
    user_prompt = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
    return system_prompt or "", user_prompt or ""


def chat(messages: list[dict], temperature: float = 0.0, label: str = "") -> str:
    """
    Send a chat completion. Returns response text.

    Raises:
        APITimeoutError     — request exceeded LLM_TIMEOUT seconds
        APIConnectionError  — network-level failure
        APIStatusError      — 4xx/5xx from the provider
    """
    tag = label or "llm"
    system_prompt, user_prompt = _preview(messages)
    emit(
        "llm",
        phase="start",
        label=tag,
        model=get_model(),
        system=clip(system_prompt, 1600),
        user=clip(user_prompt, 900),
    )
    try:
        response = get_client().chat.completions.create(
            model=get_model(),
            messages=messages,
            temperature=temperature,
        )
        text = response.choices[0].message.content.strip()
        emit("llm", phase="end", label=tag, output=clip(text, 1600))
        return text
    except APITimeoutError as e:
        emit("llm", phase="error", label=tag, error="APITimeoutError")
        log.error("llm.timeout", timeout=LLM_TIMEOUT, model=get_model())
        raise
    except APIConnectionError as e:
        emit("llm", phase="error", label=tag, error="APIConnectionError")
        log.error("llm.connection_error", error=str(e))
        raise
    except APIStatusError as e:
        emit("llm", phase="error", label=tag, error=f"APIStatusError {e.status_code}")
        log.error("llm.api_error", status_code=e.status_code, error=str(e))
        raise


def chat_stream(messages: list[dict], temperature: float = 0.1, label: str = "final_answer") -> str:
    """
    Stream a chat completion, forwarding each token to the trace as
    `answer_delta` events (the UI types the answer live). Returns the full text.
    """
    tag = label or "final_answer"
    system_prompt, user_prompt = _preview(messages)
    emit(
        "llm",
        phase="start",
        label=tag,
        model=get_model(),
        system=clip(system_prompt, 1600),
        user=clip(user_prompt, 900),
        stream=True,
    )
    parts: list[str] = []
    try:
        stream = get_client().chat.completions.create(
            model=get_model(),
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = getattr(chunk.choices[0].delta, "content", None)
            if delta:
                parts.append(delta)
                emit("answer_delta", label=tag, text=delta)
    except APITimeoutError:
        emit("llm", phase="error", label=tag, error="APITimeoutError")
        log.error("llm.timeout", timeout=LLM_TIMEOUT, model=get_model())
        raise
    except APIConnectionError as e:
        emit("llm", phase="error", label=tag, error="APIConnectionError")
        log.error("llm.connection_error", error=str(e))
        raise
    except APIStatusError as e:
        emit("llm", phase="error", label=tag, error=f"APIStatusError {e.status_code}")
        log.error("llm.api_error", status_code=e.status_code, error=str(e))
        raise

    text = "".join(parts).strip()
    emit("llm", phase="end", label=tag, output=clip(text, 1600), stream=True)
    return text


def answer_chat(messages: list[dict], temperature: float = 0.1, label: str = "final_answer") -> str:
    """
    Final-answer synthesis. During a streaming request the answer is tokenized
    live (answer_delta events); in a normal request it is a one-shot call.
    """
    if get_trace() is not None:
        return chat_stream(messages, temperature=temperature, label=label)
    return chat(messages, temperature=temperature, label=label)
