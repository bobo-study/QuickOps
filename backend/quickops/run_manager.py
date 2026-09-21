from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from agno.agent import Agent
from agno.media import File, Image
from agno.run.requirement import RunRequirement

from quickops.storage import QuickOpsStorage
from quickops.title_generator import SessionTitleGenerator, fallback_title

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
        name.startswith("execute_") or name == "run_shell_command" or name == "change_directory"
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
        payload = {
            key: getattr(event, key, None)
            for key in (
                "model",
                "model_provider",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "reasoning_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "time_to_first_token",
            )
            if getattr(event, key, None) is not None
        }
        input_tokens = payload.get("input_tokens")
        cache_read_tokens = payload.get("cache_read_tokens")
        if (
            isinstance(input_tokens, int)
            and input_tokens > 0
            and isinstance(cache_read_tokens, int)
        ):
            payload["cache_hit_rate"] = round(cache_read_tokens / input_tokens, 4)
        return "model.completed", payload
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
            snapshot = (
                requirement.to_dict()
                if hasattr(requirement, "to_dict")
                else {"id": str(requirement)}
            )
            if isinstance(snapshot, dict):
                snapshot["needs_user_feedback"] = bool(
                    getattr(requirement, "needs_user_feedback", False)
                )
                schema = snapshot.get("user_feedback_schema")
                if isinstance(schema, list):
                    snapshot["user_feedback_schema"] = _normalize_feedback_schema(schema)
            requirements.append(snapshot)
        return "run.paused", {"requirements": requirements}
    if name == "RunCompleted":
        return "run.completed", {"content": str(getattr(event, "content", None) or "")}
    if name == "RunCancelled":
        detail = getattr(event, "content", None) or getattr(event, "reason", None)
        return "run.cancelled", {"reason": str(detail or "小维运行已取消")}
    if name == "RunError":
        detail = getattr(event, "content", None) or getattr(event, "reason", None)
        payload = {
            "error": str(detail or "小维运行失败"),
            "error_type": getattr(event, "error_type", None),
            "error_id": getattr(event, "error_id", None),
            "additional_data": getattr(event, "additional_data", None),
        }
        return "run.failed", {key: value for key, value in payload.items() if value is not None}
    return None


def _normalize_feedback_schema(schema: list[Any]) -> list[dict[str, Any]]:
    """Reserve the final quick-choice slot for a free-form Other answer."""
    normalized: list[dict[str, Any]] = []
    for raw_question in schema:
        question = dict(raw_question) if isinstance(raw_question, dict) else {}
        options = [dict(item) for item in question.get("options", []) if isinstance(item, dict)]
        fixed: list[dict[str, Any]] = []
        custom: dict[str, Any] | None = None
        for option in options:
            label = str(option.get("label") or "")
            if option.get("allow_text") is True or any(
                token in label.casefold() for token in ("其他", "其它", "自定义", "other", "custom")
            ):
                custom = option
            elif len(fixed) < 3:
                fixed.append(option)
        custom = {
            **(custom or {}),
            "label": "其他",
            "description": (custom or {}).get("description") or "手动输入其他需求",
            "allow_text": True,
        }
        question["options"] = [*fixed, custom]
        normalized.append(question)
    return normalized


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
        elif event_type == "feedback.resolved":
            segments.append(
                {
                    "type": "feedback",
                    "content": payload.get("content") or "用户已提交选择",
                }
            )
    # Agno resumes a protected call in the causal order approval -> tool start -> tool result.
    # Preserve that order verbatim: moving decisions behind tools makes execution appear to
    # precede authorization and can reverse multiple approvals during live reconciliation.
    streamed_text = "".join(
        str(segment.get("content") or "") for segment in segments if segment.get("type") == "text"
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


def _friendly_run_error(error: Exception) -> str:
    """Turn provider failures into actionable operator-facing text without hiding evidence."""
    raw = str(error).strip() or type(error).__name__
    lowered = raw.casefold()
    if any(
        token in lowered
        for token in ("insufficient_balance", "insufficient balance", "余额不足", "欠费")
    ):
        return "模型服务余额不足，本次运行已停止。充值或切换模型后可重新发送任务继续。"
    if any(token in lowered for token in ("rate limit", "too many requests", "429")):
        return "模型服务请求频率受限，本次运行已停止。请稍后重试或切换模型。"
    if any(
        token in lowered for token in ("unauthorized", "invalid api key", "authentication", "401")
    ):
        return "模型服务鉴权失败，本次运行已停止。请检查该模型的服务端凭据或切换模型。"
    if "unknown model error" in lowered:
        return (
            "模型服务端返回了空错误体（Unknown model error）。"
            "通常是上游网关限流、账号额度/并发限制或模型节点短暂异常；"
            "本次已停止且保留现有过程。请稍后重试，若持续出现请切换模型并查看服务日志。"
        )
    return f"小维运行失败：{raw[:1200]}"


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
        self._run_message_ids: dict[str, str] = {}

    def _auto_confirmable_requirements(
        self, requirements: list[Any], payload: dict[str, Any], session_id: str
    ) -> bool:
        if self.auto_confirm_requirement is None or not requirements:
            return False
        snapshots = list(payload.get("requirements") or [])
        if len(snapshots) != len(requirements):
            return False
        return all(self.auto_confirm_requirement(snapshot, session_id) for snapshot in snapshots)

    def _persist_failed_assistant_message(
        self,
        *,
        run_id: str,
        session_id: str,
        output: str,
        tools: list[dict[str, Any]],
        error: Exception,
        after_sequence: int = 0,
        cumulative_output: str | None = None,
    ) -> None:
        friendly = _friendly_run_error(error)
        partial = output.rstrip()
        content = f"{partial}\n\n> ⚠️ {friendly}" if partial else f"> ⚠️ {friendly}"
        segments = _message_segments(
            self.storage.list_run_events(run_id, after_sequence=after_sequence), partial
        )
        segments.append({"type": "text", "content": f"\n\n> ⚠️ {friendly}"})
        metadata = {
                "kind": "chat",
                "status": "failed",
                "run_id": run_id,
                "tools": tools,
                "segments": segments,
        }
        active_message_id = self._run_message_ids.pop(run_id, None)
        if not active_message_id:
            active_message_id = next(
                (
                    str(message["id"])
                    for message in reversed(self.storage.list_messages(session_id))
                    if (message.get("metadata") or {}).get("run_id") == run_id
                    and message.get("role") == "assistant"
                ),
                None,
            )
        if active_message_id:
            assistant_message = self.storage.update_message(
                active_message_id, content=content, metadata=metadata
            )
        else:
            assistant_message = self.storage.append_message(
                session_id,
                role="assistant",
                content=content,
                metadata=metadata,
            )
        self.storage.update_run(
            run_id,
            status="failed",
            output_text=cumulative_output if cumulative_output is not None else partial,
            error=str(error),
        )
        self.storage.append_run_event(
            run_id,
            event_type="run.failed",
            payload={
                "error": friendly,
                "content": content,
                "segments": segments,
                "message_id": assistant_message["id"],
                "created_at": assistant_message["created_at"].isoformat(),
            },
        )

    def _persist_pause_boundary(
        self,
        *,
        run_id: str,
        session_id: str,
        output: str,
        tools: list[dict[str, Any]],
        payload: dict[str, Any],
        after_sequence: int = 0,
    ) -> dict[str, Any]:
        """Checkpoint the one assistant bubble that owns every pause and continuation."""
        segments = _message_segments(
            self.storage.list_run_events(run_id, after_sequence=after_sequence), output
        )
        content = output or "小维正在等待你的选择。"
        is_feedback = any(
            bool(requirement.get("needs_user_feedback"))
            for requirement in payload.get("requirements", [])
            if isinstance(requirement, dict)
        )
        metadata = {
                "kind": "chat",
                "status": "paused",
                "pause_type": "user_feedback" if is_feedback else "approval",
                "run_id": run_id,
                "tools": tools,
                "segments": segments,
        }
        message_id = self._run_message_ids.get(run_id)
        if message_id:
            assistant_message = self.storage.update_message(
                message_id, content=content, metadata=metadata
            )
        else:
            assistant_message = self.storage.append_message(
                session_id, role="assistant", content=content, metadata=metadata
            )
            self._run_message_ids[run_id] = assistant_message["id"]
        payload.update(
            {
                "content": output,
                "tools": tools,
                "segments": segments,
                "message_id": assistant_message["id"],
                "created_at": assistant_message["created_at"].isoformat(),
            }
        )
        return assistant_message

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
        images: list[Image] | None = None,
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
                images=images,
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
        self._run_message_ids.pop(run_id, None)
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
            LOGGER.exception(
                "Session title generation failed for %s; using local fallback", session_id
            )
            session = self.storage.get_session(session_id)
            if session and session["title"] == "新会话":
                self.storage.update_session(
                    session_id, title=fallback_title(first_user_message)
                )

    def _schedule_session_summary(
        self,
        agent: Agent,
        session_id: str,
        user_id: str,
        observed_input_tokens: int = 0,
    ) -> None:
        manager = getattr(agent, "session_summary_manager", None)
        if manager is None:
            return

        async def update_summary() -> None:
            try:
                session = await agent.aget_session(session_id=session_id, user_id=user_id)
                if session is None:
                    return
                runs = list(getattr(session, "runs", None) or [])
                if len(runs) <= 1:
                    return
                threshold = int(getattr(agent, "quickops_context_compaction_tokens", 0) or 0)
                token_count = observed_input_tokens
                if token_count <= 0:
                    messages = session.get_messages(agent_id=getattr(agent, "id", None))
                    model = getattr(agent, "model", None)
                    if model is not None and messages:
                        token_count = int(await model.acount_tokens(messages))
                if threshold > 0 and token_count < threshold:
                    return
                # A checkpoint is cumulative across epochs. Agno's summary manager normally
                # summarizes the runs currently present in the session; once earlier runs have
                # been compacted, explicitly feed its own previous checkpoint into the next
                # maintenance prompt so long-lived facts survive every epoch boundary.
                metadata = dict(getattr(session, "metadata", None) or {})
                previous_checkpoint = str(metadata.get("quickops_context_checkpoint") or "").strip()
                base_summary_prompt = str(
                    getattr(agent, "quickops_summary_base_prompt", None)
                    or getattr(manager, "session_summary_prompt", None)
                    or ""
                )
                if previous_checkpoint:
                    manager.session_summary_prompt = (
                        base_summary_prompt
                        + "\n<previous_context_checkpoint>\n"
                        + previous_checkpoint
                        + "\n</previous_context_checkpoint>\n"
                        + "请将旧检查点与本纪元的新事实合并；新证据优先，已被纠正的旧结论必须删除。"
                    )
                try:
                    await manager.acreate_session_summary(session=session)
                finally:
                    manager.session_summary_prompt = base_summary_prompt
                keep_configured = int(getattr(agent, "quickops_context_checkpoint_runs", 2) or 2)
                keep = min(keep_configured, max(1, len(runs) - 1))
                removed = len(runs) - keep
                if removed <= 0:
                    return
                summary_value = getattr(getattr(session, "summary", None), "summary", None)
                if summary_value is None and isinstance(getattr(session, "summary", None), str):
                    summary_value = session.summary
                epoch = int(metadata.get("quickops_context_epoch", 0) or 0) + 1
                metadata.update(
                    {
                        "quickops_context_epoch": epoch,
                        "quickops_context_compacted_at": datetime.now(UTC).isoformat(),
                        "quickops_context_compacted_runs": removed,
                        "quickops_context_checkpoint": str(summary_value or ""),
                        "quickops_context_checkpoint_id": f"epoch-{epoch}",
                    }
                )
                metadata.pop("quickops_context_checkpoint_seen", None)
                # The next epoch must restate the authoritative runtime snapshot because the
                # earlier copy may have been removed with the compacted runs.
                metadata.pop("quickops_runtime_snapshot_digest", None)
                session.metadata = metadata
                session.runs = runs[-keep:]
                await agent.asave_session(session)
            except Exception:
                # Compaction maintenance must never change an already completed visible run.
                LOGGER.exception("Agno context checkpoint update failed for %s", session_id)

        task = asyncio.create_task(update_summary(), name=f"quickops-summary:{session_id}")
        self._summary_tasks[session_id] = task
        task.add_done_callback(
            lambda finished: (
                self._summary_tasks.pop(session_id, None)
                if self._summary_tasks.get(session_id) is finished
                else None
            )
        )

    async def _wait_for_session_summary(self, session_id: str, run_id: str) -> None:
        """Ensure the previous turn's Agno compression is ready for the next turn."""
        task = self._summary_tasks.get(session_id)
        if task is None or task.done():
            return
        self.storage.append_run_event(
            run_id,
            event_type="context.compaction.started",
            payload={"label": "正在压缩会话上下文"},
        )
        try:
            await asyncio.shield(task)
        except Exception as error:
            self.storage.append_run_event(
                run_id,
                event_type="context.compaction.failed",
                payload={"label": "上下文压缩失败，正在保留原上下文继续", "error": str(error)},
            )
            return
        self.storage.append_run_event(
            run_id,
            event_type="context.compaction.completed",
            payload={"label": "上下文压缩完成"},
        )

    @staticmethod
    def _valid_observed_context_tokens(agent: Agent, payload: dict[str, Any]) -> int:
        """Accept prompt-size metrics only when they are plausible for the configured model.

        Some OpenAI-compatible gateways return session-cumulative or otherwise corrupted usage
        counters.  Treating those as one prompt caused needless epoch compaction and long waits.
        """
        value = payload.get("input_tokens")
        if not isinstance(value, int) or value <= 0:
            return 0
        maximum = int(getattr(agent, "quickops_max_context_tokens", 0) or 0)
        if maximum > 0 and value > int(maximum * 1.05):
            LOGGER.warning(
                "Ignoring implausible model input token metric %s above context %s",
                value,
                maximum,
            )
            return 0
        return value

    async def _cache_friendly_model_input(
        self, agent: Agent, message: str, session_id: str, user_id: str
    ) -> str:
        """Append mutable runtime context after the reusable provider-cache prefix.

        Agno owns summary generation and persistence. QuickOps only changes where the current
        snapshot is presented: the native system-message insertion rewrites the request prefix
        on every summary update, while an input checkpoint preserves all prior messages byte for
        byte and mirrors the append-only context strategy used by DeepSeek Harness.
        """
        blocks: list[str] = []
        session = None
        metadata: dict[str, Any] = {}
        metadata_changed = False
        if hasattr(agent, "aget_session"):
            try:
                session = await agent.aget_session(session_id=session_id, user_id=user_id)
                metadata = dict(getattr(session, "metadata", None) or {}) if session else {}
            except Exception:
                LOGGER.exception("Unable to load Agno prompt checkpoint for %s", session_id)
        runtime_context = getattr(agent, "quickops_runtime_context", None)
        if runtime_context:
            digest = hashlib.sha256(str(runtime_context).encode()).hexdigest()
            if metadata.get("quickops_runtime_snapshot_digest") != digest:
                blocks.append(str(runtime_context))
                metadata["quickops_runtime_snapshot_digest"] = digest
                metadata_changed = True
        checkpoint_id = metadata.get("quickops_context_checkpoint_id")
        if checkpoint_id and metadata.get("quickops_context_checkpoint_seen") != checkpoint_id:
            summary = str(metadata.get("quickops_context_checkpoint") or "").strip()
            if summary:
                blocks.append(
                    "<quickops_context_checkpoint>\n"
                    "Agno 在上一上下文纪元达到定点阈值后生成的长期检查点；新证据优先。\n"
                    f"{summary}\n"
                    "</quickops_context_checkpoint>"
                )
            metadata["quickops_context_checkpoint_seen"] = checkpoint_id
            metadata_changed = True
        # A provider failure or a QuickOps-side post-tool exception can terminate the Agno
        # run before Agno admits it to normal completed-run history.  The UI still has the
        # durable partial assistant turn, so bridge that single interrupted boundary into the
        # next request exactly once.  This is a recovery checkpoint, not a second raw-history
        # implementation: ordinary completed epochs remain wholly owned by Agno.
        durable_messages = self.storage.list_messages(session_id)
        current_user_index = next(
            (
                index
                for index in range(len(durable_messages) - 1, -1, -1)
                if durable_messages[index].get("role") == "user"
            ),
            len(durable_messages),
        )
        interrupted_index = next(
            (
                index
                for index in range(current_user_index - 1, -1, -1)
                if durable_messages[index].get("role") == "assistant"
                and (durable_messages[index].get("metadata") or {}).get("status") == "failed"
                and str(durable_messages[index].get("id") or "")
                != metadata.get("quickops_failed_run_checkpoint_seen")
            ),
            None,
        )
        if interrupted_index is not None:
            interrupted = durable_messages[interrupted_index]
            interrupted_metadata = dict(interrupted.get("metadata") or {})
            interrupted_id = str(interrupted.get("id") or "")
            if interrupted_metadata.get("status") == "failed" and interrupted_id:
                previous_user = next(
                    (
                        durable_messages[index]
                        for index in range(interrupted_index - 1, -1, -1)
                        if durable_messages[index].get("role") == "user"
                    ),
                    None,
                )
                partial = str(interrupted.get("content") or "").strip()
                if len(partial) > 6_000:
                    partial = partial[:4_500].rstrip() + "\n…\n" + partial[-1_400:].lstrip()
                previous_text = str((previous_user or {}).get("content") or "").strip()
                intervening_requests = [
                    str(durable_messages[index].get("content") or "").strip()
                    for index in range(interrupted_index + 1, current_user_index)
                    if durable_messages[index].get("role") == "user"
                    and str(durable_messages[index].get("content") or "").strip()
                ]
                intervening_text = "\n".join(intervening_requests)[-2_000:]
                blocks.append(
                    "<quickops_interrupted_run_checkpoint>\n"
                    "上一轮在正常完成前中止，可能未进入 Agno 的 completed-run 历史。"
                    "以下是 QuickOps 持久层保存的恢复检查点；继续原目标，不要改查无关服务。\n"
                    f"previous_user={previous_text[:2_000]}\n"
                    f"intervening_user_requests={intervening_text}\n"
                    f"partial_assistant={partial}\n"
                    "</quickops_interrupted_run_checkpoint>"
                )
                # A cancelled or failed continuation has not consumed this checkpoint. Mark it
                # only after a subsequent run finishes successfully, otherwise a short retry
                # such as “继续” loses the original goal on its next attempt.
                agent.quickops_pending_failed_run_checkpoint_id = interrupted_id
        if session is not None and metadata_changed and hasattr(agent, "asave_session"):
            session.metadata = metadata
            await agent.asave_session(session)
        elif metadata_changed:
            # The first Agno run creates its session lazily. Carry these values until the
            # stream has established that session, then persist them so the second turn does
            # not repeat the runtime snapshot and invalidate an otherwise stable prefix.
            agent.quickops_pending_context_metadata = metadata
        blocks.append(f"<operator_request>\n{message}\n</operator_request>")
        # Dynamic time is deliberately the final prompt block. It cannot invalidate any stable
        # prefix before the current request and avoids Agno's system-message datetime injection.
        blocks.append(
            "<request_time_utc>"
            + datetime.now(UTC).isoformat(timespec="seconds")
            + "</request_time_utc>"
        )
        return "\n\n".join(blocks)

    async def _persist_pending_context_metadata(
        self, agent: Agent, session_id: str, user_id: str
    ) -> None:
        pending = getattr(agent, "quickops_pending_context_metadata", None)
        if not isinstance(pending, dict) or not pending:
            return
        try:
            session = await agent.aget_session(session_id=session_id, user_id=user_id)
            if session is None:
                return
            session.metadata = {**dict(getattr(session, "metadata", None) or {}), **pending}
            await agent.asave_session(session)
            agent.quickops_pending_context_metadata = None
        except Exception:
            LOGGER.exception("Unable to persist Agno prompt checkpoint for %s", session_id)

    async def _mark_recovery_checkpoint_consumed(
        self, agent: Agent, session_id: str, user_id: str
    ) -> None:
        checkpoint_id = str(
            getattr(agent, "quickops_pending_failed_run_checkpoint_id", "") or ""
        ).strip()
        if not checkpoint_id:
            return
        try:
            session = await agent.aget_session(session_id=session_id, user_id=user_id)
            if session is None:
                return
            metadata = dict(getattr(session, "metadata", None) or {})
            metadata["quickops_failed_run_checkpoint_seen"] = checkpoint_id
            session.metadata = metadata
            await agent.asave_session(session)
            agent.quickops_pending_failed_run_checkpoint_id = None
        except Exception:
            LOGGER.exception("Unable to mark recovery checkpoint consumed for %s", session_id)

    async def _execute(
        self,
        agent: Agent,
        *,
        run_id: str,
        message: str,
        session_id: str,
        user_id: str,
        files: list[File] | None,
        images: list[Image] | None,
        on_completed: Callable[[str, str], Awaitable[None] | None] | None,
    ) -> None:
        output_parts: list[str] = []
        terminal_output = ""
        tools: list[dict[str, Any]] = []
        paused_run = False
        auto_continue_requirements: list[Any] | None = None
        observed_input_tokens = 0
        self.storage.update_run(run_id, status="running")
        self.storage.append_run_event(run_id, event_type="run.started")
        try:
            await self._wait_for_session_summary(session_id, run_id)
            model_input = await self._cache_friendly_model_input(
                agent, message, session_id, user_id
            )
            stream_or_awaitable = agent.arun(
                model_input,
                stream=True,
                stream_events=True,
                session_id=session_id,
                user_id=user_id,
                run_id=run_id,
                files=files,
                images=images,
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
                elif event_type == "model.completed":
                    # The provider input count measures the canonical prompt at this model step.
                    # Validate it before using it because some compatible gateways report a
                    # session-cumulative or otherwise corrupted counter here.
                    value = self._valid_observed_context_tokens(agent, payload)
                    if value:
                        observed_input_tokens = max(observed_input_tokens, value)
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
                    detail = payload.get("error") or "小维运行失败"
                    diagnostics = {
                        key: payload[key]
                        for key in ("error_type", "error_id")
                        if payload.get(key) is not None
                    }
                    additional = payload.get("additional_data")
                    if isinstance(additional, dict):
                        for key in ("status", "status_code", "code", "request_id", "model"):
                            if additional.get(key) is not None:
                                diagnostics[key] = additional[key]
                    if diagnostics:
                        detail = f"{detail} | {diagnostics}"
                    raise RuntimeError(detail)
                elif event_type == "run.cancelled":
                    self.storage.update_run(
                        run_id, status="cancelled", output_text="".join(output_parts)
                    )
                    self.storage.append_run_event(run_id, event_type=event_type, payload=payload)
                    return
                elif event_type == "run.paused":
                    requirements = _continuation_requirements(agno_event, payload)
                    if self._auto_confirmable_requirements(requirements, payload, session_id):
                        # Agno confirmations are tool-scoped. If the model mistakenly routes a
                        # read-only argv through the protected mutation tool, reclassify it at the
                        # server boundary and continue without surfacing a false HITL request.
                        self._confirm_requirements(requirements)
                        auto_continue_requirements = requirements
                        continue
                    self._persist_pause_boundary(
                        run_id=run_id,
                        session_id=session_id,
                        output="".join(output_parts),
                        tools=tools,
                        payload=payload,
                    )
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

            await self._persist_pending_context_metadata(agent, session_id, user_id)
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
            await self._mark_recovery_checkpoint_consumed(agent, session_id, user_id)
            self._schedule_session_summary(
                agent, session_id, user_id, observed_input_tokens=observed_input_tokens
            )
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
            self._persist_failed_assistant_message(
                run_id=run_id,
                session_id=session_id,
                output="".join(output_parts),
                tools=tools,
                error=error,
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

    async def resolve_user_feedback(
        self,
        run_id: str,
        *,
        selections: dict[str, list[str]],
        requirement_id: str | None = None,
    ) -> dict[str, Any]:
        """Resolve Agno's latest structured user-feedback requirement and resume the run."""
        paused = self._paused.pop(run_id, None)
        run = self.storage.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run["status"] != "paused" or paused is None:
            raise ValueError("Run is not paused in this server process")
        agent, requirements, session_id, user_id = paused
        pending = [item for item in requirements if getattr(item, "needs_user_feedback", False)]
        if not pending:
            self._paused[run_id] = paused
            raise ValueError("Run has no pending user-feedback requirement")
        target = (
            next(
                (item for item in reversed(pending) if _requirement_id(item) == requirement_id),
                None,
            )
            if requirement_id
            else pending[-1]
        )
        if target is None:
            self._paused[run_id] = paused
            raise ValueError("Pending user-feedback requirement does not exist")
        for requirement in pending:
            schema = getattr(requirement, "user_feedback_schema", None) or []
            if requirement is target:
                answers = selections
            else:
                answers = {question.question: [] for question in schema}
            requirement.provide_user_feedback(answers)
        if getattr(target, "needs_user_feedback", False):
            self._paused[run_id] = paused
            raise ValueError("请为每个问题选择至少一个选项")

        answer_text = "；".join(
            value.strip() for values in selections.values() for value in values if value.strip()
        )
        self.storage.append_run_event(
            run_id,
            event_type="feedback.resolved",
            payload={
                "kind": "user_feedback",
                "run_id": run_id,
                "requirement_id": _requirement_id(target),
                "selections": selections,
                "content": f"用户选择了：{answer_text or '已提交选择'}",
            },
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
                start_new_message=False,
            ),
            name=f"quickops-feedback:{run_id}",
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(run_id, None))
        return self.storage.get_run(run_id) or run

    async def _continue(
        self,
        agent: Agent,
        *,
        run_id: str,
        requirements: list[Any],
        session_id: str,
        user_id: str,
        existing_output: str,
        start_new_message: bool = False,
        _prior_output: str | None = None,
        _message_prefix: str | None = None,
        _boundary_sequence: int | None = None,
    ) -> None:
        prior_output = (
            _prior_output
            if _prior_output is not None
            else existing_output
            if start_new_message
            else ""
        )
        initial_message = (
            _message_prefix
            if _message_prefix is not None
            else ""
            if start_new_message
            else existing_output
        )
        output_parts = [initial_message] if initial_message else []
        boundary_sequence = _boundary_sequence or 0
        if start_new_message and _boundary_sequence is None:
            boundary_sequence = self.storage.append_run_event(
                run_id,
                event_type="continuation.started",
                payload={"reason": "user_feedback"},
            )["sequence"]
        terminal_output = ""
        tools: list[dict[str, Any]] = []
        paused_run = False
        auto_continue_requirements: list[Any] | None = None
        observed_input_tokens = 0
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
                elif event_type == "model.completed":
                    value = self._valid_observed_context_tokens(agent, payload)
                    if value:
                        observed_input_tokens = max(observed_input_tokens, value)
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
                    detail = payload.get("error") or "小维运行失败"
                    diagnostics = {
                        key: payload[key]
                        for key in ("error_type", "error_id")
                        if payload.get(key) is not None
                    }
                    additional = payload.get("additional_data")
                    if isinstance(additional, dict):
                        for key in ("status", "status_code", "code", "request_id", "model"):
                            if additional.get(key) is not None:
                                diagnostics[key] = additional[key]
                    if diagnostics:
                        detail = f"{detail} | {diagnostics}"
                    raise RuntimeError(detail)
                elif event_type == "run.cancelled":
                    self.storage.update_run(
                        run_id, status="cancelled", output_text="".join(output_parts)
                    )
                    self.storage.append_run_event(run_id, event_type=event_type, payload=payload)
                    return
                elif event_type == "run.paused":
                    new_requirements = _continuation_requirements(agno_event, payload)
                    if self._auto_confirmable_requirements(new_requirements, payload, session_id):
                        self._confirm_requirements(new_requirements)
                        auto_continue_requirements = new_requirements
                        continue
                    self._persist_pause_boundary(
                        run_id=run_id,
                        session_id=session_id,
                        output="".join(output_parts),
                        tools=tools,
                        payload=payload,
                        after_sequence=0,
                    )
                    self._paused[run_id] = (agent, new_requirements, session_id, user_id)
                    self.storage.update_run(
                        run_id,
                        status="paused",
                        output_text=prior_output + "".join(output_parts),
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
                    start_new_message=start_new_message,
                    _prior_output=prior_output,
                    _message_prefix="".join(output_parts),
                    _boundary_sequence=boundary_sequence,
                )
                return
            if paused_run:
                return
            terminal_for_message = terminal_output
            if start_new_message and prior_output and terminal_output.startswith(prior_output):
                terminal_for_message = terminal_output[len(prior_output) :]
            streamed_output = "".join(output_parts)
            streamed_suffix = (
                streamed_output[len(initial_message) :]
                if initial_message and streamed_output.startswith(initial_message)
                else streamed_output
            )
            terminal_suffix = (
                terminal_output[len(initial_message) :]
                if initial_message and terminal_output.startswith(initial_message)
                else terminal_for_message
            )
            output = _complete_output(streamed_output, terminal_for_message)
            if (
                not start_new_message
                and tools
                and not streamed_suffix.strip()
                and not terminal_suffix.strip()
            ):
                # Some OpenAI-compatible providers return only an EOS token after an Agno
                # confirmation continuation.  Do not present that as a mysteriously stopped
                # success: retain the executed tool evidence and make the empty model turn
                # explicit so the next ordinary user turn can continue from durable history.
                output = output.rstrip() + (
                    "\n\n> ⚠️ 审批后的工具调用已完成，但模型本轮没有生成后续说明。"
                    "执行结果已保留在上方工具记录中；发送“继续”即可基于该结果接着分析。"
                )
            # One user turn owns one assistant bubble across every approval/feedback pause.
            # Rebuild from the complete ordered event log; using only the final continuation
            # boundary collapses earlier text/tools/approvals into one giant text segment.
            segments = _message_segments(self.storage.list_run_events(run_id), output)
            message_content = output or "小维未返回文本内容。"
            message_metadata = {
                    "kind": "chat",
                    "run_id": run_id,
                    "tools": tools,
                    "segments": segments,
            }
            active_message_id = self._run_message_ids.pop(run_id, None)
            if active_message_id:
                assistant_message = self.storage.update_message(
                    active_message_id,
                    content=message_content,
                    metadata=message_metadata,
                )
            else:
                assistant_message = self.storage.append_message(
                    session_id,
                    role="assistant",
                    content=message_content,
                    metadata=message_metadata,
                )
            cumulative_output = prior_output + output
            self.storage.update_run(run_id, status="completed", output_text=cumulative_output)
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
            await self._mark_recovery_checkpoint_consumed(agent, session_id, user_id)
            self._schedule_session_summary(
                agent, session_id, user_id, observed_input_tokens=observed_input_tokens
            )
        except asyncio.CancelledError:
            self.storage.update_run(run_id, status="cancelled", output_text="".join(output_parts))
            self.storage.append_run_event(
                run_id,
                event_type="run.cancelled",
                payload={"reason": "Operator stopped the response"},
            )
            raise
        except Exception as error:
            self._persist_failed_assistant_message(
                run_id=run_id,
                session_id=session_id,
                output="".join(output_parts),
                tools=tools,
                error=error,
                after_sequence=0,
                cumulative_output=prior_output + "".join(output_parts),
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
