from __future__ import annotations

from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.exceptions import ModelProviderError
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.session.summary import SessionSummaryManager
from agno.skills import Skills
from agno.skills.loaders.local import LocalSkills
from agno.tools import Toolkit
from agno.tools.shell import ShellTools
from agno.tools.user_feedback import UserFeedbackTools

from quickops.domain import PermissionMode
from quickops.execution import default_executor
from quickops.host_adapter import HostAdapter
from quickops.local_host_adapter import LocalMacOSHostAdapter
from quickops.model_capabilities import apply_thinking_mode, compatible_chat_role_map
from quickops.settings import Settings
from quickops.tool_registry import build_enabled_toolkits
from quickops.toolkit import ManagedOperationsToolkit, ReadOnlyOperationsToolkit

AGENT_ID = "quickops-harness"


def _enrich_empty_provider_error(error: ModelProviderError) -> ModelProviderError:
    """Recover safe HTTP/code diagnostics that Agno drops from empty provider errors."""
    if "unknown model error" not in str(error).casefold():
        return error
    status_code = int(getattr(error, "status_code", 502) or 502)
    error_code: str | int | None = None
    response = getattr(getattr(error, "__cause__", None), "response", None)
    if response is not None:
        status_code = int(getattr(response, "status_code", status_code) or status_code)
        try:
            body: Any = response.json()
            provider_error = body.get("error", body) if isinstance(body, dict) else None
            if isinstance(provider_error, dict):
                error_code = provider_error.get("code")
        except Exception:
            error_code = None
    qualifier = f"，错误码 {error_code}" if error_code is not None else ""
    message = f"模型服务端请求失败（HTTP {status_code}{qualifier}）"
    return ModelProviderError(
        message=message,
        status_code=status_code,
        model_name=getattr(error, "model_name", None),
        model_id=getattr(error, "model_id", None),
    )


class QuickOpsOpenAIChat(OpenAIChat):
    """OpenAI-compatible adapter that preserves actionable empty-error diagnostics."""

    async def ainvoke(self, *args: Any, **kwargs: Any):
        try:
            return await super().ainvoke(*args, **kwargs)
        except ModelProviderError as error:
            enriched = _enrich_empty_provider_error(error)
            if enriched is error:
                raise
            raise enriched from error

    async def ainvoke_stream(self, *args: Any, **kwargs: Any):
        try:
            async for response in super().ainvoke_stream(*args, **kwargs):
                yield response
        except ModelProviderError as error:
            enriched = _enrich_empty_provider_error(error)
            if enriched is error:
                raise
            raise enriched from error


def _bounded_context_text(value: Any, limit: int) -> str:
    """Keep both ends of large evidence while making its omission explicit."""
    text = str(value or "")
    if len(text) <= limit:
        return text
    marker = f"\n\n… [QuickOps omitted {len(text) - limit:,} characters] …\n\n"
    remaining = max(0, limit - len(marker))
    head = remaining * 2 // 3
    return text[:head] + marker + text[-(remaining - head) :]


class QuickOpsCompressionManager(CompressionManager):
    """Agno compression with a deterministic fail-closed size boundary.

    Agno deliberately returns the original tool content when its compression-model call
    fails.  That is lossless, but it can immediately overflow the primary model when one log
    tool returns a very large payload.  QuickOps keeps the original evidence in durable run
    events and bounds only the copy sent back into model context.
    """

    source_char_limit = 32_000
    compressed_char_limit = 8_000

    def configure_context_budget(self, max_context_tokens: int) -> None:
        """Scale evidence and summary sizes without filling the compressor context.

        Provider-advertised limits are not always the limits enforced by the selected
        upstream route. In particular, a model configured for 200K may be routed to a
        node enforcing roughly 120K. Keeping the compression input near 35% leaves room
        for provider tokenisation variance, the compression prompt and the generated
        summary. The summary itself receives a materially larger 12% budget while still
        leaving most of the primary context for conversation state and the next answer.
        """
        context_tokens = max(8_000, int(max_context_tokens or 0))
        self.source_char_limit = max(16_000, min(70_000, int(context_tokens * 0.35)))
        self.compressed_char_limit = max(
            16_000, min(32_000, int(context_tokens * 0.12))
        )

    def _oversized_uncompressed_tool(self, messages: list[Message]) -> bool:
        return any(
            message.role == "tool"
            and message.compressed_content is None
            and len(str(message.content or "")) > self.source_char_limit
            for message in messages
        )

    def should_compress(self, messages: list[Message], *args: Any, **kwargs: Any) -> bool:
        if self._oversized_uncompressed_tool(messages):
            return True
        return super().should_compress(messages, *args, **kwargs)

    async def ashould_compress(
        self, messages: list[Message], *args: Any, **kwargs: Any
    ) -> bool:
        if self._oversized_uncompressed_tool(messages):
            return True
        return await super().ashould_compress(messages, *args, **kwargs)

    def _bounded_tool_result(self, tool_result: Message) -> Message:
        bounded = tool_result.model_copy(deep=True)
        bounded.content = _bounded_context_text(tool_result.content, self.source_char_limit)
        return bounded

    def _compress_tool_result(self, tool_result: Message, run_metrics: Any = None) -> str | None:
        compressed = super()._compress_tool_result(
            self._bounded_tool_result(tool_result), run_metrics=run_metrics
        )
        return (
            _bounded_context_text(compressed, self.compressed_char_limit)
            if compressed is not None
            else None
        )

    async def _acompress_tool_result(
        self, tool_result: Message, run_metrics: Any = None
    ) -> str | None:
        compressed = await super()._acompress_tool_result(
            self._bounded_tool_result(tool_result), run_metrics=run_metrics
        )
        return (
            _bounded_context_text(compressed, self.compressed_char_limit)
            if compressed is not None
            else None
        )

def build_runtime(
    settings: Settings,
    host_adapter: HostAdapter | None = None,
    permission_mode: PermissionMode = PermissionMode.APPROVAL,
    command_toolkit: Toolkit | None = None,
) -> tuple[Agent, HostAdapter, SqliteDb]:
    settings.ensure_data_dir()
    # Host observation remains adapter-bound. AI command authority is separately selected from
    # the four-level permission model below; manual terminal commands never enter this tool list.
    adapter = host_adapter or LocalMacOSHostAdapter()
    database = SqliteDb(db_file=str(settings.quickops_db_file), id="quickops-agent-db")

    def configured_model(
        *,
        name_suffix: str = "",
        portable_json_output: bool = False,
        thinking_mode: str | None = None,
    ) -> OpenAIChat:
        configured = QuickOpsOpenAIChat(
            id=settings.model_id,
            name=f"{settings.model_id} via {settings.model_provider}{name_suffix}",
            provider=settings.model_provider,
            api_key=settings.siliconflow_api_key,
            base_url=settings.model_base_url,
            retries=2,
            delay_between_retries=1,
            exponential_backoff=True,
            timeout=60,
            role_map=compatible_chat_role_map(),
            extra_body=apply_thinking_mode(
                None,
                provider=settings.model_provider,
                mode=thinking_mode or settings.thinking_mode,
                model_id=settings.model_id,
                base_url=settings.model_base_url,
            ),
        )
        if portable_json_output:
            # SiliconFlow, DashScope, DeepSeek and self-hosted OpenAI-compatible
            # endpoints do not consistently implement native json_schema output even
            # when the generic OpenAI adapter advertises it. Let Agno request the
            # portable json_object format and parse SessionSummaryResponse itself.
            configured.supports_native_structured_outputs = False
            configured.supports_json_schema_outputs = False
        return configured

    model = configured_model()
    # Agno keeps complete tool events in persistence, but replaces verbose tool messages with
    # model-generated compressed_content for subsequent model turns once the configured context
    # budget is approached. Keep 25% for the next answer and provider token-count variance.
    compression_token_limit = max(
        4_000, int(settings.max_context_tokens * settings.quickops_tool_compression_ratio)
    )
    compression_manager = QuickOpsCompressionManager(
        model=configured_model(name_suffix=" context compressor"),
        compress_tool_results=True,
        compress_tool_results_limit=None,
        compress_token_limit=compression_token_limit,
    )
    compression_manager.configure_context_budget(settings.max_context_tokens)
    session_summary_prompt = (
        "你负责维护 QuickOps 运维会话的长期摘要。只保留用户目标、已确认事实、关键主机状态、"
        "已完成操作及其结果、未完成事项、风险决策和用户偏好。不要把工具原始输出逐字复制进摘要，"
        "不要省略仍影响后续操作的路径、标识符、错误码和配置值。输出简洁中文摘要。"
        "严格返回 JSON 对象，字段为 summary 字符串和 topics 字符串数组。"
    )
    session_summary_manager = SessionSummaryManager(
        model=configured_model(
            name_suffix=" session summarizer",
            portable_json_output=True,
            # Reasoning adds latency/tokens and commonly wraps JSON in prose. The
            # rolling summary is a deterministic maintenance call, so keep it off.
            thinking_mode="off",
        ),
        session_summary_prompt=session_summary_prompt,
    )
    tools = [
        ReadOnlyOperationsToolkit(adapter, settings.quickops_target_host_id),
        UserFeedbackTools(
            instructions=(
                "当任务确实需要操作员从明确方案中选择后才能继续时，调用 ask_user。"
                "每次只提出一个关键问题，最多提供 3 个确定选项，选项使用简短中文标签并说明影响；"
                "QuickOps 会自动补上可手动输入的‘其他’末选项。不要用它代替命令审批，"
                "也不要在已有足够信息时打断任务。QuickOps 会把问题显示为输入框上方的快捷选项卡。"
            ),
        ),
    ]
    if command_toolkit is not None:
        tools.append(command_toolkit)
    elif permission_mode in {
        PermissionMode.APPROVAL,
        PermissionMode.DELEGATED_APPROVAL,
    }:
        tools.append(
            ManagedOperationsToolkit(
                default_executor(settings.quickops_workspace_root), permission_mode
            )
        )
    elif permission_mode == PermissionMode.FULL_ACCESS:
        tools.append(ShellTools(base_dir=settings.quickops_workspace_root))
    optional_toolkits = build_enabled_toolkits(
        settings.enabled_toolkits,
        configs=settings.toolkit_config,
        workspace_root=settings.quickops_workspace_root,
        permission_mode=permission_mode,
    )
    tools.extend(optional_toolkits.tools)
    enabled_tool_names = []
    for toolkit in optional_toolkits.tools:
        enabled_tool_names.append(toolkit.name)
    unavailable_tool_names = [
        f"{report.id}: {report.reason}"
        for report in optional_toolkits.reports
        if report.enabled and not report.available
    ]
    live_toolbox_context = (
        "<quickops_live_toolbox>\n"
        "这是本次运行开始时由服务端重新装配的权威工具清单。它覆盖会话历史或长期摘要中"
        "关于工具未启用、不可用或不存在的旧结论；设置中刚启用的工具在当前既有会话的"
        "下一次运行立即生效，不需要新建会话。\n"
        + ("enabled=" + ",".join(enabled_tool_names) if enabled_tool_names else "enabled=none")
        + ("\nunavailable=" + " | ".join(unavailable_tool_names) if unavailable_tool_names else "")
        + "\n</quickops_live_toolbox>"
    )
    skill_root = Path(__file__).with_name("agno_skills")
    runtime_context = (
        "<quickops_runtime_snapshot>\n"
        "以下信息由 QuickOps 服务端在本次运行开始时注入。它是追加式、不可猜测、"
        "不可替换的权威运行快照：\n"
        f"host_id={settings.quickops_target_host_id or '未绑定'}\n"
        f"hostname={settings.quickops_target_host_name or '未知'}\n"
        f"ip={settings.quickops_target_host_ip or '未知'}\n"
        f"platform={settings.quickops_target_host_platform or '未知'}\n"
        f"permission_mode={permission_mode.value}\n"
        "你正在接管并观察这台主机。不要要求操作员再次提供 host_id，不要使用会话 ID"
        "作为 host_id，也不要引用其他开发机、macOS 测试机或原型主机。\n"
        + live_toolbox_context
        + "\n</quickops_runtime_snapshot>"
    )
    agent = Agent(
        id=AGENT_ID,
        name="小维",
        description="顶级运维专家，与操作员共同完成真实主机上的诊断、处置与复盘。",
        # Mutable host/toolbox/permission facts are deliberately not placed in the system
        # message. BackgroundRunManager appends them to the current user turn so previous
        # requests remain an exact provider-cache prefix, matching DeepSeek Harness' model.
        additional_context=None,
        model=model,
        db=database,
        tools=tools,
        instructions=[
            (
                "你叫小维，是与操作员协作、直接接管当前绑定主机的顶级运维专家。"
                "不要自称 Agent、助手或 QuickOps Harness Agent。"
            ),
            (
                "以服务端 quickops_runtime_snapshot 为当前主机、权限和工具能力的唯一权威。"
                "不要索要已有 host_id，不要猜测环境，不要把旧摘要中的工具可用性覆盖当前工具清单。"
            ),
            (
                "遵循运维闭环：理解目标→用最少的只读证据确认现状→区分事实、推断和未知→形成带置信度的工作假设→"
                "在权限允许时执行最小变更→验证结果→给出结论、影响、回滚/后续。单一快照或相关性不是根因证据。"
            ),
            (
                "MANUAL_COMMAND 是操作员在本会话共享终端输入的命令，"
                "SERVER_ECHO 是主机真实回显，二者不是你的工具调用。"
                "涉及相对路径、刚才命令或终端状态时先调用 "
                "get_operator_terminal_context；你的命令工具与该终端共享 cwd 和状态。"
            ),
            (
                "严格服从四级权限。只读观察不得申请审批；审批执行中的变更走 Agno HITL；"
                "替我审批会由服务端自动放行"
                "只读、低风险和一般可恢复变更，仅高风险/严重风险交给操作员；完全访问不确认。"
                "需要确认时直接调用受保护工具，不在正文里索要批准；恢复后只报告真实执行结果。"
            ),
            (
                "工具成功事件才代表操作已执行。不得编造结果、忽略错误或重复索取已经提供的信息。"
                "需要操作员从明确方案中选择时使用 ask_user 快捷选项；开放式说明才用普通文本提问。"
            ),
            "默认用简洁中文输出：结论优先，随后列关键证据、风险/不确定性和安全下一步；简单问题不套模板。",
        ],
        skills=Skills(loaders=[LocalSkills(str(skill_root))]),
        # Include the whole current epoch. BackgroundRunManager starts a new compacted epoch at a
        # fixed token threshold, so we never delete one old run on every request like a sliding
        # window. Complete UI/audit history remains in QuickOps storage.
        add_history_to_context=True,
        num_history_runs=None,
        enable_session_summaries=True,
        # Agno normally rewrites the rolling summary into the system message, invalidating the
        # cache after the first changed summary token. QuickOps still uses Agno's manager and
        # persistence, but appends the current summary as a user-turn checkpoint instead.
        add_session_summary_to_context=False,
        session_summary_manager=session_summary_manager,
        compress_tool_results=True,
        compression_manager=compression_manager,
        # Provider prompt caches match an exact prefix. Agno's per-request datetime was
        # previously inserted in the middle of the system message, invalidating every
        # static instruction after it. Time remains available through read-only host tools.
        add_datetime_to_context=False,
        markdown=True,
        store_events=True,
        stream_events=True,
        tool_call_limit=settings.quickops_tool_call_limit,
    )
    # Deliberately outside Agent.additional_context: run_manager appends this snapshot after the
    # stable system prompt and retained history. It remains durable in Agno's session log.
    agent.quickops_runtime_context = runtime_context
    # Agent's constructor normalizes an explicit None to its three-run default. Reset it after
    # construction so the current context epoch is append-only until our fixed threshold fires.
    agent.num_history_runs = None
    agent.quickops_max_context_tokens = settings.max_context_tokens
    agent.quickops_context_compaction_tokens = max(
        4_000, int(settings.max_context_tokens * settings.quickops_context_compaction_ratio)
    )
    agent.quickops_context_checkpoint_runs = settings.quickops_context_checkpoint_runs
    agent.quickops_summary_base_prompt = session_summary_prompt
    # Agno normally awaits summary generation before yielding RunCompleted. Keep Agno's native
    # summary manager and summary-in-context behavior, but let QuickOps schedule the update after
    # the visible run completes so a maintenance LLM call never prolongs the user's reply state.
    agent.enable_session_summaries = False
    return agent, adapter, database
