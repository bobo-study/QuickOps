from __future__ import annotations

from pathlib import Path

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.session.summary import SessionSummaryManager
from agno.skills import Skills
from agno.skills.loaders.local import LocalSkills
from agno.tools import Toolkit
from agno.tools.shell import ShellTools

from quickops.domain import PermissionMode
from quickops.execution import default_executor
from quickops.host_adapter import HostAdapter
from quickops.local_host_adapter import LocalMacOSHostAdapter
from quickops.model_capabilities import apply_thinking_mode, compatible_chat_role_map
from quickops.settings import Settings
from quickops.tool_registry import build_enabled_toolkits
from quickops.toolkit import ManagedOperationsToolkit, ReadOnlyOperationsToolkit

AGENT_ID = "quickops-harness"


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
        configured = OpenAIChat(
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
    compression_token_limit = max(4_000, int(settings.max_context_tokens * 0.75))
    compression_manager = CompressionManager(
        model=configured_model(name_suffix=" context compressor"),
        compress_tool_results=True,
        compress_tool_results_limit=None,
        compress_token_limit=compression_token_limit,
    )
    session_summary_manager = SessionSummaryManager(
        model=configured_model(
            name_suffix=" session summarizer",
            portable_json_output=True,
            # Reasoning adds latency/tokens and commonly wraps JSON in prose. The
            # rolling summary is a deterministic maintenance call, so keep it off.
            thinking_mode="off",
        ),
        session_summary_prompt=(
            "你负责维护 QuickOps 运维会话的长期摘要。只保留用户目标、已确认事实、关键主机状态、"
            "已完成操作及其结果、未完成事项、风险决策和用户偏好。不要把工具原始输出逐字复制进摘要，"
            "不要省略仍影响后续操作的路径、标识符、错误码和配置值。输出简洁中文摘要。"
            "严格返回 JSON 对象，字段为 summary 字符串和 topics 字符串数组。"
        ),
    )
    tools = [ReadOnlyOperationsToolkit(adapter, settings.quickops_target_host_id)]
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
        function_names = ", ".join(sorted(toolkit.functions))
        enabled_tool_names.append(f"{toolkit.name}: {function_names}")
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
        + (
            "已启用并可调用的扩展工具：\n- " + "\n- ".join(enabled_tool_names)
            if enabled_tool_names
            else "当前没有启用可调用的扩展工具。"
        )
        + (
            "\n已启用但本次无法装载：\n- " + "\n- ".join(unavailable_tool_names)
            if unavailable_tool_names
            else ""
        )
        + "\n</quickops_live_toolbox>"
    )
    skill_root = Path(__file__).with_name("agno_skills")
    agent = Agent(
        id=AGENT_ID,
        name="小维",
        description="顶级运维专家，与操作员共同完成真实主机上的诊断、处置与复盘。",
        additional_context=(
            "<quickops_bound_target>\n"
            "以下信息由 QuickOps 服务端从真实 HostAdapter 注入，是当前会话不可猜测、"
            "不可替换的权威目标：\n"
            f"host_id={settings.quickops_target_host_id or '未绑定'}\n"
            f"hostname={settings.quickops_target_host_name or '未知'}\n"
            f"ip={settings.quickops_target_host_ip or '未知'}\n"
            f"platform={settings.quickops_target_host_platform or '未知'}\n"
            "你正在接管并观察这台主机。不要要求操作员再次提供 host_id，不要使用会话 ID"
            "作为 host_id，也不要引用其他开发机、macOS 测试机或原型主机。\n"
            "</quickops_bound_target>\n"
            + live_toolbox_context
        ),
        model=model,
        db=database,
        tools=tools,
        instructions=[
            "你的名字是小维。你是一位顶级运维专家，不要自称 QuickOps Harness Agent。",
            (
                "你处在人机协作的运维工作台中：操作员可直接提问，也可在同一会话的手动终端"
                "执行命令。上下文中的 MANUAL_COMMAND 是操作员本人输入的原始命令；"
                "SERVER_ECHO 是目标主机对该命令的真实回显。它们是既成事实证据，但绝不"
                "代表你调用过工具，也不要把操作员的手动操作说成你的执行结果。"
            ),
            (
                "当操作员提到相对路径、刚才的手动命令或主机回显时，先调用 "
                "get_operator_terminal_context 获取当前会话的真实 cwd 与结构化命令记录，"
                "不要依靠自然语言历史猜测。AI 命令工具与手动命令模式操作同一个会话 Shell，"
                "共享 cwd、环境变量与 Shell 状态；但 AI 工具仍受四级权限、HITL 与审计约束。"
            ),
            "始终以 quickops_bound_target 和真实工具输出判断操作系统，不得引用原型环境。",
            (
                "The active permission mode is " + permission_mode.value + ". Never claim a "
                "command ran unless its Agno tool event completed successfully."
            ),
            "Before concluding, collect only the minimum evidence needed using available tools.",
            "Keep host observations distinct from inference and state uncertainty explicitly.",
            "A high-CPU snapshot identifies the hot process, not the root cause by itself.",
            (
                "Never contradict tool output or report that evidence is absent when a tool "
                "returned it."
            ),
            (
                "Correlation is not proof of root cause. Use 'working hypothesis' with a "
                "confidence level unless a tool directly verifies causality."
            ),
            (
                "In read-only mode, present mutations only as approval-required follow-up. "
                "In approval modes, rely on Agno's confirmation requirement and never bypass it. "
                "When an operation needs approval, invoke the confirmation-protected tool "
                "immediately; do not ask for approval in conversational text because Agno will "
                "pause the run; the QuickOps approval panel will collect the operator's "
                "decision. "
                "After a confirmation-protected tool resumes and returns, the approval has "
                "already been resolved: report the actual tool result and never tell the "
                "operator to wait for or provide that approval again. "
                "Never request approval for a read-only observation, and if the user rejects an "
                "operation, do not request the same operation again unless the user explicitly "
                "asks."
            ),
            "Return a concise Chinese diagnosis with evidence, likely cause, and safe next steps.",
        ],
        skills=Skills(loaders=[LocalSkills(str(skill_root))]),
        # The Agno summary is the long-term compressed context. One immediately preceding run is
        # included only as a continuity bridge while its asynchronous summary is being persisted.
        add_history_to_context=True,
        num_history_runs=1,
        enable_session_summaries=True,
        add_session_summary_to_context=True,
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
        tool_call_limit=8,
    )
    # Agno normally awaits summary generation before yielding RunCompleted. Keep Agno's native
    # summary manager and summary-in-context behavior, but let QuickOps schedule the update after
    # the visible run completes so a maintenance LLM call never prolongs the user's reply state.
    agent.enable_session_summaries = False
    return agent, adapter, database
