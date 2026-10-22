from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Fact(BaseModel):
    id: Optional[int] = None
    character_id: str
    user_id: str
    category: str = "general"  # identity, preference, habit, project, schedule, general
    key: str
    value: str
    confidence: float = 1.0
    active: bool = True
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)


class Episode(BaseModel):
    id: Optional[int] = None
    character_id: str
    user_id: str
    summary: str
    message_count: int = 0
    created_at: str = Field(default_factory=_utc_now_iso)


class MessageRecord(BaseModel):
    id: Optional[int] = None
    character_id: str
    user_id: str
    role: str
    content: str
    emotion: Optional[str] = None
    consolidated: bool = False
    timestamp: str = Field(default_factory=_utc_now_iso)
