from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

ToolTier = Literal["safe", "moderate", "dangerous"]


class ToolResult(BaseModel):
    success: bool
    output: str
    error: Optional[str] = None
    diff: Optional[str] = None
    needs_confirmation: bool = False
    confirmation_prompt: Optional[str] = None
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    stderr: str = ""
    detail: str = ""
    data: Optional[dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.success

    def to_dict(self) -> dict[str, Any]:
        res = {
            "ok": self.success,
            "pid": self.pid,
            "exit_code": self.exit_code,
            "stderr": self.stderr or (self.error or ""),
            "detail": self.detail or self.output or (self.error or ""),
        }
        if self.data is not None:
            res["data"] = self.data
        return res

    def format_for_llm(self) -> str:
        if not self.success:
            err = self.error or self.detail or self.output
            return f"[Tool Error]: {err} (Result: {self.to_dict()})"
        return f"{self.output} (Result: {self.to_dict()})"


class BaseTool(ABC):
    """Abstract base class for all tools."""

    name: str
    description: str
    parameters: dict[str, Any]
    tier: ToolTier = "safe"

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Run the tool with the provided arguments."""
        pass

    async def dry_run(self, **kwargs) -> str:
        """Return a string describing the planned action without executing it."""
        return f"Would execute {self.name} with arguments: {kwargs}"
