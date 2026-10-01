"""Checks on the real static files that a substring assertion can't do.

Every other UI test is `assert "..." in CHAT_HTML`, which ships a client
syntax error green. These actually parse the files.
"""

import re
import shutil
import subprocess

import pytest

from mindtrail.web.chat_server import STATIC_DIR, STATIC_FILES
from mindtrail.web.chat_ui import CHAT_HTML

JS_FILES = sorted(name for name, _ in STATIC_FILES.values() if name.endswith(".js"))
CSS_FILES = sorted(name for name, _ in STATIC_FILES.values() if name.endswith(".css"))
CSS_PATH = STATIC_DIR / "app.css"


@pytest.mark.parametrize("name", JS_FILES)
def test_js_is_syntactically_valid(name):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH")

    result = subprocess.run(
        [node, "--check", str(STATIC_DIR / name)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", CSS_FILES)
def test_css_braces_are_balanced(name):
    css = (STATIC_DIR / name).read_text(encoding="utf-8")
    assert css.count("{") == css.count("}")


@pytest.mark.parametrize("name", CSS_FILES)
def test_css_custom_properties_all_resolve(name):
    root_match = re.search(r":root\s*\{(.*?)\}", CSS_PATH.read_text(encoding="utf-8"), re.DOTALL)
    assert root_match, "expected a :root block in app.css declaring the design tokens"
    defined = set(re.findall(r"--([\w-]+)\s*:", root_match.group(1)))

    referenced = set(re.findall(r"var\(--([\w-]+)\)", (STATIC_DIR / name).read_text(encoding="utf-8")))

    missing = referenced - defined
    assert not missing, f"var(--token) referenced but never defined in :root: {missing}"


def test_every_served_file_is_linked_from_the_page_and_exists():
    for url, (name, _) in STATIC_FILES.items():
        assert (STATIC_DIR / name).is_file(), name
        assert f'"{url}"' in CHAT_HTML, url


def test_view_scripts_load_before_app_js():
    """app.js's boot code may open any view immediately, so every script
    defining a view must already be loaded when app.js runs."""
    app_at = CHAT_HTML.index('"/static/app.js"')
    for name in JS_FILES:
        if name != "app.js":
            assert CHAT_HTML.index(f'"/static/{name}"') < app_at, name


def test_no_top_level_name_is_declared_in_two_scripts():
    """Every script shares one global scope. A const/let declared twice
    across files throws at load and takes the whole app down with it."""
    pattern = re.compile(r"^  (?:const|let|var|function|async function) ([A-Za-z_$][\w$]*)", re.M)
    seen: dict[str, str] = {}
    for name in JS_FILES:
        for ident in pattern.findall((STATIC_DIR / name).read_text(encoding="utf-8")):
            assert ident not in seen, f"{ident} declared in both {seen[ident]} and {name}"
            seen[ident] = name
