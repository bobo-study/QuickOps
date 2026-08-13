from quickops.model_capabilities import (
    ModelProtocol,
    ThinkingMode,
    apply_thinking_mode,
    compatible_chat_role_map,
    resolve_model_protocol,
    thinking_extra_body,
)
from quickops.title_generator import AgnoSessionTitleGenerator


def test_resolves_known_provider_aliases_and_hosts() -> None:
    assert resolve_model_protocol("硅基流动") is ModelProtocol.SILICONFLOW
    assert resolve_model_protocol("custom", "https://dashscope.aliyuncs.com/v1") is (
        ModelProtocol.ALIBABA
    )
    assert resolve_model_protocol("custom", "https://api.deepseek.com") is (
        ModelProtocol.DEEPSEEK
    )
    assert resolve_model_protocol("vLLM") is ModelProtocol.VLLM
    assert resolve_model_protocol("SGLang") is ModelProtocol.SGLANG


def test_compatible_chat_roles_keep_system_role() -> None:
    assert compatible_chat_role_map() == {
        "system": "system",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
        "model": "assistant",
    }


def test_hosted_provider_thinking_payloads() -> None:
    assert thinking_extra_body(provider="SiliconFlow", mode="off") == {
        "enable_thinking": False
    }
    assert thinking_extra_body(provider="阿里云百炼", mode="on") == {
        "enable_thinking": True
    }
    assert thinking_extra_body(provider="DeepSeek", mode="off") == {
        "thinking": {"type": "disabled"}
    }
    assert thinking_extra_body(provider="DeepSeek", mode="on") == {
        "thinking": {"type": "enabled"}
    }


def test_auto_preserves_provider_default() -> None:
    for provider in ModelProtocol:
        assert thinking_extra_body(provider=provider, mode=ThinkingMode.AUTO) == {}


def test_vllm_and_sglang_use_model_chat_template_switch() -> None:
    assert thinking_extra_body(
        provider="vllm", mode="off", model_id="Qwen/Qwen3-32B"
    ) == {"chat_template_kwargs": {"enable_thinking": False}}
    assert thinking_extra_body(
        provider="vllm", mode="on", model_id="deepseek-ai/DeepSeek-V3.1"
    ) == {"chat_template_kwargs": {"thinking": True}}
    assert thinking_extra_body(
        provider="sglang", mode="off", model_id="Qwen/Qwen3.5-35B"
    ) == {"chat_template_kwargs": {"enable_thinking": False}}
    assert thinking_extra_body(
        provider="sglang", mode="on", model_id="deepseek-ai/DeepSeek-V4"
    ) == {"chat_template_kwargs": {"thinking": True}}


def test_merge_removes_conflicting_switches_and_keeps_other_parameters() -> None:
    result = apply_thinking_mode(
        {
            "enable_thinking": True,
            "thinking": {"type": "enabled"},
            "chat_template_kwargs": {"thinking": True, "custom": "kept"},
            "thinking_budget": 512,
        },
        provider="vllm",
        mode="off",
        model_id="Qwen3",
    )
    assert result == {
        "chat_template_kwargs": {"custom": "kept", "enable_thinking": False},
        "thinking_budget": 512,
    }


def test_title_generator_forces_thinking_off_for_each_protocol() -> None:
    cases = [
        ("SiliconFlow", "deepseek-ai/DeepSeek-V4-Flash", {"enable_thinking": False}),
        ("阿里云百炼", "qwen-plus", {"enable_thinking": False}),
        ("DeepSeek", "deepseek-v4-pro", {"thinking": {"type": "disabled"}}),
        (
            "vLLM",
            "Qwen/Qwen3-32B",
            {"chat_template_kwargs": {"enable_thinking": False}},
        ),
        (
            "SGLang",
            "deepseek-ai/DeepSeek-V4",
            {"chat_template_kwargs": {"thinking": False}},
        ),
    ]
    for provider, model_id, expected in cases:
        generator = AgnoSessionTitleGenerator(
            model_id=model_id,
            base_url="http://localhost:8000/v1",
            api_key="test-placeholder",
            provider=provider,
        )
        assert generator.agent.model.extra_body == expected
        assert generator.agent.model.role_map["system"] == "system"
