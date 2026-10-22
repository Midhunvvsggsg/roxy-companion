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

    def format_for_llm(self) -> str:
        if not self.success:
            return f"[Tool Error]: {self.error or self.output}"
        return self.output


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
