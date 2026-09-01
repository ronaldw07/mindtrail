"""Local chat interface over the researcher.

Built on stdlib http.server rather than a web framework: a single local
user hitting one endpoint does not need routing, middleware, or async
handling, and it avoids adding another dependency to an already
torch-adjacent install.
"""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mindtrail.ingest.researcher import Researcher

CHAT_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>mindtrail chat</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: -apple-system, system-ui, sans-serif; max-width: 720px;
           margin: 0 auto; padding: 1rem; display: flex; flex-direction: column;
           height: 100vh; box-sizing: border-box; }
    h1 { margin: 0 0 1rem; font-size: 1.2rem; }
    #log { flex: 1; overflow-y: auto; padding-right: 0.25rem; }
    .msg { margin: 0.75rem 0; padding: 0.7rem 0.9rem; border-radius: 10px;
           max-width: 85%; white-space: pre-wrap; line-height: 1.45; }
    .user { background: #2563eb; color: white; margin-left: auto; }
    .assistant { background: #e5e5ea; color: #111; }
    @media (prefers-color-scheme: dark) { .assistant { background: #2c2c2e; color: #eee; } }
    .meta { font-size: 0.78rem; opacity: 0.7; margin-top: 0.4rem; }
    .meta a { color: inherit; }
    .pending { opacity: 0.6; font-style: italic; }
    form { display: flex; gap: 0.5rem; margin-top: 0.75rem; }
    input { flex: 1; padding: 0.7rem; font-size: 1rem; border-radius: 8px;
            border: 1px solid #ccc; }
    button { padding: 0.7rem 1.1rem; border-radius: 8px; border: none;
             background: #2563eb; color: white; font-size: 1rem; cursor: pointer; }
    button:disabled { opacity: 0.5; cursor: default; }
  </style>
</head>
<body>
  <h1>mindtrail</h1>
  <div id="log"></div>
  <form id="form">
    <input id="input" autocomplete="off" placeholder="Ask something..." autofocus>
    <button id="send">Ask</button>
  </form>
  <script>
    const log = document.getElementById('log');
    const form = document.getElementById('form');
    const input = document.getElementById('input');
    const send = document.getElementById('send');

    function bubble(text, cls) {
      const div = document.createElement('div');
      div.className = 'msg ' + cls;
      div.textContent = text;
      log.appendChild(div);
      log.scrollTop = log.scrollHeight;
      return div;
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      input.value = '';
      bubble(message, 'user');
      const pending = bubble('thinking...', 'assistant pending');
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
          if (data.recalled.length || data.sources.length) {
            const meta = document.createElement('div');
            meta.className = 'meta';
            if (data.recalled.length) {
              meta.innerHTML += 'Built on: ' + data.recalled.join(', ') + '<br>';
            }
            data.sources.forEach(u => {
              const a = document.createElement('a');
              a.href = u; a.target = '_blank'; a.rel = 'noopener';
              a.textContent = u;
              meta.appendChild(a);
              meta.appendChild(document.createElement('br'));
            });
            pending.appendChild(meta);
          }
        }
      } catch (err) {
        pending.classList.remove('pending');
        pending.textContent = 'Error: request failed';
      } finally {
        input.disabled = false;
        send.disabled = false;
        input.focus();
      }
    });
  </script>
</body>
</html>"""


def handle_ask(researcher: Researcher, message: str) -> dict:
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

    return {
        "answer": result.summary,
        "sources": list(result.sources),
        "recalled": [e.query for e in result.recalled],
    }


def make_handler(researcher: Researcher) -> type[BaseHTTPRequestHandler]:
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

        def do_GET(self):
            if self.path != "/":
                self.send_response(404)
                self.end_headers()
                return
            body = CHAT_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
            result = handle_ask(researcher, str(payload.get("message", "")))
            self._send_json(200, result)

    return ChatHandler


def run_chat_server(
    researcher: Researcher, port: int = 8765, open_browser: bool = True
) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(researcher))
    url = f"http://127.0.0.1:{port}"
    print(f"mindtrail chat running at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
