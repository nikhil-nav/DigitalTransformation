import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

CHAT_SCOPES = ("bcm", "data_quality")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_citations(raw_json: str | None) -> list[dict[str, Any]]:
    """Walk the persisted assistant transcript and pull out unique web/file citations."""
    if not raw_json:
        return []
    try:
        segments = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(segments, list):
        return []

    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        content = segment.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            citations = block.get("citations")
            if not isinstance(citations, list):
                continue
            for c in citations:
                if not isinstance(c, dict):
                    continue
                url = c.get("url")
                title = c.get("title") or url
                if not isinstance(url, str) or not url:
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                out.append(
                    {
                        "url": url,
                        "title": title,
                        "cited_text": c.get("cited_text"),
                    }
                )
    return out


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(
        String, nullable=False, default="bcm", server_default="bcm", index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False, default="New chat")
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "scope IN ('bcm','data_quality')", name="ck_chat_thread_scope"
        ),
        Index("ix_chat_threads_project_scope", "project_id", "scope"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scope: Mapped[str] = mapped_column(
        String, nullable=False, default="bcm", server_default="bcm", index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    @property
    def citations(self) -> list[dict[str, Any]]:
        return _extract_citations(self.raw)

    __table_args__ = (
        CheckConstraint(
            "scope IN ('bcm','data_quality')", name="ck_chat_message_scope"
        ),
        Index("ix_chat_msgs_project_scope_created", "project_id", "scope", "created_at"),
        Index("ix_chat_msgs_thread_created", "thread_id", "created_at"),
    )
