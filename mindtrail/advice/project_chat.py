"""Talk about a project and propose changes to it - never apply them.

Mirrors roadmap_chat.py's safety property: the model only ever *proposes*
an action. The caller applies it through the existing project endpoint
once the user accepts, so a chat-driven change and a hand-typed one are
indistinguishable to the server.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace

from mindtrail.llm import LLMClient

MAX_ACTIONS = 3
CHAT_MAX_TOKENS = 700

ACTION_TYPES = ("update_project",)

SYSTEM_PROMPT = (
    "You are a collaborator discussing one specific project with its owner. "
    "You are given the project's name, its current instructions (guidance "
    "applied to every answer generated in it), the user's profile, and the "
    "conversation so far.\n\n"
    "Reply conversationally - answer questions, react to what they say. You "
    "cannot change the project yourself - only the user can, by clicking "
    "Accept on a proposed action you send. When renaming the project or "
    "changing its instructions would help, propose it as a structured "
    "action instead of just describing it in text. Phrase your reply as a "
    "suggestion to confirm ('I've proposed updating the instructions "
    "below'), never as something already done - it is not applied until "
    "they accept it.\n\n"
    "Action type:\n"
    '- update_project: {"type": "update_project", "name": "...", '
    '"instructions": "..."} - include only the field(s) you are proposing '
    "to change; omit a field you are not touching.\n\n"
    "Propose at most one action per turn - most turns need zero.\n\n"
    'Respond with JSON only: {"reply": "...", "actions": [...]}, actions can '
    "be an empty list, no code fences."
)


@dataclass(frozen=True)
class ProjectAction:
    type: str
    name: str | None = None
    instructions: str | None = None
    label: str = ""


@dataclass(frozen=True)
class ProjectChatResult:
    reply: str
    actions: tuple[ProjectAction, ...] = field(default_factory=tuple)


def _label_for(action: ProjectAction) -> str:
    parts = []
    if action.name is not None:
        parts.append(f'rename to "{action.name}"')
    if action.instructions is not None:
        parts.append("update instructions")
    return "Project: " + " and ".join(parts) if parts else "Update project"


def parse_chat_response(text: str) -> ProjectChatResult:
    """Tolerant of anything unparseable in the actions list - a malformed
    action is dropped rather than failing the whole reply."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in project chat output: {text[:200]}")

    data = json.loads(payload[start : end + 1])
    reply = str(data.get("reply", "")).strip()
    if not reply:
        raise ValueError("no reply text in project chat output")

    raw_actions = data.get("actions", [])
    if not isinstance(raw_actions, list):
        raw_actions = []

    actions = []
    for item in raw_actions[:MAX_ACTIONS]:
        if not isinstance(item, dict):
            continue
        if str(item.get("type", "")) not in ACTION_TYPES:
            continue
        name = str(item["name"]).strip() if item.get("name") else None
        instructions = (
            str(item["instructions"]).strip() if "instructions" in item else None
        )
        if name is None and instructions is None:
            continue
        action = ProjectAction(type="update_project", name=name, instructions=instructions)
        actions.append(replace(action, label=_label_for(action)))

    return ProjectChatResult(reply=reply, actions=tuple(actions))


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = [f"{h.get('role', 'user').upper()}: {h.get('content', '')}" for h in history]
    return "CONVERSATION SO FAR:\n" + "\n".join(lines) + "\n\n"


def chat_about_project(
    llm: LLMClient,
    name: str,
    instructions: str,
    profile: str,
    history: list[dict],
    message: str,
) -> ProjectChatResult:
    """Raises ValueError for an empty message."""
    if not message.strip():
        raise ValueError("message must not be empty")

    prompt = (
        f"PROJECT NAME: {name}\n\n"
        f"CURRENT INSTRUCTIONS: {instructions or '(none set)'}\n\n"
        + (f"USER PROFILE:\n{profile}\n\n" if profile.strip() else "")
        + _format_history(history)
        + f"USER: {message}"
    )
    completion = llm.complete(SYSTEM_PROMPT, prompt, max_tokens=CHAT_MAX_TOKENS)
    return parse_chat_response(completion.text)
