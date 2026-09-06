"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from mindtrail import config
from mindtrail.advice.planner import generate_advice
from mindtrail.ingest.documents import DocumentError, extract_pdf_text
from mindtrail.ingest.fetch import FetchError, extract_title, fetch_html, html_to_text
from mindtrail.ingest.researcher import Researcher
from mindtrail.ingest.search import SearchError, default_search
from mindtrail.ingest.topic import TopicExtractor
from mindtrail.integrations.google_auth import default_token_path, run_oauth_flow, save_credentials
from mindtrail.integrations.google_calendar import GoogleCalendarClient
from mindtrail.llm import LLMClient, LLMError
from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.db import initialize
from mindtrail.organize.export import export_to_directory
from mindtrail.organize.migrate import backfill_conversations
from mindtrail.organize.profile import ProfileStore
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.restore_apply import import_from_directory
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.predict.next_query import predict_from_store
from mindtrail.web.chat_server import Deps, run_chat_server
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


def _assign_topic(llm: LLMClient, store: MemoryStore, headline: str, body: str):
    """Best-effort topic + key facts for content that isn't researched
    (a note or a document), so labeling is one shared path rather than
    duplicated in each command."""
    try:
        assignment = TopicExtractor(llm).extract(headline, body, store.topics())
        return assignment.topic, list(assignment.key_facts)
    except (LLMError, ValueError):
        return "", []


def cmd_note(args) -> int:
    store = MemoryStore()
    text = args.text.strip()
    headline = text.splitlines()[0][:80] if text else ""
    topic, facts = _assign_topic(LLMClient(), store, headline, text)

    # Attached to a conversation, same as the browser's Note button -
    # an unattached note has no way to appear in the sidebar at all.
    initialize()
    chats = ConversationStore()
    conversation = chats.create(title=headline or "Note")
    store.add(
        headline, text, [], topic=topic, key_facts=facts,
        kind="note", conversation_id=conversation.id,
    )
    print(f"saved note under topic: {topic or 'Uncategorized'}")
    return 0


def cmd_save_url(args) -> int:
    store = MemoryStore()
    url = args.url.strip()
    try:
        page_html = fetch_html(url)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    text = html_to_text(page_html).strip()
    if not text:
        print("error: no readable content found at that url", file=sys.stderr)
        return 1

    headline = extract_title(page_html) or url
    topic, facts = _assign_topic(LLMClient(), store, headline, text)

    # Attached to a conversation, same as the browser's Save a link
    # button - an unattached entry has no way to appear in the sidebar.
    initialize()
    chats = ConversationStore()
    conversation = chats.create(title=headline)
    store.add(
        headline, text, [url], topic=topic, key_facts=facts,
        kind="link", conversation_id=conversation.id,
    )
    print(f"saved link under topic: {topic or 'Uncategorized'}")
    return 0


def cmd_docs(args) -> int:
    store = MemoryStore()
    try:
        text = extract_pdf_text(args.path)
    except DocumentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    filename = Path(args.path).name
    headline = f"Document: {filename}"
    topic, facts = _assign_topic(LLMClient(), store, headline, text)

    store.add(
        headline,
        text,
        [str(Path(args.path).resolve())],
        topic=topic,
        key_facts=facts,
        kind="document",
    )
    print(f"stored {filename} under topic: {topic or 'Uncategorized'}")
    return 0


def cmd_advice(args) -> int:
    store = MemoryStore()
    result = generate_advice(LLMClient(), store.all())

    store.add("Advice", result.text, [], topic="Advice", kind="advice")
    print(result.text)
    return 0


def cmd_chat(args) -> int:
    store = MemoryStore()
    llm = LLMClient()
    extractor = TopicExtractor(llm)
    researcher = Researcher(store, default_search(), llm, topic_extractor=extractor)

    initialize()
    chats = ConversationStore()
    created = backfill_conversations(store, chats)
    if created:
        print(f"organized {created} existing topic(s) into conversations")
    reindexed = store.reindex_legacy_entries()
    if reindexed:
        print(f"reindexed {reindexed} existing entr{'y' if reindexed == 1 else 'ies'} for chunked search")

    deps = Deps(
        researcher=researcher,
        store=store,
        projects=ProjectStore(),
        chats=chats,
        llm=llm,
        topic_extractor=extractor,
    )
    run_chat_server(
        deps, port=args.port, open_browser=not args.no_open, host=args.host
    )
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


def cmd_export(args) -> int:
    initialize()
    count = export_to_directory(
        MemoryStore(),
        ConversationStore(),
        ProjectStore(),
        RoadmapStore(),
        RoadmapNodeStore(),
        ProfileStore(),
        args.out,
        args.project,
    )
    path = Path(args.out).resolve()
    print(f"exported {count} file(s) to {path}")
    return 0


def cmd_import(args) -> int:
    """Restore from a directory written by `mindtrail export`.

    CLI-only by design: restore can overwrite or merge into a live
    database, and a web button inviting that by accident is the wrong
    affordance for something this destructive.
    """
    initialize()
    summary = import_from_directory(
        args.dir,
        MemoryStore(),
        ConversationStore(),
        ProjectStore(),
        RoadmapStore(),
        RoadmapNodeStore(),
        ProfileStore(),
        overwrite=args.overwrite,
    )
    print(
        f"imported: {summary.created} created, {summary.skipped} skipped, "
        f"{summary.failed} failed"
    )
    for warning in summary.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 1 if summary.failed else 0


def cmd_calendar_connect(args) -> int:
    """Run the OAuth flow and store a refresh token. Never prints or logs
    the token itself - only where it landed."""
    if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
        print(
            "error: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first "
            "(see README's Google Calendar setup section)",
            file=sys.stderr,
        )
        return 1

    creds = run_oauth_flow(config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET)
    path = default_token_path()
    save_credentials(creds, path)
    print(f"connected - token stored at {path}")
    return 0


def cmd_calendar_today(args) -> int:
    snapshot = GoogleCalendarClient().snapshot()
    if not snapshot.get("connected"):
        hint = " run 'mindtrail calendar connect' to reconnect." if snapshot.get(
            "needs_reconnect"
        ) else " run 'mindtrail calendar connect' first."
        print(f"not connected to Google Calendar.{hint}")
        return 0

    if snapshot.get("error"):
        as_of = snapshot.get("as_of") or "earlier"
        print(f"warning: {snapshot['error']} - showing cached events from {as_of}", file=sys.stderr)
    elif snapshot.get("needs_reconnect"):
        print("warning: Google Calendar needs reconnecting - showing cached events", file=sys.stderr)

    events = snapshot.get("events", [])
    if not events:
        print("no events today")
        return 0
    for e in events:
        when = "all day" if e["all_day"] else e["start"]
        print(f"  {when:>8}  {e['title']}")
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

    note = sub.add_parser("note", help="save a manual note, topic-labeled like research")
    note.add_argument("text")
    note.set_defaults(func=cmd_note)

    docs = sub.add_parser("docs", help="parse a PDF and store its content")
    docs.add_argument("path")
    docs.set_defaults(func=cmd_docs)

    save_url = sub.add_parser("save-url", help="fetch a url and remember its content")
    save_url.add_argument("url")
    save_url.set_defaults(func=cmd_save_url)

    advice = sub.add_parser(
        "advice", help="generate a next-steps plan from everything stored"
    )
    advice.set_defaults(func=cmd_advice)

    web = sub.add_parser("web", help="generate a static page grouped by topic")
    web.add_argument("--out", default="mindtrail_site.html")
    web.add_argument("--no-open", action="store_true")
    web.set_defaults(func=cmd_web)

    export = sub.add_parser("export", help="export everything to markdown")
    export.add_argument("--out", required=True)
    export.add_argument("--project", default=None, help="limit to one project's id")
    export.set_defaults(func=cmd_export)

    imp = sub.add_parser("import", help="restore from a directory made by 'export'")
    imp.add_argument("dir")
    imp.add_argument(
        "--overwrite", action="store_true",
        help="replace existing records instead of skipping them",
    )
    imp.set_defaults(func=cmd_import)

    calendar = sub.add_parser("calendar", help="Google Calendar connection (read-only)")
    calendar_sub = calendar.add_subparsers(dest="calendar_command", required=True)
    connect = calendar_sub.add_parser(
        "connect", help="run the OAuth flow and store a refresh token"
    )
    connect.set_defaults(func=cmd_calendar_connect)
    today_cmd = calendar_sub.add_parser(
        "today", help="show today's events from the primary calendar"
    )
    today_cmd.set_defaults(func=cmd_calendar_today)

    chat = sub.add_parser("chat", help="chatbot interface in the browser")
    chat.add_argument("--port", type=int, default=8765)
    chat.add_argument("--no-open", action="store_true")
    chat.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address; use 0.0.0.0 inside a container so port mapping reaches it",
    )
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
