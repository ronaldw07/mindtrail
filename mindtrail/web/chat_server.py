"""Local chat interface over the researcher.

Built on stdlib http.server rather than a web framework: a single local
user does not need routing tables, middleware, or async handling, and it
avoids adding another dependency to an already torch-adjacent install.

Request logic lives in web/api.py as pure functions; this module is only
the HTTP plumbing around them.
"""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from mindtrail.ingest.researcher import Researcher
from mindtrail.llm import LLMClient
from mindtrail.memory.store import MemoryStore
from mindtrail.organize.conversations import ConversationStore
from mindtrail.organize.profile import ProfileStore
from mindtrail.organize.projects import ProjectStore
from mindtrail.organize.roadmaps import RoadmapNodeStore, RoadmapStore
from mindtrail.organize.trash import Trash
from mindtrail.web import api
from mindtrail.web.chat_ui import CHAT_HTML

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class Deps:
    """Everything the handlers need, passed as one object.

    Threading a growing list of stores through every handler signature
    would be noisier than grouping them once here.
    """

    def __init__(
        self,
        researcher: Researcher,
        store: MemoryStore,
        projects: ProjectStore,
        chats: ConversationStore,
        llm: LLMClient,
        topic_extractor=None,
        profile: ProfileStore | None = None,
        roadmaps: RoadmapStore | None = None,
        roadmap_nodes: RoadmapNodeStore | None = None,
    ):
        self.researcher = researcher
        self.store = store
        self.projects = projects
        self.chats = chats
        self.llm = llm
        self.topic_extractor = topic_extractor
        self.trash = Trash()
        self.profile = profile or ProfileStore()
        self.roadmaps = roadmaps or RoadmapStore()
        self.roadmap_nodes = roadmap_nodes or RoadmapNodeStore()


def make_handler(deps: Deps) -> type[BaseHTTPRequestHandler]:
    class ChatHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # keep the terminal quiet during a chat session

        # --- helpers ---

        def _json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> bytes:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_UPLOAD_BYTES:
                return b""
            return self.rfile.read(length) if length else b""

        def _json_body(self) -> dict | None:
            try:
                return json.loads(self._body() or b"{}")
            except json.JSONDecodeError:
                return None

        def _tail(self, prefix: str) -> str:
            """The id segment after a known path prefix."""
            return unquote(urlparse(self.path).path[len(prefix) :])

        def _not_found(self) -> None:
            self.send_response(404)
            self.end_headers()

        # --- routes ---

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                body = CHAT_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/sidebar":
                self._json(api.handle_sidebar(deps.projects, deps.chats))
            elif path.startswith("/api/conversations/"):
                self._json(
                    api.handle_conversation_entries(
                        deps.store, deps.chats, self._tail("/api/conversations/")
                    )
                )
            elif path.startswith("/api/roadmap/"):
                self._json(
                    api.handle_get_roadmap(
                        deps.roadmaps, deps.roadmap_nodes, self._tail("/api/roadmap/")
                    )
                )
            elif path == "/api/profile":
                self._json(api.handle_get_profile(deps.profile))
            elif path.startswith("/api/projects/"):
                params = parse_qs(urlparse(self.path).query)
                self._json(
                    api.handle_project_detail(
                        deps.store,
                        deps.chats,
                        deps.projects,
                        deps.llm,
                        self._tail("/api/projects/"),
                        params.get("refresh", [""])[0] == "1",
                        params.get("background", [""])[0] != "1",
                        deps.profile,
                    )
                )
            else:
                self._not_found()

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/ask":
                body = self._json_body()
                if body is None:
                    self._json({"error": "malformed request body"}, 400)
                    return
                self._json(
                    api.handle_ask(
                        deps.researcher,
                        deps.store,
                        deps.chats,
                        str(body.get("message", "")),
                        str(body.get("conversation_id", "") or ""),
                        body.get("project_id") or None,
                        deps.projects,
                        deps.profile,
                    )
                )
            elif path.startswith("/api/roadmap/") and path.endswith("/generate"):
                body = self._json_body() or {}
                project_id = path[len("/api/roadmap/") : -len("/generate")]
                self._json(
                    api.handle_generate_roadmap(
                        deps.store,
                        deps.chats,
                        deps.projects,
                        deps.roadmaps,
                        deps.roadmap_nodes,
                        deps.llm,
                        deps.profile,
                        project_id,
                        str(body.get("goal", "")),
                    )
                )
            elif path.startswith("/api/roadmap-node/"):
                body = self._json_body() or {}
                self._json(
                    api.handle_add_node(
                        deps.roadmap_nodes, self._tail("/api/roadmap-node/"), body
                    )
                )
            elif path == "/api/profile":
                body = self._json_body() or {}
                self._json(api.handle_save_profile(deps.profile, str(body.get("content", ""))))
            elif path == "/api/profile/draft":
                self._json(api.handle_draft_profile(deps.store, deps.llm))
            elif path == "/api/projects":
                body = self._json_body()
                if body is None:
                    self._json({"error": "malformed request body"}, 400)
                    return
                self._json(api.handle_create_project(deps.projects, str(body.get("name", ""))))
            elif path.startswith("/api/undo-delete/"):
                self._json(
                    api.handle_undo_delete(
                        deps.store,
                        deps.chats,
                        deps.trash,
                        self._tail("/api/undo-delete/"),
                    )
                )
            elif path == "/api/transcribe":
                self._json(api.handle_transcribe(deps.llm, self._body()))
            elif path == "/api/upload":
                params = parse_qs(parsed.query)
                self._json(
                    api.handle_upload(
                        deps.store,
                        deps.chats,
                        deps.llm,
                        params.get("filename", [""])[0],
                        self._body(),
                        params.get("conversation_id", [""])[0],
                        deps.topic_extractor,
                    )
                )
            else:
                self._not_found()

        def do_PATCH(self):
            path = urlparse(self.path).path
            body = self._json_body()
            if body is None:
                self._json({"error": "malformed request body"}, 400)
                return

            if path.startswith("/api/conversations/"):
                self._json(
                    api.handle_update_conversation(
                        deps.chats, self._tail("/api/conversations/"), body
                    )
                )
            elif path.startswith("/api/projects/"):
                self._json(
                    api.handle_update_project(
                        deps.projects, self._tail("/api/projects/"), body
                    )
                )
            elif path.startswith("/api/roadmap-node/"):
                self._json(
                    api.handle_update_node(
                        deps.roadmap_nodes, self._tail("/api/roadmap-node/"), body
                    )
                )
            else:
                self._not_found()

        def do_DELETE(self):
            path = urlparse(self.path).path
            if path.startswith("/api/conversations/"):
                self._json(
                    api.handle_delete_conversation(
                        deps.store,
                        deps.chats,
                        self._tail("/api/conversations/"),
                        deps.trash,
                    )
                )
            elif path.startswith("/api/roadmap-node/"):
                self._json(
                    api.handle_delete_node(
                        deps.roadmap_nodes, self._tail("/api/roadmap-node/")
                    )
                )
            elif path.startswith("/api/projects/"):
                self._json(
                    api.handle_delete_project(deps.projects, self._tail("/api/projects/"))
                )
            else:
                self._not_found()

    return ChatHandler


def run_chat_server(
    deps: Deps,
    port: int = 8765,
    open_browser: bool = True,
    host: str = "127.0.0.1",
) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(deps))
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
