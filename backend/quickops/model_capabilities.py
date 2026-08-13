from __future__ import annotations

from copy import deepcopy
from enum import StrEnum
from urllib.parse import urlparse

from quickops.domain import ThinkingMode


class ModelProtocol(StrEnum):
    SILICONFLOW = "siliconflow"
    ALIBABA = "alibaba"
    DEEPSEEK = "deepseek"
    VLLM = "vllm"
    SGLANG = "sglang"
    OPENAI_COMPATIBLE = "openai_compatible"


_PROVIDER_ALIASES = {
    "siliconflow": ModelProtocol.SILICONFLOW,
    "silicon flow": ModelProtocol.SILICONFLOW,
    "硅基流动": ModelProtocol.SILICONFLOW,
    "aliyun": ModelProtocol.ALIBABA,
    "alibaba": ModelProtocol.ALIBABA,
    "alibaba cloud": ModelProtocol.ALIBABA,
    "dashscope": ModelProtocol.ALIBABA,
    "bailian": ModelProtocol.ALIBABA,
    "阿里云": ModelProtocol.ALIBABA,
    "百炼": ModelProtocol.ALIBABA,
    "deepseek": ModelProtocol.DEEPSEEK,
    "deepseek official": ModelProtocol.DEEPSEEK,
    "vllm": ModelProtocol.VLLM,
    "sglang": ModelProtocol.SGLANG,
    "openai compatible": ModelProtocol.OPENAI_COMPATIBLE,
    "openai-compatible": ModelProtocol.OPENAI_COMPATIBLE,
    "openai_compatible": ModelProtocol.OPENAI_COMPATIBLE,
}


def compatible_chat_role_map() -> dict[str, str]:
    """Keep standard Chat Completions roles for non-OpenAI compatible endpoints.

    Agno's current ``OpenAIChat`` default maps ``system`` to the newer ``developer``
    role. SiliconFlow Qwen models and several local OpenAI-compatible servers reject
    that role, while the standard ``system`` role works across all QuickOps protocols.
    """

    return {
        "system": "system",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
        "model": "assistant",
    }


def resolve_model_protocol(provider: str, base_url: str = "") -> ModelProtocol:
    """Resolve common UI labels and known endpoint hosts to a request protocol."""

    normalized = " ".join(provider.strip().lower().replace("_", " ").split())
    if normalized in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[normalized]

    host = (urlparse(base_url).hostname or "").lower()
    if "siliconflow" in host:
        return ModelProtocol.SILICONFLOW
    if "dashscope" in host or host.endswith("aliyuncs.com"):
        return ModelProtocol.ALIBABA
    if host == "api.deepseek.com" or host.endswith(".deepseek.com"):
        return ModelProtocol.DEEPSEEK
    return ModelProtocol.OPENAI_COMPATIBLE


def _local_thinking_key(model_id: str) -> str:
    """Choose the chat-template switch used by a self-hosted model family.

    vLLM and SGLang forward these values into the Hugging Face chat template. Qwen and
    Gemma templates use ``enable_thinking``; DeepSeek V3/V4, Granite and Holo templates
    use ``thinking``. Unknown families use the more widely adopted ``enable_thinking``.
    """

    model = model_id.casefold()
    if any(family in model for family in ("deepseek", "granite", "holo")):
        return "thinking"
    return "enable_thinking"


def thinking_extra_body(
    *,
    provider: str | ModelProtocol,
    mode: ThinkingMode | str,
    model_id: str = "",
    base_url: str = "",
) -> dict[str, object]:
    """Translate a neutral thinking mode into an OpenAI SDK ``extra_body`` value.

    The returned mapping is safe to pass directly to Agno ``OpenAIChat(extra_body=...)``.
    Unsupported model families may ignore the provider-specific field; ``AUTO`` never
    sends a field and therefore preserves the endpoint's native default.
    """

    selected_mode = ThinkingMode(mode)
    if selected_mode is ThinkingMode.AUTO:
        return {}

    protocol = (
        provider
        if isinstance(provider, ModelProtocol)
        else resolve_model_protocol(provider, base_url)
    )
    enabled = selected_mode is ThinkingMode.ON

    if protocol in {ModelProtocol.SILICONFLOW, ModelProtocol.ALIBABA}:
        return {"enable_thinking": enabled}
    if protocol is ModelProtocol.DEEPSEEK:
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
    if protocol in {ModelProtocol.VLLM, ModelProtocol.SGLANG}:
        return {"chat_template_kwargs": {_local_thinking_key(model_id): enabled}}

    # Generic OpenAI-compatible servers most commonly expose the Qwen-style switch.
    return {"enable_thinking": enabled}


def apply_thinking_mode(
    extra_body: dict[str, object] | None,
    *,
    provider: str | ModelProtocol,
    mode: ThinkingMode | str,
    model_id: str = "",
    base_url: str = "",
) -> dict[str, object]:
    """Merge thinking control without retaining a stale, conflicting provider switch."""

    merged: dict[str, object] = deepcopy(extra_body or {})
    merged.pop("enable_thinking", None)
    merged.pop("thinking", None)

    template_kwargs = merged.get("chat_template_kwargs")
    if isinstance(template_kwargs, dict):
        cleaned_template_kwargs = deepcopy(template_kwargs)
        cleaned_template_kwargs.pop("enable_thinking", None)
        cleaned_template_kwargs.pop("thinking", None)
        if cleaned_template_kwargs:
            merged["chat_template_kwargs"] = cleaned_template_kwargs
        else:
            merged.pop("chat_template_kwargs", None)

    override = thinking_extra_body(
        provider=provider,
        mode=mode,
        model_id=model_id,
        base_url=base_url,
    )
    override_template = override.pop("chat_template_kwargs", None)
    merged.update(override)
    if isinstance(override_template, dict):
        existing_template = merged.get("chat_template_kwargs")
        merged["chat_template_kwargs"] = {
            **(existing_template if isinstance(existing_template, dict) else {}),
            **override_template,
        }
    return merged
