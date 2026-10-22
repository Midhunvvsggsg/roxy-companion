from __future__ import annotations

import re
from typing import Optional
from kokoro_term.relationship.models import RelationshipState
from kokoro_term.tools.base import BaseTool


CONFIRM_PATTERNS = [
    r"\b(yes|confirm|proceed|do it|go ahead|i am sure|approved)\b",
]


class ResistanceManager:
    """Handles Roxy's in-character resistance, safety protests, and single-warning compliance model."""

    def __init__(self):
        # Maps pending action signature to warning issued state
        self._pending_confirmation: dict[str, dict] = {}

    def is_user_confirming(self, user_message: str) -> bool:
        lower = user_message.strip().lower()
        return any(re.search(pat, lower) for pat in CONFIRM_PATTERNS)

    def generate_objection(
        self,
        tool: BaseTool,
        arguments: dict,
        rel_state: RelationshipState,
    ) -> str:
        """Formulate a personalized, in-character objection scaled by affection and tsundere level."""
        action_desc = f"{tool.name}({arguments})"

        if rel_state.affection >= 70:
            if rel_state.tsundere_level >= 60:
                return (
                    f"[emotion:blush] W-wait a second! Are you being completely reckless, {rel_state.user_id}?! "
                    f"Executing `{action_desc}` could cause irreversible damage, and... I-I would be upset if your work was ruined! "
                    f"If you are absolutely certain, please reply with 'confirm' or 'yes' and I will proceed."
                )
            else:
                return (
                    f"[emotion:thinking] Please hold on. Running `{action_desc}` is dangerous, and I am genuinely concerned for your system. "
                    f"Are you completely certain? If you truly want this, reply 'confirm' and I will take care of it carefully."
                )
        elif rel_state.affection <= 30:
            return (
                f"[emotion:neutral] That operation (`{action_desc}`) carries high risk. "
                f"As a matter of protocol, I require explicit confirmation before I touch system files. Reply 'confirm' to execute."
            )
        else:
            return (
                f"[emotion:pout] Wait! As your teacher, I have to object. Running `{action_desc}` is not something a diligent apprentice "
                f"should do without caution. Are you certain? Tell me 'confirm' if you really intend to do this."
            )

    def register_pending(self, tool_name: str, arguments: dict) -> str:
        sig = f"{tool_name}:{sorted(arguments.items())}"
        self._pending_confirmation[sig] = {"tool_name": tool_name, "arguments": arguments}
        return sig

    def consume_pending(self) -> Optional[tuple[str, dict]]:
        if not self._pending_confirmation:
            return None
        sig, data = self._pending_confirmation.popitem()
        return data["tool_name"], data["arguments"]

    def has_pending(self) -> bool:
        return len(self._pending_confirmation) > 0
