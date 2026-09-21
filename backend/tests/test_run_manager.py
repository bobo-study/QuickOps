from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from quickops.run_manager import BackgroundRunManager, _message_segments, map_agno_event
from quickops.storage import QuickOpsStorage
from quickops.title_generator import fallback_title, normalize_title


class FakeTitleGenerator:
    async def generate(self, first_user_message: str) -> str:
        assert first_user_message == "生产 nginx 为什么很慢？"
        return "nginx 延迟排查"


class FailingTitleGenerator:
    async def generate(self, _first_user_message: str) -> str:
        raise RuntimeError("title provider unavailable")


class FakeAgent:
    async def arun(self, _message, **kwargs):
        assert kwargs["stream"] is True
        assert kwargs["stream_events"] is True

        async def events():
            yield SimpleNamespace(event="RunStarted")
            yield SimpleNamespace(event="ReasoningStarted")
            yield SimpleNamespace(event="ReasoningContentDelta", reasoning_content="检查指标")
            yield SimpleNamespace(event="ReasoningCompleted")
            yield SimpleNamespace(event="RunContent", content="负载")
            yield SimpleNamespace(event="RunContent", content="正常")
            # Full content must not be appended a second time.
            yield SimpleNamespace(event="RunCompleted", content="负载正常")

        return events()


class FakeBillingFailureAgent:
    async def arun(self, _message, **_kwargs):
        async def events():
            yield SimpleNamespace(event="RunContent", content="已完成环境检查。")
            yield SimpleNamespace(event="RunError", content="insufficient_balance")

        return events()


class FakeSummaryManager:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.session_summary_prompt = "base summary prompt"
        self.prompt_seen = None

    async def acreate_session_summary(self, *, session):
        self.prompt_seen = self.session_summary_prompt
        self.started.set()
        await self.release.wait()
        session.summary = "updated"


class FakeAgentWithSlowSummary(FakeAgent):
    def __init__(self):
        self.session_summary_manager = FakeSummaryManager()
        self.session = SimpleNamespace(
            summary=None,
            runs=[SimpleNamespace(), SimpleNamespace()],
            metadata={},
            get_messages=lambda **_kwargs: [object()],
        )
        self.model = SimpleNamespace(acount_tokens=self._count_tokens)
        self.id = "fake-agent"
        self.quickops_context_compaction_tokens = 1
        self.quickops_context_checkpoint_runs = 1
        self.quickops_summary_base_prompt = "base summary prompt"
        self.saved = False

    async def _count_tokens(self, _messages):
        return 2

    async def aget_session(self, **_kwargs):
        return self.session

    async def asave_session(self, _session):
        self.saved = True


class FakeCacheContextAgent:
    quickops_runtime_context = "<runtime>host=server-1</runtime>"
    session_summary_manager = object()

    def __init__(self):
        self.session = SimpleNamespace(
            summary=SimpleNamespace(summary="此前已确认 nginx 正常"), metadata={}
        )

    async def aget_session(self, **_kwargs):
        return self.session

    async def asave_session(self, session):
        self.session = session


class FakeConfirmationRequirement:
    needs_confirmation = True

    def __init__(self, requirement_id="req-1", command="safe-test-file"):
        self.approved = None
        self.requirement_id = requirement_id
        self.command = command

    def to_dict(self):
        return {
            "id": self.requirement_id,
            "needs_confirmation": True,
            "tool_execution": {
                "tool_name": "run_shell_command",
                "tool_args": {"args": ["touch", self.command]},
            },
        }

    def confirm(self):
        self.approved = True

    def reject(self, _note=None):
        self.approved = False


@pytest.mark.asyncio
async def test_runtime_snapshot_and_request_time_are_appended_to_current_turn(tmp_path):
    storage = QuickOpsStorage(tmp_path / "runs.db")
    manager = BackgroundRunManager(storage)

    agent = FakeCacheContextAgent()
    model_input = await manager._cache_friendly_model_input(agent, "继续检查", "s1", "operator")

    assert model_input.index("<runtime>") < model_input.index("<operator_request>")
    assert "<quickops_session_summary>" not in model_input
    assert model_input.endswith("</request_time_utc>")
    assert model_input.index("</operator_request>") < model_input.index("<request_time_utc>")

    second_input = await manager._cache_friendly_model_input(agent, "继续验证", "s1", "operator")
    assert "<runtime>" not in second_input
    assert second_input.endswith("</request_time_utc>")


@pytest.mark.asyncio
async def test_interrupted_turn_remains_available_until_a_retry_completes(tmp_path):
    storage = QuickOpsStorage(tmp_path / "interrupted.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    storage.append_message("s1", role="user", content="排查 MinerU GPU 错误")
    storage.append_message(
        "s1",
        role="assistant",
        content="已确认容器内 NVML 初始化失败。\n\n> ⚠️ 审计写入失败",
        metadata={"status": "failed", "run_id": "failed-1"},
    )
    storage.append_message("s1", role="user", content="先确认这个镜像是否属于目标服务")
    storage.append_message("s1", role="user", content="怎么样？")
    manager = BackgroundRunManager(storage)
    agent = FakeCacheContextAgent()

    first = await manager._cache_friendly_model_input(agent, "怎么样？", "s1", "operator")
    assert "quickops_interrupted_run_checkpoint" in first
    assert "排查 MinerU GPU 错误" in first
    assert "NVML 初始化失败" in first
    assert "先确认这个镜像是否属于目标服务" in first

    second = await manager._cache_friendly_model_input(agent, "继续", "s1", "operator")
    assert "quickops_interrupted_run_checkpoint" in second

    await manager._mark_recovery_checkpoint_consumed(agent, "s1", "operator")
    third = await manager._cache_friendly_model_input(agent, "继续", "s1", "operator")
    assert "quickops_interrupted_run_checkpoint" not in third


class FakePausedAgent:
    def __init__(self):
        self.requirement = FakeConfirmationRequirement()
        self.pause_stream_exhausted = False

    async def arun(self, _message, **_kwargs):
        async def events():
            yield SimpleNamespace(event="RunStarted")
            yield SimpleNamespace(event="RunContent", content="准备执行。")
            yield SimpleNamespace(event="RunPaused", requirements=[self.requirement])
            self.pause_stream_exhausted = True

        return events()

    async def acontinue_run(self, **kwargs):
        assert kwargs["requirements"] == [self.requirement]
        assert self.requirement.approved is True
        completed_tool = SimpleNamespace(
            to_dict=lambda: {
                "tool_call_id": "approved-tool-1",
                "tool_name": "run_shell_command",
                "result": "created",
            }
        )

        async def events():
            yield SimpleNamespace(event="ToolCallCompleted", tool=completed_tool)
            yield SimpleNamespace(event="RunContent", content="执行完成。")
            yield SimpleNamespace(event="RunCompleted", content="准备执行。执行完成。")

        return events()


class FakeEmptyAfterApprovalAgent(FakePausedAgent):
    async def acontinue_run(self, **kwargs):
        assert kwargs["requirements"] == [self.requirement]
        assert self.requirement.approved is True
        completed_tool = SimpleNamespace(
            to_dict=lambda: {
                "tool_call_id": "approved-tool-empty",
                "tool_name": "run_shell_command",
                "result": "diagnostic result",
            }
        )

        async def events():
            yield SimpleNamespace(event="ToolCallCompleted", tool=completed_tool)
            yield SimpleNamespace(event="RunContent", content="")
            yield SimpleNamespace(event="RunCompleted", content="准备执行。")

        return events()


class FakeMultiPausedAgent:
    def __init__(self):
        self.requirements = [
            FakeConfirmationRequirement("req-older", "older-file"),
            FakeConfirmationRequirement("req-latest", "latest-file"),
        ]

    async def arun(self, _message, **_kwargs):
        async def events():
            yield SimpleNamespace(event="RunPaused", requirements=self.requirements)

        return events()

    async def acontinue_run(self, **kwargs):
        assert kwargs["requirements"] == self.requirements
        assert self.requirements[0].approved is False
        assert self.requirements[1].approved is True

        async def events():
            yield SimpleNamespace(event="RunContent", content="只执行最新申请。")
            yield SimpleNamespace(event="RunCompleted", content="只执行最新申请。")

        return events()


class FakeMisroutedReadonlyAgent:
    def __init__(self):
        self.requirement = FakeConfirmationRequirement("req-ls", "unused")
        self.requirement.command = "ls"
        self.requirement.to_dict = lambda: {
            "id": "req-ls",
            "needs_confirmation": True,
            "tool_execution": {
                "tool_name": "execute_change_command",
                "tool_args": {"args": ["ls"]},
            },
        }

    async def arun(self, _message, **_kwargs):
        async def events():
            yield SimpleNamespace(event="RunPaused", requirements=[self.requirement])

        return events()

    async def acontinue_run(self, **_kwargs):
        assert self.requirement.approved is True

        async def events():
            yield SimpleNamespace(event="RunContent", content="只读命令已直接执行。")
            yield SimpleNamespace(event="RunCompleted", content="只读命令已直接执行。")

        return events()


class FakeFeedbackRequirement:
    def __init__(self):
        self.requirement_id = "feedback-1"
        self.needs_confirmation = False
        self.needs_user_feedback = True
        self.answer = None
        self.user_feedback_schema = [
            SimpleNamespace(
                question="选择排查深度",
                header="排查范围",
                multi_select=False,
                selected_options=None,
                options=[
                    SimpleNamespace(label="快速检查", description="只读检查关键状态"),
                    SimpleNamespace(label="深入排查", description="扩大只读证据范围"),
                ],
            )
        ]

    def to_dict(self):
        return {
            "id": self.requirement_id,
            "needs_user_feedback": self.needs_user_feedback,
            "user_feedback_schema": [
                {
                    "question": "选择排查深度",
                    "header": "排查范围",
                    "multi_select": False,
                    "options": [
                        {"label": "快速检查", "description": "只读检查关键状态"},
                        {"label": "深入排查", "description": "扩大只读证据范围"},
                    ],
                }
            ],
        }

    def provide_user_feedback(self, selections):
        values = selections.get("选择排查深度")
        if values:
            self.answer = values
            self.needs_user_feedback = False


class FakeFeedbackAgent:
    def __init__(self):
        self.requirement = FakeFeedbackRequirement()

    async def arun(self, _message, **_kwargs):
        async def events():
            yield SimpleNamespace(event="RunContent", content="请选择排查深度。")
            yield SimpleNamespace(event="RunPaused", requirements=[self.requirement])

        return events()

    async def acontinue_run(self, **kwargs):
        assert kwargs["requirements"] == [self.requirement]
        assert self.requirement.answer == ["快速检查"]

        async def events():
            yield SimpleNamespace(event="RunContent", content="开始快速检查。")
            yield SimpleNamespace(event="RunCompleted", content="请选择排查深度。开始快速检查。")

        return events()


class FakeSlowAgent:
    def __init__(self):
        self.started = asyncio.Event()

    async def arun(self, _message, **_kwargs):
        async def events():
            yield SimpleNamespace(event="RunContent", content="已生成部分")
            self.started.set()
            await asyncio.Event().wait()

        return events()


class FakeInterleavedToolAgent:
    async def arun(self, _message, **_kwargs):
        started_tool = SimpleNamespace(
            to_dict=lambda: {
                "tool_call_id": "tool-1",
                "tool_name": "system_status",
            }
        )
        completed_tool = SimpleNamespace(
            to_dict=lambda: {
                "tool_call_id": "tool-1",
                "tool_name": "system_status",
                "result": "cpu=10%",
            }
        )

        async def events():
            yield SimpleNamespace(event="RunContent", content="先检查状态。")
            yield SimpleNamespace(event="ToolCallStarted", tool=started_tool)
            yield SimpleNamespace(event="ToolCallCompleted", tool=completed_tool)
            yield SimpleNamespace(event="RunContent", content="状态正常。")
            yield SimpleNamespace(event="RunCompleted", content="先检查状态。状态正常。")

        return events()


class FakePartialDeltaAgent:
    async def arun(self, _message, **_kwargs):
        async def events():
            yield SimpleNamespace(event="RunContent", content="已经整理了前半部分。")
            yield SimpleNamespace(
                event="RunCompleted",
                content="已经整理了前半部分。这里是仅在完成事件中返回的后半部分。",
            )

        return events()


class FakeFileAgent(FakeAgent):
    def __init__(self):
        self.files = None
        self.images = None

    async def arun(self, _message, **kwargs):
        self.files = kwargs.get("files")
        self.images = kwargs.get("images")
        return await super().arun(_message, **kwargs)


@pytest.mark.asyncio
async def test_background_run_streams_persists_and_generates_title(tmp_path):
    storage = QuickOpsStorage(tmp_path / "runs.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    storage.append_message("s1", role="user", content="生产 nginx 为什么很慢？")
    manager = BackgroundRunManager(
        storage, title_generator=FakeTitleGenerator(), poll_interval=0.001
    )

    run = manager.start(FakeAgent(), message="生产 nginx 为什么很慢？", session_id="s1")
    events = [event async for event in manager.subscribe(run["id"])]

    assert storage.get_run(run["id"])["output_text"] == "负载正常"
    assert [event["event_type"] for event in events] == [
        "run.started",
        "reasoning.started",
        "reasoning.delta",
        "reasoning.completed",
        "content.delta",
        "content.delta",
        "run.completed",
    ]
    assert storage.list_messages("s1")[-1]["content"] == "负载正常"
    # Title generation is independent and may settle immediately after the run stream.
    for task in list(manager._title_tasks):
        await task
    assert storage.get_session("s1")["title"] == "nginx 延迟排查"


@pytest.mark.asyncio
async def test_title_generation_failure_uses_local_fallback(tmp_path):
    storage = QuickOpsStorage(tmp_path / "title-fallback.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    storage.append_message("s1", role="user", content="帮我排查 nginx 响应变慢的问题")
    manager = BackgroundRunManager(
        storage, title_generator=FailingTitleGenerator(), poll_interval=0.001
    )

    run = manager.start(FakeAgent(), message="帮我排查 nginx 响应变慢的问题", session_id="s1")
    _ = [event async for event in manager.subscribe(run["id"])]
    for task in list(manager._title_tasks):
        await task

    assert storage.get_session("s1")["title"] == "排查 nginx 响应变慢的问题"


@pytest.mark.asyncio
async def test_background_run_passes_files_to_agno_agent(tmp_path):
    from agno.media import File

    storage = QuickOpsStorage(tmp_path / "file-run.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    manager = BackgroundRunManager(storage, poll_interval=0.001)
    agent = FakeFileAgent()
    attached = File(content=b"hello", filename="notes.txt", mime_type="text/plain")
    image = object()

    run = manager.start(
        agent,
        message="阅读附件",
        session_id="s1",
        files=[attached],
        images=[image],
    )
    _ = [event async for event in manager.subscribe(run["id"])]

    assert agent.files == [attached]
    assert agent.images == [image]


@pytest.mark.asyncio
async def test_session_summary_does_not_delay_visible_run_completion(tmp_path):
    storage = QuickOpsStorage(tmp_path / "summary.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    manager = BackgroundRunManager(storage, poll_interval=0.001)
    agent = FakeAgentWithSlowSummary()

    run = manager.start(agent, message="检查", session_id="s1")
    events = [event async for event in manager.subscribe(run["id"])]

    assert events[-1]["event_type"] == "run.completed"
    assert storage.get_run(run["id"])["status"] == "completed"
    await agent.session_summary_manager.started.wait()
    assert agent.saved is False
    agent.session_summary_manager.release.set()
    for task in list(manager._summary_tasks.values()):
        await task
    assert agent.saved is True


@pytest.mark.asyncio
async def test_context_checkpoint_is_cumulative_across_compaction_epochs(tmp_path):
    storage = QuickOpsStorage(tmp_path / "cumulative-summary.db")
    manager = BackgroundRunManager(storage)
    agent = FakeAgentWithSlowSummary()
    agent.session.metadata = {
        "quickops_context_checkpoint": "旧纪元已确认 nginx 配置路径为 /etc/nginx/nginx.conf"
    }

    manager._schedule_session_summary(agent, "s1", "operator", observed_input_tokens=2)
    await agent.session_summary_manager.started.wait()
    assert "旧纪元已确认 nginx 配置路径" in agent.session_summary_manager.prompt_seen
    agent.session_summary_manager.release.set()
    for task in list(manager._summary_tasks.values()):
        await task

    assert agent.session_summary_manager.session_summary_prompt == "base summary prompt"
    assert agent.session.metadata["quickops_context_epoch"] == 1
    assert agent.session.metadata["quickops_context_checkpoint"] == "updated"


@pytest.mark.asyncio
async def test_waiting_for_compaction_emits_explicit_run_status(tmp_path):
    storage = QuickOpsStorage(tmp_path / "compaction-status.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    run = storage.create_run("run-1", session_id="s1", user_id="operator", input_text="继续")
    manager = BackgroundRunManager(storage)
    release = asyncio.Event()

    async def pending_summary():
        await release.wait()

    manager._summary_tasks["s1"] = asyncio.create_task(pending_summary())
    waiting = asyncio.create_task(manager._wait_for_session_summary("s1", run["id"]))
    await asyncio.sleep(0)
    assert storage.list_run_events(run["id"])[-1]["event_type"] == (
        "context.compaction.started"
    )
    release.set()
    await waiting
    assert [event["event_type"] for event in storage.list_run_events(run["id"])] == [
        "context.compaction.started",
        "context.compaction.completed",
    ]


def test_implausible_provider_usage_does_not_trigger_false_compaction():
    agent = SimpleNamespace(quickops_max_context_tokens=128_000)
    assert BackgroundRunManager._valid_observed_context_tokens(
        agent, {"input_tokens": 92_000, "total_tokens": 93_000}
    ) == 92_000
    assert BackgroundRunManager._valid_observed_context_tokens(
        agent, {"input_tokens": 36_578_331, "total_tokens": 36_689_379}
    ) == 0


@pytest.mark.asyncio
async def test_completed_message_preserves_interleaved_tool_timeline(tmp_path):
    storage = QuickOpsStorage(tmp_path / "segments.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    manager = BackgroundRunManager(storage, poll_interval=0.001)

    run = manager.start(FakeInterleavedToolAgent(), message="检查", session_id="s1")
    _ = [event async for event in manager.subscribe(run["id"])]

    message = storage.list_messages("s1")[-1]
    segments = message["metadata"]["segments"]
    assert [segment["type"] for segment in segments] == ["text", "tool", "text"]
    assert segments[0]["content"] == "先检查状态。"
    assert segments[1]["status"] == "completed"
    assert segments[1]["tool"]["result"] == "cpu=10%"
    assert segments[2]["content"] == "状态正常。"


def test_multiple_approval_continuations_keep_complete_ordered_timeline():
    events = [
        {"event_type": "content.delta", "payload": {"delta": "开始。"}},
        {
            "event_type": "approval.resolved",
            "payload": {"decision": "approved", "content": "用户批准了操作 A"},
        },
        {
            "event_type": "tool.started",
            "payload": {"tool": {"tool_call_id": "a", "tool_name": "operation_a"}},
        },
        {
            "event_type": "tool.completed",
            "payload": {
                "tool": {"tool_call_id": "a", "tool_name": "operation_a", "result": "A ok"}
            },
        },
        {"event_type": "content.delta", "payload": {"delta": "继续。"}},
        {
            "event_type": "approval.resolved",
            "payload": {"decision": "approved", "content": "用户批准了操作 B"},
        },
        {
            "event_type": "tool.started",
            "payload": {"tool": {"tool_call_id": "b", "tool_name": "operation_b"}},
        },
        {
            "event_type": "tool.completed",
            "payload": {
                "tool": {"tool_call_id": "b", "tool_name": "operation_b", "result": "B ok"}
            },
        },
        {"event_type": "content.delta", "payload": {"delta": "完成。"}},
    ]

    segments = _message_segments(events, "开始。继续。完成。")
    assert [segment["type"] for segment in segments] == [
        "text",
        "approval",
        "tool",
        "text",
        "approval",
        "tool",
        "text",
    ]
    assert segments[1]["content"] == "用户批准了操作 A"
    assert segments[2]["tool"]["result"] == "A ok"
    assert segments[4]["content"] == "用户批准了操作 B"
    assert segments[5]["tool"]["result"] == "B ok"


@pytest.mark.asyncio
async def test_terminal_content_completes_a_partial_delta_stream(tmp_path):
    storage = QuickOpsStorage(tmp_path / "partial-deltas.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    manager = BackgroundRunManager(storage, poll_interval=0.001)

    run = manager.start(FakePartialDeltaAgent(), message="整理文档", session_id="s1")
    events = [event async for event in manager.subscribe(run["id"])]

    expected = "已经整理了前半部分。这里是仅在完成事件中返回的后半部分。"
    message = storage.list_messages("s1")[-1]
    assert storage.get_run(run["id"])["output_text"] == expected
    assert message["content"] == expected
    assert (
        "".join(
            segment["content"]
            for segment in message["metadata"]["segments"]
            if segment["type"] == "text"
        )
        == expected
    )
    assert events[-1]["payload"]["content"] == expected


@pytest.mark.asyncio
async def test_paused_run_is_persisted_confirmed_and_resumed(tmp_path):
    storage = QuickOpsStorage(tmp_path / "hitl.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    manager = BackgroundRunManager(storage, poll_interval=0.001)
    agent = FakePausedAgent()

    run = manager.start(agent, message="创建测试文件", session_id="s1")
    paused_events = [event async for event in manager.subscribe(run["id"])]

    assert storage.get_run(run["id"])["status"] == "paused"
    assert agent.pause_stream_exhausted is True
    assert paused_events[-1]["event_type"] == "run.paused"
    paused_message = storage.list_messages("s1")[-1]
    assert paused_events[-1]["payload"]["message_id"] == paused_message["id"]
    assert paused_message["content"] == "准备执行。"
    assert paused_message["metadata"]["pause_type"] == "approval"
    after_pause = paused_events[-1]["sequence"]

    await manager.resolve_confirmation(run["id"], approved=True)
    resumed_events = [
        event async for event in manager.subscribe(run["id"], after_sequence=after_pause)
    ]

    completed = resumed_events[-1]
    assert storage.get_run(run["id"])["status"] == "completed"
    assert completed["event_type"] == "run.completed"
    assert resumed_events[0]["event_type"] == "approval.resolved"
    assert completed["payload"]["message_id"] == storage.list_messages("s1")[-1]["id"]
    assert storage.list_messages("s1")[-1]["content"] == "准备执行。执行完成。"
    branch = storage.branch_session(
        "s1",
        completed["payload"]["message_id"],
        child_session_id="s1-branch",
    )
    assert branch["branch"]["message_count"] == 1
    messages = storage.list_messages("s1")
    assert len(messages) == 1
    segments = messages[0]["metadata"]["segments"]
    assert [segment["type"] for segment in segments] == [
        "text",
        "approval",
        "tool",
        "text",
    ]
    assert "用户批准了执行命令" in segments[1]["content"]


@pytest.mark.asyncio
async def test_empty_model_turn_after_approval_is_never_silent(tmp_path):
    storage = QuickOpsStorage(tmp_path / "empty-after-approval.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    manager = BackgroundRunManager(storage, poll_interval=0.001)
    agent = FakeEmptyAfterApprovalAgent()

    run = manager.start(agent, message="执行诊断", session_id="s1")
    paused_events = [event async for event in manager.subscribe(run["id"])]
    await manager.resolve_confirmation(run["id"], approved=True)
    _ = [
        event
        async for event in manager.subscribe(
            run["id"], after_sequence=paused_events[-1]["sequence"]
        )
    ]

    message = storage.list_messages("s1")[-1]
    assert "审批后的工具调用已完成" in message["content"]
    assert "发送“继续”" in message["content"]
    assert any(
        segment.get("type") == "tool"
        and segment.get("tool", {}).get("result") == "diagnostic result"
        for segment in message["metadata"]["segments"]
    )


@pytest.mark.asyncio
async def test_only_latest_confirmation_is_actionable(tmp_path):
    storage = QuickOpsStorage(tmp_path / "latest-hitl.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    manager = BackgroundRunManager(storage, poll_interval=0.001)
    agent = FakeMultiPausedAgent()

    run = manager.start(agent, message="只处理最新申请", session_id="s1")
    paused_events = [event async for event in manager.subscribe(run["id"])]
    after_pause = paused_events[-1]["sequence"]
    resolved = await manager.resolve_confirmation(
        run["id"], approved=True, requirement_id="req-latest"
    )
    resumed_events = [
        event async for event in manager.subscribe(run["id"], after_sequence=after_pause)
    ]

    assert resolved["approval_event"]["actions"] == ["执行命令 `touch latest-file`"]
    assert resumed_events[-1]["event_type"] == "run.completed"
    audit = storage.list_audit_events(session_id="s1")[0]
    assert audit["details"]["superseded_requirement_ids"] == ["req-older"]


@pytest.mark.asyncio
async def test_misrouted_readonly_command_does_not_surface_hitl(tmp_path):
    storage = QuickOpsStorage(tmp_path / "readonly-no-hitl.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    manager = BackgroundRunManager(
        storage,
        poll_interval=0.001,
        auto_confirm_requirement=lambda requirement, _session_id: (
            requirement.get("tool_execution", {}).get("tool_args", {}).get("args") == ["ls"]
        ),
    )

    run = manager.start(FakeMisroutedReadonlyAgent(), message="ls", session_id="s1")
    events = [event async for event in manager.subscribe(run["id"])]

    assert storage.get_run(run["id"])["status"] == "completed"
    assert "run.paused" not in [event["event_type"] for event in events]
    assert storage.list_messages("s1")[-1]["content"] == "只读命令已直接执行。"


@pytest.mark.asyncio
async def test_structured_user_feedback_resumes_agno_run(tmp_path):
    storage = QuickOpsStorage(tmp_path / "feedback.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    manager = BackgroundRunManager(storage, poll_interval=0.001)
    agent = FakeFeedbackAgent()

    run = manager.start(agent, message="帮我排查", session_id="s1")
    paused_events = [event async for event in manager.subscribe(run["id"])]
    assert paused_events[-1]["event_type"] == "run.paused"
    schema = paused_events[-1]["payload"]["requirements"][0]["user_feedback_schema"]
    assert schema[0]["options"][0]["label"] == "快速检查"
    assert schema[0]["options"][-1] == {
        "label": "其他",
        "description": "手动输入其他需求",
        "allow_text": True,
    }

    after_pause = paused_events[-1]["sequence"]
    await manager.resolve_user_feedback(
        run["id"],
        requirement_id="feedback-1",
        selections={"选择排查深度": ["快速检查"]},
    )
    resumed = [event async for event in manager.subscribe(run["id"], after_sequence=after_pause)]
    assert resumed[0]["event_type"] == "feedback.resolved"
    assert resumed[-1]["event_type"] == "run.completed"
    transcript = storage.list_messages("s1")
    assert [message["role"] for message in transcript] == ["assistant"]
    assert transcript[0]["content"] == "请选择排查深度。开始快速检查。"
    assert "status" not in transcript[0]["metadata"]
    assert [segment["type"] for segment in transcript[0]["metadata"]["segments"]] == [
        "text",
        "feedback",
        "text",
    ]
    assert transcript[0]["metadata"]["segments"][1]["content"] == "用户选择了：快速检查"
    assert storage.get_run(run["id"])["output_text"] == "请选择排查深度。开始快速检查。"


@pytest.mark.asyncio
async def test_provider_failure_preserves_partial_chain_as_durable_message(tmp_path):
    storage = QuickOpsStorage(tmp_path / "failed-run.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    manager = BackgroundRunManager(storage, poll_interval=0.001)

    run = manager.start(FakeBillingFailureAgent(), message="继续部署", session_id="s1")
    events = [event async for event in manager.subscribe(run["id"])]

    assert events[-1]["event_type"] == "run.failed"
    assert "余额不足" in events[-1]["payload"]["content"]
    durable = storage.list_messages("s1")[-1]
    assert durable["metadata"]["status"] == "failed"
    assert "已完成环境检查" in durable["content"]
    assert "切换模型" in durable["content"]


@pytest.mark.asyncio
async def test_running_and_paused_runs_can_be_cancelled(tmp_path):
    storage = QuickOpsStorage(tmp_path / "cancel.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    manager = BackgroundRunManager(storage, poll_interval=0.001)
    slow = FakeSlowAgent()
    running = manager.start(slow, message="slow", session_id="s1")
    await slow.started.wait()

    cancelled = await manager.cancel(running["id"])
    assert cancelled["status"] == "cancelled"
    assert storage.list_run_events(running["id"])[-1]["event_type"] == "run.cancelled"

    paused_agent = FakePausedAgent()
    paused = manager.start(paused_agent, message="pause", session_id="s1")
    _ = [event async for event in manager.subscribe(paused["id"])]
    cancelled_pause = await manager.cancel(paused["id"])
    assert cancelled_pause["status"] == "cancelled"
    assert paused["id"] not in manager._paused


def test_agno_tool_and_pause_events_are_mapped():
    tool = SimpleNamespace(to_dict=lambda: {"tool_name": "system_status", "result": "ok"})
    requirement = SimpleNamespace(to_dict=lambda: {"id": "req-1"})
    assert map_agno_event(SimpleNamespace(event="ToolCallStarted", tool=tool)) == (
        "tool.started",
        {"tool": {"tool_name": "system_status", "result": "ok"}},
    )
    assert map_agno_event(SimpleNamespace(event="RunPaused", requirements=[requirement])) == (
        "run.paused",
        {"requirements": [{"id": "req-1", "needs_user_feedback": False}]},
    )
    assert map_agno_event(SimpleNamespace(event="ModelRequestStarted")) == (
        "model.started",
        {},
    )
    assert map_agno_event(SimpleNamespace(event="ModelRequestCompleted")) == (
        "model.completed",
        {},
    )
    assert map_agno_event(
        SimpleNamespace(
            event="ModelRequestCompleted",
            model="deepseek",
            input_tokens=1000,
            cache_read_tokens=750,
        )
    ) == (
        "model.completed",
        {
            "model": "deepseek",
            "input_tokens": 1000,
            "cache_read_tokens": 750,
            "cache_hit_rate": 0.75,
        },
    )


def test_title_normalization_removes_model_wrappers():
    assert normalize_title('**标题："nginx CPU 异常排查。"**') == "nginx CPU 异常排查"
    assert fallback_title("帮我检查 MiniCPM5 服务是否正常？") == "检查 MiniCPM5 服务是否正常"
