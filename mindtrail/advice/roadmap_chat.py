"""Talk about a roadmap and propose changes to it - never apply them.

The model only ever *proposes* actions (add a step, change a status, add
a note, delete a step). The caller is responsible for asking the user to
accept or reject each one before touching the real roadmap - this module
has no write access to anything, on purpose.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace

from mindtrail.llm import LLMClient
from mindtrail.organize.roadmaps import STATUSES, RoadmapNode

MAX_ACTIONS = 5
CHAT_MAX_TOKENS = 900

ACTION_TYPES = ("add_node", "update_status", "update_note", "delete_node", "tidy")

SYSTEM_PROMPT = (
    "You are a collaborator discussing one specific roadmap with its owner. "
    "You are given the goal, every current step with its id/title/status/note, "
    "the user's profile, and the conversation so far.\n\n"
    "Reply conversationally - answer questions, ask clarifying questions about "
    "how they want to view or reshape the plan, react to what they say. You "
    "cannot change the roadmap yourself - only the user can, by clicking "
    "Accept on a proposed action you send. When a change would help (adding "
    "a step, marking one done, rejecting one, attaching a note, deleting "
    "one, re-spacing the whole layout), propose it as a structured action "
    "instead of just describing it in text. In your reply, phrase it as "
    "something you're suggesting they confirm ('I've proposed marking it "
    "done below'), never as something already done ('I've marked it "
    "done') - it is not done until they accept it, and saying otherwise "
    "would be lying to them.\n\n"
    "Action types:\n"
    '- add_node: {"type": "add_node", "title": "...", "detail": "..."}\n'
    '- update_status: {"type": "update_status", "node_id": "...", '
    '"status": "accepted"|"rejected"|"done"|"proposed"}\n'
    '- update_note: {"type": "update_note", "node_id": "...", "note": "..."}\n'
    '- delete_node: {"type": "delete_node", "node_id": "..."}\n'
    '- tidy: {"type": "tidy"} - re-spaces every step into a clean, '
    "non-overlapping grid (accepted work first, then proposed, then done, "
    "then rejected). Propose this when they ask to clean up, sort, "
    "reorganize, or de-clutter the layout - it does not change any step's "
    "content or status, only where it sits on the canvas.\n\n"
    "Only use a node_id that appears in the current steps you were given. "
    "Propose at most a few actions per turn - most turns need zero.\n\n"
    'Respond with JSON only: {"reply": "...", "actions": [...]}, actions can '
    "be an empty list, no code fences."
)


@dataclass(frozen=True)
class RoadmapAction:
    type: str
    node_id: str = ""
    title: str = ""
    detail: str = ""
    status: str = ""
    note: str = ""
    label: str = ""


@dataclass(frozen=True)
class RoadmapChatResult:
    reply: str
    actions: tuple[RoadmapAction, ...] = field(default_factory=tuple)


def _label_for(action: RoadmapAction, titles_by_id: dict[str, str]) -> str:
    node_title = titles_by_id.get(action.node_id, "that step")
    if action.type == "add_node":
        return f'Add step: "{action.title}"'
    if action.type == "update_status":
        return f'Mark "{node_title}" as {action.status}'
    if action.type == "update_note":
        return f'Note on "{node_title}": {action.note}'
    if action.type == "delete_node":
        return f'Delete "{node_title}"'
    if action.type == "tidy":
        return "Tidy up: re-space every step into a clean grid"
    return action.type


def parse_chat_response(text: str, titles_by_id: dict[str, str]) -> RoadmapChatResult:
    """Tolerant of anything unparseable in the actions list - a malformed
    action is dropped rather than failing the whole reply, since the
    conversational text is usually still worth showing."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in roadmap chat output: {text[:200]}")

    data = json.loads(payload[start : end + 1])
    reply = str(data.get("reply", "")).strip()
    if not reply:
        raise ValueError("no reply text in roadmap chat output")

    raw_actions = data.get("actions", [])
    if not isinstance(raw_actions, list):
        raw_actions = []

    actions = []
    for item in raw_actions[:MAX_ACTIONS]:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type", ""))
        if action_type not in ACTION_TYPES:
            continue
        status = str(item.get("status", ""))
        if action_type == "update_status" and status not in STATUSES:
            continue
        node_id = str(item.get("node_id", ""))
        if action_type in ("update_status", "update_note", "delete_node"):
            if node_id not in titles_by_id:
                continue
        title = str(item.get("title", "")).strip()
        if action_type == "add_node" and not title:
            continue

        action = RoadmapAction(
            type=action_type,
            node_id=node_id,
            title=title,
            detail=str(item.get("detail", "")).strip(),
            status=status,
            note=str(item.get("note", "")).strip(),
        )
        actions.append(replace(action, label=_label_for(action, titles_by_id)))

    return RoadmapChatResult(reply=reply, actions=tuple(actions))


def _format_nodes(nodes: list[RoadmapNode]) -> str:
    if not nodes:
        return "No steps yet.\n\n"
    lines = []
    for n in nodes:
        line = f"- id={n.id} [{n.status}] {n.title}"
        if n.detail:
            line += f" - {n.detail}"
        if n.note:
            line += f" (user's note: {n.note})"
        lines.append(line)
    return "CURRENT STEPS:\n" + "\n".join(lines) + "\n\n"


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = [f"{h.get('role', 'user').upper()}: {h.get('content', '')}" for h in history]
    return "CONVERSATION SO FAR:\n" + "\n".join(lines) + "\n\n"


def chat_about_roadmap(
    llm: LLMClient,
    goal: str,
    nodes: list[RoadmapNode],
    profile: str,
    history: list[dict],
    message: str,
) -> RoadmapChatResult:
    """Raises ValueError for an empty message."""
    if not message.strip():
        raise ValueError("message must not be empty")

    titles_by_id = {n.id: n.title for n in nodes}
    prompt = (
        f"GOAL: {goal}\n\n"
        + (f"USER PROFILE:\n{profile}\n\n" if profile.strip() else "")
        + _format_nodes(nodes)
        + _format_history(history)
        + f"USER: {message}"
    )
    completion = llm.complete(SYSTEM_PROMPT, prompt, max_tokens=CHAT_MAX_TOKENS)
    return parse_chat_response(completion.text, titles_by_id)
