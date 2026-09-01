"""CLI argument wiring. Commands themselves are covered elsewhere."""

import pytest

from mindtrail.cli import build_parser, cmd_ask, cmd_predict, cmd_search, main
from mindtrail.llm import LLMError


def test_ask_routes_to_the_ask_command():
    args = build_parser().parse_args(["ask", "what is X"])

    assert args.func is cmd_ask
    assert args.question == "what is X"


def test_search_routes_with_its_default_limit():
    args = build_parser().parse_args(["search", "topic"])

    assert args.func is cmd_search
    assert args.limit == 3


def test_predict_accepts_a_history_length():
    args = build_parser().parse_args(["predict", "--history", "8"])

    assert args.func is cmd_predict
    assert args.history == 8


def test_a_command_is_required():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_unknown_command_is_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["explode"])


def _run_raising(exc, monkeypatch, capsys):
    """Run `stats` with a command body that raises, and capture stderr.

    build_parser resolves cmd_stats from module globals when it runs, so
    patching the attribute is enough to swap the command body.
    """

    def boom(args):
        raise exc

    monkeypatch.setattr("mindtrail.cli.cmd_stats", boom)
    code = main(["stats"])
    return code, capsys.readouterr().err


def test_known_errors_become_a_clean_message(monkeypatch, capsys):
    code, err = _run_raising(LLMError("no key"), monkeypatch, capsys)

    assert code == 1
    assert "error: no key" in err


def test_unexpected_errors_are_not_raw_tracebacks(monkeypatch, capsys):
    # Chroma can raise its own types; the user should still get one line.
    code, err = _run_raising(RuntimeError("database is locked"), monkeypatch, capsys)

    assert code == 1
    assert "RuntimeError: database is locked" in err


def test_interrupt_returns_the_conventional_code(monkeypatch, capsys):
    code, err = _run_raising(KeyboardInterrupt(), monkeypatch, capsys)

    assert code == 130
    assert "interrupted" in err
