"""Read your Gemini prompts out of a Google Takeout export.

Google offers no API for Gemini chat history. Takeout does export it:
takeout.google.com -> My Activity -> Gemini Apps, as either
"My Activity.json" or "My Activity.html" depending on the format picked.
Both are handled. Only your prompts are kept - the replies are Gemini's,
and the prompts alone say what you were working on.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass

PROMPT_PREFIXES = ("Prompted ", "Prompted\u00a0", "Asked ")
MAX_PROMPT_CHARS = 160

_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
_HTML_DATE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (\d{1,2}), (\d{4})")
_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Prompt:
    date: str  # YYYY-MM-DD
    text: str


def _strip_prefix(text: str) -> str | None:
    for prefix in PROMPT_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return None


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_PROMPT_CHARS else text[:MAX_PROMPT_CHARS - 1] + "…"


def _from_json(data: list) -> list[Prompt]:
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        prompt = _strip_prefix(str(item.get("title", "")))
        when = str(item.get("time", ""))[:10]
        if prompt and re.match(r"\d{4}-\d{2}-\d{2}$", when):
            out.append(Prompt(when, _clip(prompt)))
    return out


def _from_html(text: str) -> list[Prompt]:
    out = []
    for cell in re.split(r'class="outer-cell', text)[1:]:
        match = re.search(r'class="content-cell[^"]*"[^>]*>(.*?)</div>', cell, re.DOTALL)
        if not match:
            continue
        lines = [html.unescape(_TAG.sub("", part)).strip()
                 for part in re.split(r"<br\s*/?>", match.group(1))]
        lines = [line for line in lines if line]
        if not lines:
            continue
        prompt = _strip_prefix(lines[0].replace("\u00a0", " "))
        date = next((m for m in (_HTML_DATE.search(line) for line in lines[1:]) if m), None)
        if prompt and date:
            when = f"{date.group(3)}-{_MONTHS[date.group(1)]:02d}-{int(date.group(2)):02d}"
            out.append(Prompt(when, _clip(prompt)))
    return out


def parse_takeout(text: str) -> list[Prompt]:
    """Every prompt in the export, oldest first, exact repeats dropped.
    ValueError if the file doesn't look like a Gemini activity export."""
    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            prompts = _from_json(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ValueError(f"that JSON file couldn't be read: {exc}") from exc
    elif "outer-cell" in text:
        prompts = _from_html(text)
    else:
        raise ValueError("that doesn't look like a Takeout My Activity file")
    seen, unique = set(), []
    for p in sorted(prompts, key=lambda p: p.date):
        key = p.text.lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique
