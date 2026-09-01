"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from mindtrail.ingest.researcher import Researcher
from mindtrail.ingest.search import SearchError, default_search
from mindtrail.ingest.topic import TopicExtractor
from mindtrail.llm import LLMClient, LLMError
from mindtrail.memory.store import MemoryStore
from mindtrail.predict.next_query import predict_from_store
from mindtrail.web.chat_server import run_chat_server
from mindtrail.web.generate import build_html

DIVIDER = "-" * 68


def _print_wrapped(label: str, body: str) -> None:
    print(f"\n{label}\n{DIVIDER}\n{body}\n")


def cmd_ask(args) -> int:
    store = MemoryStore()
    llm = LLMClient()
    researcher = Researcher(
        store, default_search(), llm, topic_extractor=TopicExtractor(llm)
    )
    result = researcher.research_and_store(args.question)

    _print_wrapped(f"Q: {result.query}", result.summary)
    if result.recalled:
        print("Built on earlier research:")
        for entry in result.recalled:
            print(f"  - {entry.query}")
        print()
    print("Sources:")
    for i, url in enumerate(result.sources, start=1):
        print(f"  [{i}] {url}")
    print(f"\n({result.tokens} tokens, {store.count()} entries in memory)")
    return 0


def cmd_search(args) -> int:
    store = MemoryStore()
    found = store.search(args.topic, k=args.limit)
    if not found:
        print("Nothing in memory matches that yet.")
        return 0

    for entry in found:
        _print_wrapped(f"Q: {entry.query}  ({entry.created_at[:10]})", entry.summary)
    return 0


def cmd_predict(args) -> int:
    store = MemoryStore()
    if store.count() == 0:
        print("No research history yet. Run 'mindtrail ask' first.")
        return 0

    predictions = predict_from_store(store, LLMClient(), history=args.history)
    print("\nYou will probably want to know next:\n")
    for i, prediction in enumerate(predictions, start=1):
        print(f"  {i}. {prediction.question}")
        if prediction.reasoning:
            print(f"     {prediction.reasoning}")
    print()
    return 0


def cmd_stats(args) -> int:
    store = MemoryStore()
    print(f"{store.count()} entries in memory")
    for entry in store.recent(args.limit):
        print(f"  {entry.created_at[:16]}  {entry.query}")
    return 0


def cmd_chat(args) -> int:
    store = MemoryStore()
    llm = LLMClient()
    researcher = Researcher(
        store, default_search(), llm, topic_extractor=TopicExtractor(llm)
    )
    run_chat_server(researcher, port=args.port, open_browser=not args.no_open)
    return 0


def cmd_web(args) -> int:
    store = MemoryStore()
    html = build_html(store.all())

    path = Path(args.out).resolve()
    path.write_text(html)
    print(f"wrote {path}")

    if not args.no_open:
        webbrowser.open(f"file://{path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mindtrail",
        description="Research assistant with a searchable, self-updating memory.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="research a question and remember the answer")
    ask.add_argument("question")
    ask.set_defaults(func=cmd_ask)

    search = sub.add_parser("search", help="search past research, no new lookups")
    search.add_argument("topic")
    search.add_argument("--limit", type=int, default=3)
    search.set_defaults(func=cmd_search)

    predict = sub.add_parser("predict", help="predict your next question")
    predict.add_argument("--history", type=int, default=5)
    predict.set_defaults(func=cmd_predict)

    stats = sub.add_parser("stats", help="show what is in memory")
    stats.add_argument("--limit", type=int, default=10)
    stats.set_defaults(func=cmd_stats)

    web = sub.add_parser("web", help="generate a static page grouped by topic")
    web.add_argument("--out", default="mindtrail_site.html")
    web.add_argument("--no-open", action="store_true")
    web.set_defaults(func=cmd_web)

    chat = sub.add_parser("chat", help="chatbot interface in the browser")
    chat.add_argument("--port", type=int, default=8765)
    chat.add_argument("--no-open", action="store_true")
    chat.set_defaults(func=cmd_chat)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (LLMError, SearchError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        # Chroma raises its own errors for a locked or unreadable store,
        # and a raw traceback is not a useful answer to "what went wrong".
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
