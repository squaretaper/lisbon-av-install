#!/usr/bin/env python3
"""
oracle_bridge.py - receives Ganchi chat replies and appends them to the breath
say_queue, so the monolith speaks each reply (breath_clock watches the queue).

Pablo's chat.js (Cloudflare Pages functions/oracle/chat.js) POSTs, fire-and-forget,
after the Anthropic reply:
    POST /oracle   header: X-Oracle-Token: <token>
    body: {"session_id":..., "visitor_msg":..., "ganchi_reply":"...", "ts":...}

Stdlib only (no pip / no network needed to run). Token-gated since it's exposed
publicly via Tailscale Funnel.
"""
import json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

QUEUE = os.path.expanduser("~/code/lisbon-av-install/breath/say_queue.jsonl")
TOKEN = os.environ.get("ORACLE_TOKEN", "")
PORT  = int(os.environ.get("ORACLE_PORT", "8791"))

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass  # quiet
    def _j(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Oracle-Token")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self): self._j(204, {})
    def do_GET(self):
        return self._j(200, {"ok": True}) if self.path.startswith("/health") else self._j(404, {"error": "not found"})
    def do_POST(self):
        if not self.path.startswith("/oracle"): return self._j(404, {"error": "not found"})
        if TOKEN and self.headers.get("X-Oracle-Token") != TOKEN: return self._j(401, {"error": "unauthorized"})
        n = int(self.headers.get("Content-Length") or 0)
        try: data = json.loads(self.rfile.read(n) or b"{}")
        except Exception: return self._j(400, {"error": "bad json"})
        reply = str(data.get("ganchi_reply") or data.get("text") or "").strip()
        if not reply: return self._j(400, {"error": "no ganchi_reply"})
        ev = {"text": reply[:600], "session_id": data.get("session_id"),
              "visitor_msg": data.get("visitor_msg"), "ts": data.get("ts") or time.time(), "source": "oracle"}
        with open(QUEUE, "a") as f: f.write(json.dumps(ev) + "\n")
        return self._j(200, {"spoken": True})

if __name__ == "__main__":
    print(f"oracle_bridge on :{PORT} -> {QUEUE}  (token {'set' if TOKEN else 'OFF'})")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
