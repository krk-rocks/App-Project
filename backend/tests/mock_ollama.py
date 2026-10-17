"""A stand-in for an Ollama server, so the LLM client can be tested end to end without a model.

It speaks just enough of the real API: GET /api/tags and POST /api/chat. Tests choose how it behaves by setting
`chat` to a function(body) -> (status, payload) and can inspect every request it received.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def reply(content_obj=None, raw=None):
    """A normal /api/chat answer carrying `content_obj` as JSON text (or `raw` text as-is)."""
    text = raw if raw is not None else json.dumps(content_obj)
    return 200, {"model": "epic-tn-planner", "message": {"role": "assistant", "content": text}, "done": True}


class MockOllama:
    def __init__(self, models=("epic-tn-planner:latest",)):
        self.models, self.requests, self.tags_hits = list(models), [], 0
        self.chat = lambda body: reply({"intro": "x", "days": []})
        self.delay = 0.0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/tags":
                    outer.tags_hits += 1
                    self._send(200, {"models": [{"name": m} for m in outer.models]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                outer.requests.append(body)
                if outer.delay:
                    time.sleep(outer.delay)
                status, payload = outer.chat(body)
                try:
                    self._send(status, payload)
                except ConnectionError:
                    pass                                   # the client gave up waiting: fine

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
