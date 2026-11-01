from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
from kokoro_term.avatar.lipsync import LipSyncEngine


class AvatarBackend(ABC):
    """Abstract interface for avatar display backends (GUI window or terminal)."""

    @abstractmethod
    def start(self) -> None:
        """Initialize and display the avatar backend."""
        pass

    @abstractmethod
    def update_emotion(self, emotion: str) -> None:
        """Set the active character emotion."""
        pass

    def update_pose(self, pose: str) -> None:
        """Set the active body posture / hand gesture."""
        pass

    def set_roam(self, enabled: bool) -> None:
        """Enable or disable autonomous screen roaming."""
        pass

    @abstractmethod
    def set_speaking(self, speaking: bool, lipsync: Optional[LipSyncEngine] = None) -> None:
        """Signal speech start/stop and attach lip-sync engine."""
        pass

    def set_mouth(self, mouth: str) -> None:
        """Explicitly set mouth shape (e.g. 'closed', 'a', 'i', 'u', 'e', 'o')."""
        pass

    def set_mouth_level(self, level: float) -> None:
        """Set normalized mouth open level (0.0 to 1.0)."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Cleanly shut down backend resources."""
        pass
