from __future__ import annotations

import json
import mimetypes
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from agno.media import File


class AttachmentError(ValueError):
    pass


class SessionAttachmentStore:
    """Durable, session-isolated storage for files supplied to Agno runs."""

    max_file_bytes = 25 * 1024 * 1024
    max_files_per_session = 100
    _safe_session = re.compile(r"^[A-Za-z0-9._-]{1,200}$")

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        if not self._safe_session.fullmatch(session_id):
            raise AttachmentError("无效的会话标识")
        directory = (self.root / session_id).resolve()
        if directory.parent != self.root:
            raise AttachmentError("无效的会话附件目录")
        return directory

    @staticmethod
    def _clean_filename(filename: str | None) -> str:
        name = Path(filename or "attachment").name.strip()
        if not name or name in {".", ".."}:
            name = "attachment"
        return name[:255]

    def save(
        self,
        session_id: str,
        *,
        filename: str | None,
        content_type: str | None,
        content: bytes,
    ) -> dict[str, Any]:
        if not content:
            raise AttachmentError("不能上传空文件")
        if len(content) > self.max_file_bytes:
            raise AttachmentError("单个附件不能超过 25 MB")
        directory = self._session_dir(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        if len(list(directory.glob("*.json"))) >= self.max_files_per_session:
            raise AttachmentError("当前会话附件数量已达到上限")
        attachment_id = uuid.uuid4().hex
        safe_name = self._clean_filename(filename)
        suffix = Path(safe_name).suffix[:20]
        path = directory / f"{attachment_id}{suffix}"
        mime_type = (
            (content_type or "").split(";", 1)[0].strip()
            or mimetypes.guess_type(safe_name)[0]
            or "application/octet-stream"
        )
        if mime_type not in File.valid_mime_types():
            try:
                content.decode("utf-8")
                mime_type = "text/plain"
            except UnicodeDecodeError as error:
                raise AttachmentError("当前文件类型不受模型附件输入支持") from error
        path.write_bytes(content)
        metadata = {
            "id": attachment_id,
            "session_id": session_id,
            "name": safe_name,
            "mime_type": mime_type,
            "size": len(content),
            "path": str(path),
        }
        (directory / f"{attachment_id}.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
        return self.public(metadata)

    def resolve(self, session_id: str, attachment_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{32}", attachment_id):
            raise AttachmentError("无效的附件标识")
        metadata_path = self._session_dir(session_id) / f"{attachment_id}.json"
        if not metadata_path.is_file():
            raise AttachmentError("附件不存在或不属于当前会话")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        path = Path(metadata["path"]).resolve()
        session_dir = self._session_dir(session_id)
        if path.parent != session_dir or not path.is_file():
            raise AttachmentError("附件文件不可用")
        metadata["path"] = str(path)
        return metadata

    def delete(self, session_id: str, attachment_id: str) -> bool:
        try:
            metadata = self.resolve(session_id, attachment_id)
        except AttachmentError:
            return False
        Path(metadata["path"]).unlink(missing_ok=True)
        (self._session_dir(session_id) / f"{attachment_id}.json").unlink(missing_ok=True)
        return True

    def delete_session(self, session_id: str) -> None:
        directory = self._session_dir(session_id)
        if directory.is_dir():
            shutil.rmtree(directory)

    @staticmethod
    def public(metadata: dict[str, Any]) -> dict[str, Any]:
        return {key: metadata[key] for key in ("id", "name", "mime_type", "size")}
