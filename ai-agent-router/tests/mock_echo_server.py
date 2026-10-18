"""Tiny mock agent for tests: echoes the JSON it receives.  python tests/mock_echo_server.py 9001"""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        out = json.dumps({"response": f"echo[{body.get('target')}] from {body.get('from_agent')}: {body.get('message')} | ctx={json.dumps(body.get('context'))} | auth={self.headers.get('Authorization')}"}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 9001), H).serve_forever()
