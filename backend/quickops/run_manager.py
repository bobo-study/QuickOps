from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from agno.agent import Agent
from agno.media import File
from agno.run.requirement import RunRequirement

from quickops.storage import QuickOpsStorage
from quickops.title_generator import SessionTitleGenerator

TERMINAL_RUN_STATUSES = {"paused", "completed", "failed", "cancelled"}
LOGGER = logging.getLogger(__name__)


def _continuation_requirements(event: Any, payload: dict[str, Any]) -> list[Any]:
    """Keep stable HITL requirements after Agno's stream generator is finalized.

    Some providers/runtime paths mutate the event-owned requirement objects while unwinding the
    paused stream. Rebuild confirmation requirements from their serialized event form so the
    later HTTP approval still sees ``requires_confirmation=True``.
    """
    raw = list(getattr(event, "requirements", None) or [])
    serialized = list(payload.get("requirements", []) or [])
    normalized: list[Any] = []
    for index, requirement in enumerate(raw):
        snapshot = serialized[index] if index < len(serialized) else None
        if isinstance(requirement, RunRequirement):
            normalized.append(requirement)
            continue
        tool_snapshot = snapshot.get("tool_execution") if isinstance(snapshot, dict) else None
        if isinstance(tool_snapshot, dict) and tool_snapshot.get("requires_confirmation"):
            normalized.append(RunRequirement.from_dict(snapshot))
        elif isinstance(requirement, dict):
            normalized.append(RunRequirement.from_dict(requirement))
        else:
            normalized.append(requirement)
    return normalized


def _tool_payload(event: Any) -> dict[str, Any]:
    tool = getattr(event, "tool", None)
    if tool is None:
        return {}
    if hasattr(tool, "to_dict"):
        value = tool.to_dict()
        # Tool output is useful evidence but can be very large. The complete output remains in
        # Agno/session persistence; the live UI event is deliberately bounded.
        if isinstance(value.get("result"), str):
            value["result"] = value["result"][:100_000]
        return value
    return {"name": str(tool)}


def _command_action(tool: dict[str, Any]) -> str | None:
    name = str(tool.get("tool_name") or tool.get("name") or "")
    if not (
        name.startswith("execute_")
        or name == "run_shell_command"
        or name == "change_directory"
    ):
        return None
    args = tool.get("tool_args") or tool.get("arguments") or {}
    command_args = args.get("args") if isinstance(args, dict) else None
    if command_args:
        return " ".join(str(item) for item in command_args)
    if isinstance(args, dict) and args.get("command"):
        return str(args["command"])
    if isinstance(args, dict) and args.get("path"):
        return f"cd {args['path']}"
    return name


def _requirement_summary(requirement: Any) -> str:
    snapshot = (
        requirement.to_dict()
        if hasattr(requirement, "to_dict")
        else requirement
        if isinstance(requirement, dict)
        else {}
    )
    tool = snapshot.get("tool_execution") or snapshot.get("tool") or {}
    name = str(tool.get("tool_name") or tool.get("name") or "受控工具")
    args = tool.get("tool_args") or tool.get("arguments") or {}
    command_args = args.get("args") if isinstance(args, dict) else None
    if isinstance(command_args, list) and command_args:
        import shlex

        return f"执行命令 `{shlex.join(str(item) for item in command_args)}`"
    if isinstance(args, dict):
        important = next(
            (
                args[key]
                for key in ("path", "query", "command", "table", "uri", "host")
                if args.get(key)
            ),
            None,
        )
        if important is not None:
            return f"调用 {name}（{str(important)[:160]}）"
    return f"调用 {name}"


def _requirement_id(requirement: Any) -> str | None:
    snapshot = (
        requirement.to_dict()
        if hasattr(requirement, "to_dict")
        else requirement
        if isinstance(requirement, dict)
        else {}
    )
    value = snapshot.get("id") or getattr(requirement, "id", None)
    return str(value) if value is not None else None


def map_agno_event(event: Any) -> tuple[str, dict[str, Any]] | None:
    """Translate Agno's native stream into the small stable QuickOps UI event contract."""
    name = str(getattr(event, "event", ""))
    if name == "RunStarted":
        return "run.started", {}
    if name == "ModelRequestStarted":
        return "model.started", {}
    if name == "ReasoningStarted":
        return "reasoning.started", {}
    if name in {"ReasoningStep", "ReasoningContentDelta"}:
        delta = getattr(event, "reasoning_content", None) or getattr(event, "content", None)
        return "reasoning.delta", {"delta": str(delta or "")}
    if name == "ModelRequestCompleted":
        return "model.completed", {}
    if name == "ReasoningCompleted":
        return "reasoning.completed", {}
    if name == "ToolCallStarted":
        return "tool.started", {"tool": _tool_payload(event)}
    if name in {"ToolCallCompleted", "ToolCallError"}:
        payload = {"tool": _tool_payload(event)}
        error = getattr(event, "error", None)
        if error:
            payload["error"] = str(error)
        return "tool.completed", payload
    if name in {"RunContent", "RunIntermediateContent"}:
        content = getattr(event, "content", None)
        if content is not None:
            return "content.delta", {"delta": str(content)}
    if name == "RunPaused":
        requirements = []
        for requirement in getattr(event, "requirements", None) or []:
            requirements.append(
                requirement.to_dict()
                if hasattr(requirement, "to_dict")
                else {"id": str(requirement)}
            )
        return "run.paused", {"requirements": requirements}
    if name == "RunCompleted":
        return "run.completed", {"content": str(getattr(event, "content", None) or "")}
    if name == "RunCancelled":
        detail = getattr(event, "content", None) or getattr(event, "reason", None)
        return "run.cancelled", {"reason": str(detail or "小维运行已取消")}
    if name == "RunError":
        detail = getattr(event, "content", None) or getattr(event, "reason", None)
        return "run.failed", {"error": str(detail or "小维运行失败")}
    return None


def _message_segments(events: list[dict[str, Any]], fallback_text: str) -> list[dict[str, Any]]:
    """Rebuild the visible assistant timeline from durable stream events."""
    segments: list[dict[str, Any]] = []
    for event in events:
        event_type = event.get("event_type")
        payload = event.get("payload") or {}
        if event_type == "content.delta":
            delta = str(payload.get("delta") or "")
            if not delta:
                continue
            if segments and segments[-1].get("type") == "text":
                segments[-1]["content"] += delta
            else:
                segments.append({"type": "text", "content": delta})
        elif event_type == "tool.started":
            tool = dict(payload.get("tool") or {})
            segments.append({"type": "tool", "status": "running", "tool": tool})
        elif event_type == "tool.completed":
            tool = dict(payload.get("tool") or {})
            tool_id = tool.get("tool_call_id") or tool.get("id")
            target = next(
                (
                    segment
                    for segment in reversed(segments)
                    if segment.get("type") == "tool"
                    and (
                        (tool_id and (segment.get("tool") or {}).get("tool_call_id") == tool_id)
                        or (not tool_id and segment.get("status") == "running")
                    )
                ),
                None,
            )
            if target is None:
                segments.append({"type": "tool", "status": "completed", "tool": tool})
            else:
                target["status"] = "completed"
                target["tool"] = {**(target.get("tool") or {}), **tool}
        elif event_type == "approval.resolved":
            segments.append(
                {
                    "type": "approval",
                    "decision": payload.get("decision"),
                    "content": payload.get("content") or "审批操作已处理",
                }
            )
    # Agno may emit a paused requirement before it emits the eventual completed tool event.
    # Keep the operator decision visually attached after the approved tool block.
    index = 0
    while index < len(segments) - 1:
        if (
            segments[index].get("type") == "approval"
            and segments[index + 1].get("type") == "tool"
        ):
            approval = segments.pop(index)
            while index < len(segments) and segments[index].get("type") == "tool":
                index += 1
            segments.insert(index, approval)
        index += 1
    streamed_text = "".join(
        str(segment.get("content") or "")
        for segment in segments
        if segment.get("type") == "text"
    )
    if fallback_text and not streamed_text:
        segments.append({"type": "text", "content": fallback_text})
    elif fallback_text.startswith(streamed_text) and len(fallback_text) > len(streamed_text):
        # Some OpenAI-compatible providers stop emitting RunContent deltas before the response
        # ends while still returning the complete body in RunCompleted. Preserve the real tool
        # timeline and attach only the terminal suffix instead of hiding it from the transcript.
        suffix = fallback_text[len(streamed_text) :]
        if segments and segments[-1].get("type") == "text":
            segments[-1]["content"] += suffix
        else:
            segments.append({"type": "text", "content": suffix})
    return segments


def _complete_output(streamed_text: str, terminal_text: str) -> str:
    """Prefer a provider's complete terminal body when streamed deltas are its prefix."""
    if terminal_text and (not streamed_text or terminal_text.startswith(streamed_text)):
        return terminal_text
    return streamed_text


class BackgroundRunManager:
    """Owns detached Agent tasks while durable storage provides replay and subscriptions."""

    def __init__(
        self,
        storage: QuickOpsStorage,
        *,
        title_generator: SessionTitleGenerator | None = None,
        poll_interval: float = 0.1,
        auto_confirm_requirement: Callable[[dict[str, Any], str], bool] | None = None,
    ):
        self.storage = storage
        self.title_generator = title_generator
        self.poll_interval = poll_interval
        self.auto_confirm_requirement = auto_confirm_requirement
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._title_tasks: set[asyncio.Task[None]] = set()
        self._summary_tasks: dict[str, asyncio.Task[None]] = {}
        self._paused: dict[str, tuple[Agent, list[Any], str, str]] = {}

    def _auto_confirmable_requirements(
        self, requirements: list[Any], payload: dict[str, Any], session_id: str
    ) -> bool:
        if self.auto_confirm_requirement is None or not requirements:
            return False
        snapshots = list(payload.get("requirements") or [])
        if len(snapshots) != len(requirements):
            return False
        return all(
            self.auto_confirm_requirement(snapshot, session_id) for snapshot in snapshots
        )

    @staticmethod
    def _confirm_requirements(requirements: list[Any]) -> None:
        for requirement in requirements:
            if hasattr(requirement, "confirm"):
                requirement.confirm()
            elif hasattr(requirement, "confirmed"):
                requirement.confirmed = True

    def start(
        self,
        agent: Agent,
        *,
        message: str,
        session_id: str,
        user_id: str = "operator",
        run_id: str | None = None,
        title_generator: SessionTitleGenerator | None = None,
        files: list[File] | None = None,
        on_completed: Callable[[str, str], Awaitable[None] | None] | None = None,
    ) -> dict[str, Any]:
        """Persist and detach a run. The task is not coupled to an HTTP connection."""
        run_id = run_id or f"quickops-run-{uuid.uuid4()}"
        run = self.storage.create_run(
            run_id, session_id=session_id, user_id=user_id, input_text=message
        )
        task = asyncio.create_task(
            self._execute(
                agent,
                run_id=run_id,
                message=message,
                session_id=session_id,
                user_id=user_id,
                files=files,
                on_completed=on_completed,
            ),
            name=f"quickops:{run_id}",
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(run_id, None))
        generator = title_generator or self.title_generator
        if generator is not None:
            title_task = asyncio.create_task(
                self._generate_title_safely(session_id, message, generator),
                name=f"quickops-title:{session_id}",
            )
            self._title_tasks.add(title_task)
            title_task.add_done_callback(self._title_tasks.discard)
        return run

    async def cancel(self, run_id: str) -> dict[str, Any]:
        """Cancel a detached running or paused run and make the transition durable."""
        run = self.storage.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run["status"] not in {"queued", "running", "paused"}:
            raise ValueError("Run is not active")

        # Signal Agno's own cancellation manager first so provider/tool loops observe the stop,
        # then cancel our detached asyncio owner as the local hard-stop fallback.
        with contextlib.suppress(Exception):
            await Agent.acancel_run(run_id)
        self._paused.pop(run_id, None)
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # The task cancellation handler normally owns persistence. Cover queued/orphaned tasks
        # and cancellation races without producing a duplicate terminal event.
        current = self.storage.get_run(run_id)
        if current is not None and current["status"] in {"queued", "running", "paused"}:
            current = self.storage.update_run(
                run_id, status="cancelled", output_text=current.get("output_text", "")
            )
            self.storage.append_run_event(
                run_id,
                event_type="run.cancelled",
                payload={"reason": "Operator stopped the response"},
            )
        return self.storage.get_run(run_id) or current or run

    async def _generate_title_safely(
        self,
        session_id: str,
        first_user_message: str,
        generator: SessionTitleGenerator,
    ) -> None:
        try:
            await self.maybe_generate_title(
                session_id, first_user_message, title_generator=generator
            )
        except Exception:
            # Naming is useful metadata but must never fail or delay the diagnostic run.
            return

    def _schedule_session_summary(self, agent: Agent, session_id: str, user_id: str) -> None:
        manager = getattr(agent, "session_summary_manager", None)
        if manager is None:
            return

        async def update_summary() -> None:
            try:
                session = await agent.aget_session(session_id=session_id, user_id=user_id)
                if session is None:
                    return
                await manager.acreate_session_summary(session=session)
                await agent.asave_session(session)
            except Exception:
                # Summary maintenance must never change an already completed user-facing run.
                LOGGER.exception("Agno session summary update failed for %s", session_id)

        task = asyncio.create_task(
            update_summary(), name=f"quickops-summary:{session_id}"
        )
        self._summary_tasks[session_id] = task
        task.add_done_callback(
            lambda finished: self._summary_tasks.pop(session_id, None)
            if self._summary_tasks.get(session_id) is finished
            else None
        )

    async def _wait_for_session_summary(self, session_id: str) -> None:
        """Ensure the previous turn's Agno compression is ready for the next turn."""
        task = self._summary_tasks.get(session_id)
        if task is not None:
            await asyncio.shield(task)

    async def _execute(
        self,
        agent: Agent,
        *,
        run_id: str,
        message: str,
        session_id: str,
        user_id: str,
        files: list[File] | None,
        on_completed: Callable[[str, str], Awaitable[None] | None] | None,
    ) -> None:
        await self._wait_for_session_summary(session_id)
        output_parts: list[str] = []
        terminal_output = ""
        tools: list[dict[str, Any]] = []
        paused_run = False
        auto_continue_requirements: list[Any] | None = None
        self.storage.update_run(run_id, status="running")
        self.storage.append_run_event(run_id, event_type="run.started")
        try:
            stream_or_awaitable = agent.arun(
                message,
                stream=True,
                stream_events=True,
                session_id=session_id,
                user_id=user_id,
                run_id=run_id,
                files=files,
            )
            stream = (
                await stream_or_awaitable
                if inspect.isawaitable(stream_or_awaitable)
                else stream_or_awaitable
            )
            async for agno_event in stream:
                mapped = map_agno_event(agno_event)
                if mapped is None:
                    continue
                event_type, payload = mapped
                # We publish our durable start before the provider request begins.
                if event_type == "run.started":
                    continue
                if event_type == "content.delta":
                    output_parts.append(payload["delta"])
                elif event_type == "tool.completed" and payload.get("tool"):
                    tools.append(payload["tool"])
                    action = _command_action(payload["tool"])
                    if action:
                        self.storage.append_audit_event(
                            session_id=session_id,
                            actor="quickops-harness",
                            event_type="ai.command.executed",
                            action=action,
                            target=session_id,
                            outcome="success" if not payload.get("error") else "failed",
                            details={"run_id": run_id, "tool": payload["tool"]},
                        )
                elif event_type == "run.failed":
                    raise RuntimeError(payload["error"])
                elif event_type == "run.cancelled":
                    self.storage.update_run(
                        run_id, status="cancelled", output_text="".join(output_parts)
                    )
                    self.storage.append_run_event(
                        run_id, event_type=event_type, payload=payload
                    )
                    return
                elif event_type == "run.paused":
                    requirements = _continuation_requirements(agno_event, payload)
                    if self._auto_confirmable_requirements(
                        requirements, payload, session_id
                    ):
                        # Agno confirmations are tool-scoped. If the model mistakenly routes a
                        # read-only argv through the protected mutation tool, reclassify it at the
                        # server boundary and continue without surfacing a false HITL request.
                        self._confirm_requirements(requirements)
                        auto_continue_requirements = requirements
                        continue
                    self._paused[run_id] = (agent, requirements, session_id, user_id)
                    self.storage.update_run(
                        run_id, status="paused", output_text="".join(output_parts)
                    )
                    self.storage.append_run_event(run_id, event_type=event_type, payload=payload)
                    for requirement in payload.get("requirements", []):
                        tool = requirement.get("tool_execution", {})
                        action = _command_action(tool)
                        if action:
                            self.storage.append_audit_event(
                                session_id=session_id,
                                actor="quickops-harness",
                                event_type="ai.command.approval_requested",
                                action=action,
                                target=session_id,
                                outcome="pending",
                                details={
                                    "run_id": run_id,
                                    "requirement_id": requirement.get("id"),
                                },
                            )
                    # Do not close Agno's async generator early: doing so cancels the provider
                    # run in Agno persistence and makes acontinue_run reject the approval.
                    paused_run = True
                    continue
                elif event_type == "run.completed":
                    # Never append the terminal body to its streamed prefix. Reconcile both after
                    # the stream finishes because some providers emit only a partial delta stream.
                    terminal_output = str(payload.get("content") or "")
                    continue
                self.storage.append_run_event(run_id, event_type=event_type, payload=payload)

            if auto_continue_requirements is not None:
                await self._continue(
                    agent,
                    run_id=run_id,
                    requirements=auto_continue_requirements,
                    session_id=session_id,
                    user_id=user_id,
                    existing_output="".join(output_parts),
                )
                return
            if paused_run:
                return
            output = _complete_output("".join(output_parts), terminal_output)
            segments = _message_segments(self.storage.list_run_events(run_id), output)
            assistant_message = self.storage.append_message(
                session_id,
                role="assistant",
                content=output or "小维未返回文本内容。",
                metadata={
                    "kind": "chat",
                    "run_id": run_id,
                    "tools": tools,
                    "segments": segments,
                },
            )
            self.storage.update_run(run_id, status="completed", output_text=output)
            self.storage.append_run_event(
                run_id,
                event_type="run.completed",
                payload={
                    "content": output,
                    "tools": tools,
                    "segments": segments,
                    "message_id": assistant_message["id"],
                    "created_at": assistant_message["created_at"].isoformat(),
                },
            )
            self._schedule_session_summary(agent, session_id, user_id)
            if on_completed is not None:
                result = on_completed(run_id, output)
                if asyncio.iscoroutine(result):
                    await result
        except asyncio.CancelledError:
            self.storage.update_run(run_id, status="cancelled", output_text="".join(output_parts))
            self.storage.append_run_event(
                run_id,
                event_type="run.cancelled",
                payload={"reason": "Operator stopped the response"},
            )
            raise
        except Exception as error:  # the failure is durable and delivered to subscribers
            self.storage.update_run(
                run_id,
                status="failed",
                output_text="".join(output_parts),
                error=str(error),
            )
            self.storage.append_run_event(
                run_id, event_type="run.failed", payload={"error": str(error)}
            )

    async def maybe_generate_title(
        self,
        session_id: str,
        first_user_message: str,
        *,
        title_generator: SessionTitleGenerator | None = None,
    ) -> str | None:
        generator = title_generator or self.title_generator
        if generator is None:
            return None
        session = self.storage.get_session(session_id)
        if session is None or session["title"] != "新会话":
            return None
        if self.storage.count_messages(session_id, role="user") != 1:
            return None
        title = await generator.generate(first_user_message)
        self.storage.update_session(session_id, title=title)
        return title

    async def resolve_confirmation(
        self,
        run_id: str,
        *,
        approved: bool,
        note: str | None = None,
        requirement_id: str | None = None,
    ) -> dict[str, Any]:
        """Resolve only the latest visible requirement and supersede older pending calls."""
        paused = self._paused.pop(run_id, None)
        run = self.storage.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run["status"] != "paused" or paused is None:
            raise ValueError("Run is not paused in this server process")
        agent, requirements, session_id, user_id = paused
        pending = [
            requirement
            for requirement in requirements
            if getattr(requirement, "needs_confirmation", False)
        ]
        if not pending:
            self._paused[run_id] = paused
            raise ValueError("Run has no pending confirmation requirement")
        target = (
            next(
                (
                    requirement
                    for requirement in reversed(pending)
                    if _requirement_id(requirement) == requirement_id
                ),
                None,
            )
            if requirement_id
            else pending[-1]
        )
        if target is None:
            self._paused[run_id] = paused
            raise ValueError("Pending confirmation requirement does not exist")
        superseded = [requirement for requirement in pending if requirement is not target]
        for requirement in superseded:
            requirement.reject("已被最新权限申请取代")
        if approved:
            target.confirm()
        else:
            target.reject(note)
        actions = [_requirement_summary(target)]

        self.storage.append_audit_event(
            session_id=session_id,
            actor="operator",
            event_type="ai.command.approved" if approved else "ai.command.rejected",
            action="resolve latest Agno confirmation requirement",
            target=session_id,
            outcome="approved" if approved else "rejected",
            details={
                "run_id": run_id,
                "note": note,
                "requirement_id": _requirement_id(target),
                "superseded_requirement_ids": [
                    _requirement_id(requirement) for requirement in superseded
                ],
            },
        )
        decision_text = "批准" if approved else "拒绝"
        action_text = "、".join(actions) or "受控工具"
        approval_event = {
            "kind": "approval_event",
            "run_id": run_id,
            "decision": "approved" if approved else "rejected",
            "actions": actions,
            "content": f"用户{decision_text}了{action_text}",
        }
        stored_approval_event = self.storage.append_run_event(
            run_id,
            event_type="approval.resolved",
            payload=approval_event,
        )

        self.storage.update_run(run_id, status="running", output_text=run["output_text"])
        task = asyncio.create_task(
            self._continue(
                agent,
                run_id=run_id,
                requirements=requirements,
                session_id=session_id,
                user_id=user_id,
                existing_output=run["output_text"],
            ),
            name=f"quickops-continue:{run_id}",
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(run_id, None))
        result = self.storage.get_run(run_id) or run
        result["approval_event"] = {
            **approval_event,
            "sequence": stored_approval_event["sequence"],
            "created_at": stored_approval_event["created_at"],
        }
        return result

    async def _continue(
        self,
        agent: Agent,
        *,
        run_id: str,
        requirements: list[Any],
        session_id: str,
        user_id: str,
        existing_output: str,
    ) -> None:
        output_parts = [existing_output] if existing_output else []
        terminal_output = ""
        tools: list[dict[str, Any]] = []
        paused_run = False
        auto_continue_requirements: list[Any] | None = None
        try:
            stream_or_awaitable = agent.acontinue_run(
                run_id=run_id,
                requirements=requirements,
                stream=True,
                stream_events=True,
                session_id=session_id,
                user_id=user_id,
            )
            stream = (
                await stream_or_awaitable
                if inspect.isawaitable(stream_or_awaitable)
                else stream_or_awaitable
            )
            async for agno_event in stream:
                mapped = map_agno_event(agno_event)
                if mapped is None:
                    continue
                event_type, payload = mapped
                if event_type == "run.started":
                    continue
                if event_type == "content.delta":
                    output_parts.append(payload["delta"])
                elif event_type == "tool.completed" and payload.get("tool"):
                    tools.append(payload["tool"])
                    action = _command_action(payload["tool"])
                    if action:
                        self.storage.append_audit_event(
                            session_id=session_id,
                            actor="quickops-harness",
                            event_type="ai.command.executed",
                            action=action,
                            target=session_id,
                            outcome="success" if not payload.get("error") else "failed",
                            details={"run_id": run_id, "tool": payload["tool"]},
                        )
                elif event_type == "run.failed":
                    raise RuntimeError(payload["error"])
                elif event_type == "run.cancelled":
                    self.storage.update_run(
                        run_id, status="cancelled", output_text="".join(output_parts)
                    )
                    self.storage.append_run_event(
                        run_id, event_type=event_type, payload=payload
                    )
                    return
                elif event_type == "run.paused":
                    new_requirements = _continuation_requirements(agno_event, payload)
                    if self._auto_confirmable_requirements(
                        new_requirements, payload, session_id
                    ):
                        self._confirm_requirements(new_requirements)
                        auto_continue_requirements = new_requirements
                        continue
                    self._paused[run_id] = (agent, new_requirements, session_id, user_id)
                    self.storage.update_run(
                        run_id, status="paused", output_text="".join(output_parts)
                    )
                    self.storage.append_run_event(run_id, event_type=event_type, payload=payload)
                    paused_run = True
                    continue
                elif event_type == "run.completed":
                    terminal_output = str(payload.get("content") or "")
                    continue
                self.storage.append_run_event(run_id, event_type=event_type, payload=payload)

            if auto_continue_requirements is not None:
                await self._continue(
                    agent,
                    run_id=run_id,
                    requirements=auto_continue_requirements,
                    session_id=session_id,
                    user_id=user_id,
                    existing_output="".join(output_parts),
                )
                return
            if paused_run:
                return
            output = _complete_output("".join(output_parts), terminal_output)
            segments = _message_segments(self.storage.list_run_events(run_id), output)
            assistant_message = self.storage.append_message(
                session_id,
                role="assistant",
                content=output or "小维未返回文本内容。",
                metadata={
                    "kind": "chat",
                    "run_id": run_id,
                    "tools": tools,
                    "segments": segments,
                },
            )
            self.storage.update_run(run_id, status="completed", output_text=output)
            self.storage.append_run_event(
                run_id,
                event_type="run.completed",
                payload={
                    "content": output,
                    "tools": tools,
                    "segments": segments,
                    "message_id": assistant_message["id"],
                    "created_at": assistant_message["created_at"].isoformat(),
                },
            )
            self._schedule_session_summary(agent, session_id, user_id)
        except asyncio.CancelledError:
            self.storage.update_run(run_id, status="cancelled", output_text="".join(output_parts))
            self.storage.append_run_event(
                run_id,
                event_type="run.cancelled",
                payload={"reason": "Operator stopped the response"},
            )
            raise
        except Exception as error:
            self.storage.update_run(
                run_id,
                status="failed",
                output_text="".join(output_parts),
                error=str(error),
            )
            self.storage.append_run_event(
                run_id, event_type="run.failed", payload={"error": str(error)}
            )

    async def subscribe(
        self, run_id: str, *, after_sequence: int = 0
    ) -> AsyncIterator[dict[str, Any]]:
        """Replay stored events, then poll until the run reaches a terminal state."""
        sequence = max(after_sequence, 0)
        while True:
            run = self.storage.get_run(run_id)
            if run is None:
                raise KeyError(run_id)
            events = self.storage.list_run_events(run_id, after_sequence=sequence)
            for event in events:
                sequence = event["sequence"]
                yield event
            if run["status"] in TERMINAL_RUN_STATUSES and not events:
                return
            await asyncio.sleep(self.poll_interval)
