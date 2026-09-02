"""Local chat interface over the researcher.

Built on stdlib http.server rather than a web framework: a single local
user hitting a handful of endpoints does not need routing, middleware, or
async handling, and it avoids adding another dependency to an already
torch-adjacent install.
"""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from mindtrail.ingest.researcher import Researcher
from mindtrail.memory.store import UNCATEGORIZED, MemoryStore

CHAT_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>mindtrail</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, system-ui, sans-serif;
           background: #1a1a1a; color: #ececec; height: 100vh; overflow: hidden; }
    #app { display: flex; height: 100vh; }

    #sidebar { width: 260px; background: #171717; border-right: 1px solid #2a2a2a;
               display: flex; flex-direction: column; flex-shrink: 0; }
    .brand { padding: 1rem 1rem 0.5rem; font-weight: 600; letter-spacing: 0.02em; }
    #new-chat { margin: 0.5rem 1rem; padding: 0.55rem 0.8rem; border-radius: 8px;
                border: 1px solid #333; background: #212121; color: #ececec;
                cursor: pointer; text-align: left; font-size: 0.9rem; }
    #new-chat:hover { background: #2a2a2a; }
    #topic-search { margin: 0.25rem 1rem 0.5rem; padding: 0.5rem 0.7rem;
                    border-radius: 8px; border: 1px solid #2a2a2a; background: #1e1e1e;
                    color: #ececec; font-size: 0.85rem; }
    #topic-list { flex: 1; overflow-y: auto; padding: 0 0.5rem 1rem; }
    .topic-item { display: flex; justify-content: space-between; gap: 0.5rem;
                  padding: 0.5rem 0.6rem; border-radius: 6px; cursor: pointer;
                  font-size: 0.86rem; color: #c8c8c8; }
    .topic-item:hover { background: #212121; }
    .topic-item.active { background: #262626; color: #fff; }
    .topic-count { color: #777; font-size: 0.78rem; }

    main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    #breadcrumb { padding: 0.9rem 1.5rem; border-bottom: 1px solid #2a2a2a;
                  font-size: 0.85rem; color: #999; flex-shrink: 0; }
    #breadcrumb b { color: #ececec; font-weight: 600; }

    #log { flex: 1; overflow-y: auto; padding: 1.5rem 2rem; max-width: 760px;
           margin: 0 auto; width: 100%; }
    .turn { margin-bottom: 1.6rem; }
    .user-line { display: flex; justify-content: flex-end; margin-bottom: 0.6rem; }
    .user-line span { background: #2a2a2a; padding: 0.5rem 0.9rem; border-radius: 14px;
                       max-width: 80%; white-space: pre-wrap; font-size: 0.95rem; }
    .assistant-text { white-space: pre-wrap; line-height: 1.6; font-size: 0.97rem; }
    .assistant-text.pending { color: #888; font-style: italic; }
    .meta { margin-top: 0.6rem; font-size: 0.78rem; color: #888; }
    .meta a { color: #8ab4f8; display: block; text-decoration: none; }
    .meta a:hover { text-decoration: underline; }
    .kind-tag { display: inline-block; font-size: 0.68rem; text-transform: uppercase;
                letter-spacing: 0.03em; color: #999; margin-bottom: 0.3rem; }

    #composer { padding: 1rem 1.5rem 1.5rem; flex-shrink: 0; }
    form { max-width: 760px; margin: 0 auto; display: flex; align-items: center;
           gap: 0.5rem; background: #212121; border: 1px solid #333; border-radius: 26px;
           padding: 0.35rem 0.4rem 0.35rem 1.1rem; }
    #input { flex: 1; background: transparent; border: none; outline: none;
             color: #ececec; font-size: 0.95rem; padding: 0.5rem 0; }
    #input::placeholder { color: #777; }
    button { padding: 0.55rem 1.1rem; border-radius: 20px; border: none;
             background: #4f46e5; color: white; font-size: 0.88rem; cursor: pointer; }
    button:disabled { opacity: 0.4; cursor: default; }
  </style>
</head>
<body>
  <div id="app">
    <aside id="sidebar">
      <div class="brand">mindtrail</div>
      <button id="new-chat">+ New</button>
      <input id="topic-search" placeholder="Search topics...">
      <div id="topic-list"></div>
    </aside>
    <main>
      <div id="breadcrumb">New chat</div>
      <div id="log"></div>
      <div id="composer">
        <form id="form">
          <input id="input" autocomplete="off" placeholder="Ask something..." autofocus>
          <button id="send">Ask</button>
        </form>
      </div>
    </main>
  </div>
  <script>
    const log = document.getElementById('log');
    const form = document.getElementById('form');
    const input = document.getElementById('input');
    const send = document.getElementById('send');
    const topicList = document.getElementById('topic-list');
    const topicSearch = document.getElementById('topic-search');
    const breadcrumb = document.getElementById('breadcrumb');
    let topics = [];

    function turn() {
      const div = document.createElement('div');
      div.className = 'turn';
      log.appendChild(div);
      return div;
    }

    function userLine(container, text) {
      const row = document.createElement('div');
      row.className = 'user-line';
      const span = document.createElement('span');
      span.textContent = text;
      row.appendChild(span);
      container.appendChild(row);
    }

    function assistantText(container, text, kind) {
      if (kind && kind !== 'research') {
        const tag = document.createElement('div');
        tag.className = 'kind-tag';
        tag.textContent = kind;
        container.appendChild(tag);
      }
      const div = document.createElement('div');
      div.className = 'assistant-text';
      div.textContent = text;
      container.appendChild(div);
      return div;
    }

    function metaBlock(container, recalled, sources) {
      if (!(recalled && recalled.length) && !(sources && sources.length)) return;
      const meta = document.createElement('div');
      meta.className = 'meta';
      if (recalled && recalled.length) {
        meta.innerHTML += 'Built on: ' + recalled.join(', ') + '<br>';
      }
      (sources || []).forEach(u => {
        const a = document.createElement('a');
        a.href = u; a.target = '_blank'; a.rel = 'noopener';
        a.textContent = u;
        meta.appendChild(a);
      });
      container.appendChild(meta);
    }

    async function loadTopics() {
      const res = await fetch('/api/topics');
      const data = await res.json();
      topics = data.topics || [];
      renderTopicList();
    }

    function renderTopicList() {
      const q = topicSearch.value.trim().toLowerCase();
      topicList.innerHTML = '';
      topics
        .filter(t => !q || t.name.toLowerCase().includes(q))
        .forEach(t => {
          const item = document.createElement('div');
          item.className = 'topic-item';
          item.dataset.name = t.name;
          item.innerHTML = '<span>' + t.name + '</span><span class="topic-count">' + t.count + '</span>';
          item.addEventListener('click', () => openTopic(t.name));
          topicList.appendChild(item);
        });
    }

    async function openTopic(name) {
      breadcrumb.innerHTML = '<b>' + name + '</b>';
      document.querySelectorAll('.topic-item').forEach(el => {
        el.classList.toggle('active', el.dataset.name === name);
      });
      log.innerHTML = '';
      const res = await fetch('/api/topic/' + encodeURIComponent(name));
      const data = await res.json();
      (data.entries || []).forEach(e => {
        const t = turn();
        userLine(t, e.query);
        assistantText(t, e.summary, e.kind);
        metaBlock(t, [], e.sources);
      });
      log.scrollTop = log.scrollHeight;
    }

    document.getElementById('new-chat').addEventListener('click', () => {
      log.innerHTML = '';
      breadcrumb.textContent = 'New chat';
      document.querySelectorAll('.topic-item').forEach(el => el.classList.remove('active'));
      input.focus();
    });

    topicSearch.addEventListener('input', renderTopicList);

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      input.value = '';
      const t = turn();
      userLine(t, message);
      const pending = assistantText(t, 'thinking...', null);
      pending.classList.add('pending');
      log.scrollTop = log.scrollHeight;
      input.disabled = true;
      send.disabled = true;

      try {
        const res = await fetch('/api/ask', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message })
        });
        const data = await res.json();
        pending.classList.remove('pending');

        if (data.error) {
          pending.textContent = 'Error: ' + data.error;
        } else {
          pending.textContent = data.answer;
          metaBlock(t, data.recalled, data.sources);
          if (data.topic) breadcrumb.innerHTML = '<b>' + data.topic + '</b>';
          loadTopics();
        }
      } catch (err) {
        pending.classList.remove('pending');
        pending.textContent = 'Error: request failed';
      } finally {
        input.disabled = false;
        send.disabled = false;
        input.focus();
        log.scrollTop = log.scrollHeight;
      }
    });

    loadTopics();
  </script>
</body>
</html>"""


def handle_ask(researcher: Researcher, store: MemoryStore, message: str) -> dict:
    """Run one research turn and shape the JSON response.

    Kept separate from the HTTP layer so the logic is testable without a
    running server or a real socket.
    """
    if not message.strip():
        return {"error": "message was empty"}

    try:
        result = researcher.research_and_store(message)
    except Exception as exc:  # noqa: BLE001 - errors are shown in the chat UI
        return {"error": str(exc)}

    # The topic was assigned during research_and_store but not returned by
    # it, so the entry just stored is re-read rather than plumbing the
    # value through Research's fixed shape.
    recent = store.recent(1)
    topic = recent[0].topic if recent else ""

    return {
        "answer": result.summary,
        "sources": list(result.sources),
        "recalled": [e.query for e in result.recalled],
        "topic": topic or UNCATEGORIZED,
    }


def handle_topics(store: MemoryStore) -> dict:
    """Distinct topics with entry counts, for the sidebar list.

    Advice entries are excluded - they're a plan about the topics, not a
    topic of their own, matching how the static site pins them separately.
    """
    counts: dict[str, int] = {}
    for entry in store.all():
        if entry.kind == "advice":
            continue
        label = entry.topic or UNCATEGORIZED
        counts[label] = counts.get(label, 0) + 1

    ordered = sorted(counts, key=lambda t: (t == UNCATEGORIZED, t.lower()))
    return {"topics": [{"name": t, "count": counts[t]} for t in ordered]}


def handle_topic_entries(store: MemoryStore, topic: str) -> dict:
    """A topic's entries oldest-first, so they read like a conversation."""
    matches = [
        e for e in store.all() if (e.topic or UNCATEGORIZED) == topic and e.kind != "advice"
    ]
    matches.sort(key=lambda e: e.created_at)
    return {
        "entries": [
            {
                "query": e.query,
                "summary": e.summary,
                "created_at": e.created_at,
                "kind": e.kind,
                "sources": list(e.sources),
            }
            for e in matches
        ]
    }


def make_handler(
    researcher: Researcher, store: MemoryStore
) -> type[BaseHTTPRequestHandler]:
    class ChatHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # keep the terminal quiet during a chat session

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, body_text: str) -> None:
            body = body_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self._send_html(CHAT_HTML)
            elif self.path == "/api/topics":
                self._send_json(200, handle_topics(store))
            elif self.path.startswith("/api/topic/"):
                name = unquote(self.path[len("/api/topic/") :])
                self._send_json(200, handle_topic_entries(store, name))
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path != "/api/ask":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send_json(400, {"error": "malformed request body"})
                return
            result = handle_ask(researcher, store, str(payload.get("message", "")))
            self._send_json(200, result)

    return ChatHandler


def run_chat_server(
    researcher: Researcher,
    store: MemoryStore,
    port: int = 8765,
    open_browser: bool = True,
    host: str = "127.0.0.1",
) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(researcher, store))
    url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"
    print(f"mindtrail chat running at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
