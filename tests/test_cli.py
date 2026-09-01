"""CLI argument wiring. Commands themselves are covered elsewhere."""

import pytest

from mindtrail.cli import build_parser, cmd_ask, cmd_predict, cmd_search


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
