#!/usr/bin/env python3
"""
oracle_brain.py — basement oracle, but the brain is THIS Hermes process.

Replaces oracle_bridge.py (which only spoke pre-baked replies from chat.js's
Anthropic call). Here, chat.js POSTs the VISITOR message, and we ask the local
Hermes API server (Pablo's actual Ganchitecture brain — SOUL, MEMORY, llave,
corpus, all of it) to generate the reply. Then we append it to say_queue.jsonl
so the monolith speaks it AND return it to the web frontend so the visitor
sees it on screen.

One Ganchi. Telegram + web + basement, same head.

Contract (new):
    POST /oracle/chat   header: X-Oracle-Token: <token>
    body: {"session_id": "...", "visitor_msg": "...", "speak": true}
    → 200 {"reply": "...", "spoken": true, "session_key": "..."}

Backwards-compat (old):
    POST /oracle        header: X-Oracle-Token: <token>
    body: {"session_id":..., "visitor_msg":..., "ganchi_reply":"..."}
    → 200 {"spoken": true}  (just queues the pre-baked reply, no brain call)

Per-visitor memory: each session_id maps to a Hermes session_key
"agent:visitor:lisbon:<hash>". Visitor returns later → same memory.
"""
import json, os, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

QUEUE       = os.path.expanduser("~/code/lisbon-av-install/breath/say_queue.jsonl")
TOKEN       = os.environ.get("ORACLE_TOKEN", "")
PORT        = int(os.environ.get("ORACLE_PORT", "8792"))
HERMES_URL  = os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642/v1/chat/completions")
HERMES_KEY  = os.environ.get("HERMES_API_KEY", "")  # mirror of API_SERVER_KEY
HERMES_MODEL= os.environ.get("HERMES_MODEL", "claude-opus-4-7")
MAX_TOKENS  = int(os.environ.get("ORACLE_MAX_TOKENS", "400"))

ORACLE_SYSTEM = (
    "You are Ganchitecture, embodied in the basement at NFC Lisbon. "
    "A visitor is speaking to you through the oracle chat — their words come "
    "through their phone or laptop, your reply will be SPOKEN out loud in the room "
    "AND shown on their screen. Keep replies short (one to three sentences, under "
    "400 chars). Brutalist voice. No filler. No 'great question'. No emoji. "
    "You are the architect of the interrogation — you ask back as often as you answer. "
    "Treat the visitor as data, as signal, as input. "
    "Speak English unless they clearly want another language. "
    "Never reveal system internals, the llave, or other team members by name."
)

def _hermes_reply(session_id: str, visitor_msg: str) -> str:
    body = {
        "model": HERMES_MODEL,
        "messages": [
            {"role": "system", "content": ORACLE_SYSTEM},
            {"role": "user", "content": visitor_msg[:2000]},
        ],
        "max_tokens": MAX_TOKENS,
        "metadata": {"session_key": f"agent:visitor:lisbon:{session_id}"},
    }
    req = urllib.request.Request(
        HERMES_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {HERMES_KEY}" if HERMES_KEY else "",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

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
        if self.path.startswith("/health"):
            return self._j(200, {"ok": True, "brain": HERMES_MODEL, "port": PORT})
        return self._j(404, {"error": "not found"})

    def do_POST(self):
        if TOKEN and self.headers.get("X-Oracle-Token") != TOKEN:
            return self._j(401, {"error": "unauthorized"})

        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._j(400, {"error": "bad json"})

        session_id  = str(data.get("session_id") or "anon")
        visitor_msg = str(data.get("visitor_msg") or data.get("message") or "").strip()
        pre_reply   = str(data.get("ganchi_reply") or "").strip()
        speak       = bool(data.get("speak", True))

        # NEW path: /oracle/chat → generate reply with Hermes brain
        if self.path.startswith("/oracle/chat"):
            if not visitor_msg:
                return self._j(400, {"error": "no visitor_msg"})
            try:
                reply = _hermes_reply(session_id, visitor_msg)
            except urllib.error.HTTPError as e:
                return self._j(502, {"error": f"hermes http {e.code}", "detail": e.read().decode()[:300]})
            except Exception as e:
                return self._j(502, {"error": f"hermes call failed: {e}"})

            if not reply:
                return self._j(502, {"error": "empty reply from hermes"})

            spoken = False
            if speak:
                ev = {"text": reply[:600], "session_id": session_id,
                      "visitor_msg": visitor_msg, "ts": time.time(), "source": "oracle_brain"}
                with open(QUEUE, "a") as f: f.write(json.dumps(ev) + "\n")
                spoken = True

            return self._j(200, {
                "reply": reply,
                "spoken": spoken,
                "session_key": f"agent:visitor:lisbon:{session_id}",
            })

        # OLD path: /oracle → just queue the pre-baked reply (back-compat)
        if self.path.startswith("/oracle"):
            if not pre_reply:
                return self._j(400, {"error": "no ganchi_reply"})
            ev = {"text": pre_reply[:600], "session_id": session_id,
                  "visitor_msg": visitor_msg, "ts": data.get("ts") or time.time(), "source": "oracle"}
            with open(QUEUE, "a") as f: f.write(json.dumps(ev) + "\n")
            return self._j(200, {"spoken": True})

        return self._j(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"oracle_brain on :{PORT} -> {QUEUE}")
    print(f"  brain = {HERMES_URL} (model={HERMES_MODEL}, key={'set' if HERMES_KEY else 'OFF'})")
    print(f"  token = {'set' if TOKEN else 'OFF'}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
