from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field


class AuditEntry(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tool_name: str
    arguments: dict[str, Any]
    tier: str
    approved: bool
    user_confirmed: bool = False
    duration_ms: float = 0.0
    success: bool
    output_preview: str
    error: Optional[str] = None


class AuditLogger:
    """Logs tool execution and authorization decisions for accountability and security."""

    def __init__(self, log_path: str | Path = "data/audit.log"):
        self.log_path = Path(log_path).expanduser().resolve()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tier: str,
        approved: bool,
        user_confirmed: bool,
        duration_ms: float,
        success: bool,
        output: str,
        error: Optional[str] = None,
    ) -> AuditEntry:
        # Avoid storing giant output buffers in audit logs
        preview = output[:300] + ("..." if len(output) > 300 else "")
        entry = AuditEntry(
            tool_name=tool_name,
            arguments=arguments,
            tier=tier,
            approved=approved,
            user_confirmed=user_confirmed,
            duration_ms=duration_ms,
            success=success,
            output_preview=preview,
            error=error,
        )

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

        return entry

    def get_recent(self, limit: int = 20) -> list[AuditEntry]:
        if not self.log_path.exists():
            return []

        entries: list[AuditEntry] = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in reversed(lines[-limit:]):
                line = line.strip()
                if line:
                    try:
                        entries.append(AuditEntry.model_validate_json(line))
                    except Exception:
                        pass
        return entries
