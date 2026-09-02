"""Turn a question into a sourced synthesis.

Past research on the same topic is retrieved first and folded into the
prompt, so answers build on what is already known rather than starting
cold each time.
"""

from __future__ import annotations

from dataclasses import dataclass

from mindtrail import config
from mindtrail.ingest.fetch import FetchError, fetch_url
from mindtrail.ingest.search import SearchError, SearchProvider
from mindtrail.ingest.topic import TopicExtractor
from mindtrail.llm import LLMClient, LLMError
from mindtrail.memory.store import Entry, MemoryStore

SYSTEM_PROMPT = (
    "You are a research assistant. Synthesize the supplied sources into a "
    "clear, factual answer of at most two paragraphs. Cite sources inline "
    "as [1], [2] matching their given numbers. If the sources do not answer "
    "the question, say so plainly instead of speculating. If prior research "
    "is supplied, build on it and note anything that contradicts it."
)


@dataclass(frozen=True)
class Research:
    query: str
    summary: str
    sources: tuple[str, ...]
    recalled: tuple[Entry, ...]
    tokens: int


CONVERSATION_TURN_CHARS = 400

REWRITE_PROMPT = (
    "Rewrite the user's latest question into a standalone web search "
    "query, resolving pronouns and implied subjects using the "
    "conversation. Reply with the query text only - no quotes, no "
    "explanation. If it already stands alone, repeat it unchanged."
)
REWRITE_MAX_CHARS = 200


def _format_prior(entries: list[Entry]) -> str:
    if not entries:
        return ""
    lines = [f"- Previously asked '{e.query}': {e.summary}" for e in entries]
    return "PRIOR RESEARCH FROM THIS USER:\n" + "\n".join(lines) + "\n\n"


def _format_conversation(entries: list[Entry]) -> str:
    """Earlier turns of the open chat, so follow-ups read as continuous.

    Semantic recall alone does not give conversational continuity: it
    surfaces topically similar entries from anywhere in memory, which is
    not the same as knowing what was just said in this thread.
    """
    if not entries:
        return ""
    lines = [
        f"Q: {e.query}\nA: {e.summary[:CONVERSATION_TURN_CHARS]}" for e in entries
    ]
    return "EARLIER IN THIS CONVERSATION:\n" + "\n\n".join(lines) + "\n\n"


def _gather_pages(
    provider: SearchProvider, query: str
) -> tuple[list[str], list[str]]:
    """Return (numbered source texts, urls) for the top search hits."""
    results = provider.search(query, config.SEARCH_RESULTS_PER_QUERY)

    texts: list[str] = []
    urls: list[str] = []
    for result in results:
        if len(texts) >= config.PAGES_FETCHED_PER_QUERY:
            break
        try:
            body = fetch_url(result.url)
        except FetchError:
            # A dead link is normal; fall back to the search snippet.
            body = result.snippet
        if not body.strip():
            continue
        texts.append(f"[{len(texts) + 1}] {result.title} ({result.url})\n{body}")
        urls.append(result.url)

    if not texts:
        raise SearchError(f"no usable sources found for '{query}'")
    return texts, urls


class Researcher:
    def __init__(
        self,
        store: MemoryStore,
        provider: SearchProvider,
        llm: LLMClient,
        topic_extractor: TopicExtractor | None = None,
    ):
        self._store = store
        self._provider = provider
        self._llm = llm
        self._topic_extractor = topic_extractor

    def _search_query(self, query: str, history: list[Entry]) -> str:
        """Resolve a follow-up into something worth searching for.

        "what are its main drawbacks?" searched literally returns pages
        about drawbacks in general. The synthesis prompt gets the
        conversation, but the search engine does not, so the query is
        rewritten first. Failure falls back to the original text - a
        worse search beats no answer.
        """
        if not history:
            return query
        try:
            completion = self._llm.complete(
                REWRITE_PROMPT,
                f"{_format_conversation(history[-2:])}LATEST QUESTION: {query}",
                max_tokens=120,
            )
        except LLMError:
            return query
        rewritten = completion.text.strip().strip('"')
        return rewritten[:REWRITE_MAX_CHARS] or query

    def research(
        self, query: str, conversation_id: str = "", instructions: str = ""
    ) -> Research:
        recalled = self._store.search(query, k=config.RELATED_MEMORIES_TO_INJECT)
        history = self._store.by_conversation(conversation_id)
        texts, urls = _gather_pages(self._provider, self._search_query(query, history))

        # Project instructions lead the prompt so they frame everything
        # after them, rather than trailing a wall of source text.
        preamble = (
            f"INSTRUCTIONS FOR THIS PROJECT (follow these):\n{instructions}\n\n"
            if instructions.strip()
            else ""
        )
        prompt = (
            f"{preamble}"
            f"{_format_conversation(history)}"
            f"{_format_prior(recalled)}QUESTION: {query}\n\n"
            f"SOURCES:\n" + "\n\n".join(texts)
        )
        completion = self._llm.complete(SYSTEM_PROMPT, prompt)

        return Research(
            query=query,
            summary=completion.text,
            sources=tuple(urls),
            recalled=tuple(recalled),
            tokens=completion.tokens,
        )

    def research_and_store(
        self, query: str, conversation_id: str = "", instructions: str = ""
    ) -> Research:
        result = self.research(
            query, conversation_id=conversation_id, instructions=instructions
        )
        topic, key_facts = self._assign_topic(result)
        self._store.add(
            result.query,
            result.summary,
            list(result.sources),
            topic=topic,
            key_facts=list(key_facts),
            conversation_id=conversation_id,
        )
        return result

    def _assign_topic(self, result: Research) -> tuple[str, tuple[str, ...]]:
        if self._topic_extractor is None:
            return "", ()
        try:
            assignment = self._topic_extractor.extract(
                result.query, result.summary, self._store.topics()
            )
        except (LLMError, ValueError):
            # Topic labeling is a display nicety; losing it should not
            # lose the research that was just done.
            return "", ()
        return assignment.topic, assignment.key_facts
