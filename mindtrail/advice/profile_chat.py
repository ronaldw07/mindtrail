"""Talk through the user's profile and propose an updated version - never
apply it. Mirrors roadmap_chat.py's safety property.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from mindtrail.llm import LLMClient

CHAT_MAX_TOKENS = 700

ACTION_TYPES = ("update_profile",)

SYSTEM_PROMPT = (
    "You are a collaborator helping the user write their profile - a short "
    "freeform description of themselves (role, goals, background) used to "
    "personalize every answer, highlight, and roadmap the app generates. "
    "You are given their current profile content and the conversation so "
    "far.\n\n"
    "Reply conversationally - ask what's missing, react to what they tell "
    "you. You cannot change the profile yourself - only the user can, by "
    "clicking Accept on a proposed version you send. When you have enough "
    "to propose an update, propose the FULL replacement text (not a diff "
    "or a partial addition) as a structured action. Phrase your reply as a "
    "suggestion to confirm, never as something already saved.\n\n"
    "Action type:\n"
    '- update_profile: {"type": "update_profile", "content": "..."} - the '
    "complete profile text to replace the current one with.\n\n"
    "Propose at most one action per turn - most turns need zero.\n\n"
    'Respond with JSON only: {"reply": "...", "actions": [...]}, actions can '
    "be an empty list, no code fences."
)


@dataclass(frozen=True)
class ProfileAction:
    type: str
    content: str = ""
    label: str = ""


@dataclass(frozen=True)
class ProfileChatResult:
    reply: str
    actions: tuple[ProfileAction, ...] = field(default_factory=tuple)


def parse_chat_response(text: str) -> ProfileChatResult:
    """Tolerant of anything unparseable in the actions list - a malformed
    action is dropped rather than failing the whole reply."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in profile chat output: {text[:200]}")

    data = json.loads(payload[start : end + 1])
    reply = str(data.get("reply", "")).strip()
    if not reply:
        raise ValueError("no reply text in profile chat output")

    raw_actions = data.get("actions", [])
    if not isinstance(raw_actions, list):
        raw_actions = []

    actions = []
    for item in raw_actions[:1]:
        if not isinstance(item, dict):
            continue
        if str(item.get("type", "")) not in ACTION_TYPES:
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        actions.append(
            ProfileAction(
                type="update_profile",
                content=content,
                label="Update profile with the proposed text",
            )
        )

    return ProfileChatResult(reply=reply, actions=tuple(actions))


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = [f"{h.get('role', 'user').upper()}: {h.get('content', '')}" for h in history]
    return "CONVERSATION SO FAR:\n" + "\n".join(lines) + "\n\n"


def chat_about_profile(
    llm: LLMClient,
    current_content: str,
    history: list[dict],
    message: str,
) -> ProfileChatResult:
    """Raises ValueError for an empty message."""
    if not message.strip():
        raise ValueError("message must not be empty")

    prompt = (
        f"CURRENT PROFILE: {current_content or '(empty)'}\n\n"
        + _format_history(history)
        + f"USER: {message}"
    )
    completion = llm.complete(SYSTEM_PROMPT, prompt, max_tokens=CHAT_MAX_TOKENS)
    return parse_chat_response(completion.text)
