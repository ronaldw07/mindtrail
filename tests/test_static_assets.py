"""Checks on the real static files that a substring assertion can't do.

Every other UI test is `assert "..." in CHAT_HTML`, which ships a client
syntax error green. These actually parse the files.
"""

import re
import shutil
import subprocess

import pytest

from mindtrail.web.chat_server import STATIC_DIR

JS_PATH = STATIC_DIR / "app.js"
CSS_PATH = STATIC_DIR / "app.css"


def test_app_js_is_syntactically_valid():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH")

    result = subprocess.run(
        [node, "--check", str(JS_PATH)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_app_css_braces_are_balanced():
    css = CSS_PATH.read_text(encoding="utf-8")
    assert css.count("{") == css.count("}")


def test_app_css_custom_properties_all_resolve():
    css = CSS_PATH.read_text(encoding="utf-8")

    root_match = re.search(r":root\s*\{(.*?)\}", css, re.DOTALL)
    assert root_match, "expected a :root block declaring the design tokens"
    defined = set(re.findall(r"--([\w-]+)\s*:", root_match.group(1)))

    referenced = set(re.findall(r"var\(--([\w-]+)\)", css))

    missing = referenced - defined
    assert not missing, f"var(--token) referenced but never defined in :root: {missing}"
