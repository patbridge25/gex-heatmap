"""Tiny local server: serves index.html and /api/gex?symbol=SPY using calc_gex.compute_gex.

Run:   python server.py
Open:  http://127.0.0.1:8000
Phone on the same Wi-Fi:  python server.py --lan   then open http://<this PC's IP>:8000
"""
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from calc_gex import compute_gex

HERE = Path(__file__).parent
PORT = 8000
CACHE_SECONDS = 60
# Cboe uses a leading underscore for cash indexes
ALIAS = {"SPX": "_SPX", "NDX": "_NDX", "RUT": "_RUT", "VIX": "_VIX", "XSP": "_XSP"}
cache = {}


def gex_for(sym):
    hit = cache.get(sym)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    d = compute_gex(ALIAS.get(sym, sym))
    d["symbol"] = sym
    cache[sym] = (time.time(), d)
    return d


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self.send(200, (HERE / "index.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
        elif u.path == "/api/gex":
            sym = (parse_qs(u.query).get("symbol", [""])[0]).upper().strip()
            if not re.fullmatch(r"[A-Z.\-]{1,6}", sym):
                return self.send(400, json.dumps({"error": "invalid ticker"}), "application/json")
            try:
                self.send(200, json.dumps(gex_for(sym)), "application/json")
            except Exception as e:
                print("error for", sym, "->", repr(e))
                self.send(502, json.dumps({"error": f"no data for {sym} ({type(e).__name__})"}), "application/json")
        else:
            self.send(404, "not found", "text/plain")

    def log_message(self, fmt, *args):
        print(self.address_string(), fmt % args)


if __name__ == "__main__":
    host = "0.0.0.0" if "--lan" in sys.argv else "127.0.0.1"
    print(f"Open http://127.0.0.1:{PORT}   (Ctrl+C to stop)")
    ThreadingHTTPServer((host, PORT), Handler).serve_forever()
