"""Pull the JSON object out of a model reply.

Models wrap JSON in code fences or a sentence of preamble often enough
that a bare json.loads fails on otherwise-good output.
"""

from __future__ import annotations

import json
import re


def extract_json_object(text: str) -> dict:
    """The first {...} object in `text`, or ValueError."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model output: {text[:200]}")
    data = json.loads(payload[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model output JSON is not an object")
    return data
