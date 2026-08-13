from __future__ import annotations

import re
from typing import Any, Protocol

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from quickops.model_capabilities import (
    ThinkingMode,
    compatible_chat_role_map,
    thinking_extra_body,
)


class SessionTitleGenerator(Protocol):
    async def generate(self, first_user_message: str) -> str: ...


class AgnoSessionTitleGenerator:
    """A dedicated, tool-free Agno agent for naming a session.

    Title generation intentionally has no conversation memory or tools. The provider-specific
    request adapter always forces thinking off, so this second model call cannot consume a
    reasoning trace from the diagnostic agent.
    """

    def __init__(
        self,
        *,
        model_id: str,
        base_url: str,
        api_key: str,
        provider: str = "SiliconFlow",
    ):
        model = OpenAIChat(
            id=model_id,
            name="QuickOps session title model",
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            temperature=0.2,
            max_tokens=40,
            timeout=30,
            retries=1,
            role_map=compatible_chat_role_map(),
            extra_body=thinking_extra_body(
                provider=provider,
                mode=ThinkingMode.OFF,
                model_id=model_id,
                base_url=base_url,
            ),
        )
        self.agent = Agent(
            id="quickops-session-title",
            name="QuickOps Session Title Generator",
            model=model,
            tools=[],
            instructions=[
                "根据用户开启会话后的第一句话生成简洁的中文运维会话标题。",
                "只输出标题，不要引号、解释、Markdown 或标点结尾。",
                "标题最多 18 个中文字符；保留必要的产品名、服务名或主机名。",
            ],
            markdown=False,
            add_history_to_context=False,
        )

    async def generate(self, first_user_message: str) -> str:
        response = await self.agent.arun(first_user_message, stream=False)
        return normalize_title(getattr(response, "content", response))


def normalize_title(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^(?:标题|会话标题)\s*[:：]\s*", "", text)
    text = text.strip("`#* \t\r\n\"'“”‘’")
    text = re.sub(r"^(?:标题|会话标题)\s*[:：]\s*", "", text)
    text = text.strip("`#* \t\r\n\"'“”‘’")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[。！？!?；;，,：:]$", "", text).strip("\"'“”‘’")
    return text[:18] or "新会话"
