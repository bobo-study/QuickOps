from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from quickops.run_manager import BackgroundRunManager, map_agno_event
from quickops.storage import QuickOpsStorage
from quickops.title_generator import normalize_title


class FakeTitleGenerator:
    async def generate(self, first_user_message: str) -> str:
        assert first_user_message == "生产 nginx 为什么很慢？"
        return "nginx 延迟排查"


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


class FakeSummaryManager:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def acreate_session_summary(self, *, session):
        self.started.set()
        await self.release.wait()
        session.summary = "updated"


class FakeAgentWithSlowSummary(FakeAgent):
    def __init__(self):
        self.session_summary_manager = FakeSummaryManager()
        self.session = SimpleNamespace(summary=None)
        self.saved = False

    async def aget_session(self, **_kwargs):
        return self.session

    async def asave_session(self, _session):
        self.saved = True


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

    async def arun(self, _message, **kwargs):
        self.files = kwargs.get("files")
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
async def test_background_run_passes_files_to_agno_agent(tmp_path):
    from agno.media import File

    storage = QuickOpsStorage(tmp_path / "file-run.db")
    storage.create_session("s1", host_id="local", user_id="operator")
    manager = BackgroundRunManager(storage, poll_interval=0.001)
    agent = FakeFileAgent()
    attached = File(content=b"hello", filename="notes.txt", mime_type="text/plain")

    run = manager.start(agent, message="阅读附件", session_id="s1", files=[attached])
    _ = [event async for event in manager.subscribe(run["id"])]

    assert agent.files == [attached]


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
    assert "".join(
        segment["content"]
        for segment in message["metadata"]["segments"]
        if segment["type"] == "text"
    ) == expected
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
    after_pause = paused_events[-1]["sequence"]

    await manager.resolve_confirmation(run["id"], approved=True)
    resumed_events = [
        event
        async for event in manager.subscribe(run["id"], after_sequence=after_pause)
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
        "tool",
        "approval",
        "text",
    ]
    assert "用户批准了执行命令" in segments[2]["content"]


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
        event
        async for event in manager.subscribe(run["id"], after_sequence=after_pause)
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
        {"requirements": [{"id": "req-1"}]},
    )
    assert map_agno_event(SimpleNamespace(event="ModelRequestStarted")) == (
        "model.started",
        {},
    )
    assert map_agno_event(SimpleNamespace(event="ModelRequestCompleted")) == (
        "model.completed",
        {},
    )


def test_title_normalization_removes_model_wrappers():
    assert normalize_title('**标题："nginx CPU 异常排查。"**') == "nginx CPU 异常排查"
