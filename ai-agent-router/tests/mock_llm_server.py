"""Mock OpenAI-compatible + Anthropic Messages server on :9003 (records last request)."""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
LAST = {}
class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        out = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    def do_GET(self):
        if self.path == "/last": return self._send(200, LAST)
        self._send(404, {"error": "nf"})
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length", 0)))
        body = json.loads(raw or b"{}")
        LAST.clear(); LAST.update(path=self.path, headers=dict(self.headers), body=body)
        if self.path.endswith("/chat/completions"):
            if self.headers.get("Authorization") != "Bearer sk-mock-123456789012345678":
                return self._send(401, {"error": {"message": "bad key"}})
            user = [m for m in body["messages"] if m["role"] == "user"][0]["content"]
            return self._send(200, {"choices": [{"message": {"role": "assistant",
                    "content": f"mock-openai[{body['model']}] got: {user}"}}]})
        if self.path == "/v1/messages":
            if self.headers.get("x-api-key") != "sk-ant-mock-1234567890123" or self.headers.get("anthropic-version") != "2023-06-01":
                return self._send(401, {"error": {"message": "bad anthropic auth"}})
            if "max_tokens" not in body: return self._send(400, {"error": "max_tokens required"})
            return self._send(200, {"content": [{"type": "text", "text": f"mock-claude[{body['model']}] got: {body['messages'][0]['content']}"}]})
        self._send(404, {"error": "nf"})
    def log_message(self, *a): pass
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 9003), H).serve_forever()
