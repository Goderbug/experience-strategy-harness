#!/usr/bin/env python3
"""View project Harness records on loopback, or export a self-contained HTML snapshot."""
import argparse
import base64
from dataclasses import dataclass
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
import webbrowser

from status_model import build_snapshot


ASSETS = Path(__file__).resolve().parents[1] / "dashboard"
INTERVAL_MS = 5000


@dataclass
class Dashboard:
    template: str
    css: str
    script: str

    @classmethod
    def load(cls):
        return cls(*[(ASSETS / name).read_text(encoding="utf-8")
                     for name in ("status.html", "status.css", "status.js")])

    def policy(self, live):
        digest = base64.b64encode(hashlib.sha256(self.script.encode()).digest()).decode()
        connection = "'self'" if live else "'none'"
        return ("default-src 'none'; base-uri 'none'; form-action 'none'; "
                f"script-src 'sha256-{digest}'; style-src 'unsafe-inline'; "
                f"img-src data:; connect-src {connection}")

    def render(self, snapshot, live=False):
        boot = json.dumps({"mode": "live" if live else "snapshot", "interval_ms": INTERVAL_MS,
                           "snapshot": snapshot}, ensure_ascii=False, separators=(",", ":"))
        # JSON script elements are parsed as raw HTML text, before JavaScript sees the data.
        boot = boot.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
        parts = {"STATUS_BOOT": boot, "STATUS_CSS": self.css, "STATUS_JS": self.script}
        html = self.template.replace("<head>", '<head><meta http-equiv="Content-Security-Policy" content="'
                                     + self.policy(live) + '">', 1)
        html = re.sub(r"\{\{(STATUS_BOOT|STATUS_CSS|STATUS_JS)\}\}", lambda match: parts[match[1]], html)
        return html.encode("utf-8")


class StatusFeed:
    def __init__(self, roots):
        self.roots = roots
        self.lock = threading.Lock()
        self.last_read = 0.0
        self.snapshot = None

    def read(self, verify=False):
        # Multiple tabs share one read. Polling only queries recorded state; a manual refresh checks files.
        with self.lock:
            if verify or self.snapshot is None or time.monotonic() - self.last_read >= 1:
                self.snapshot = build_snapshot(self.roots, verify_files=verify)
                self.last_read = time.monotonic()
            return self.snapshot


def handler_for(page, feed):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, mime, content=b"", policy=None):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            if policy:
                self.send_header("Content-Security-Policy", policy + "; frame-ancestors 'none'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(content)

        def do_GET(self):
            try:
                self.send_view()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                # An unreadable project is normally represented in the model. A whole-feed failure
                # should still return a bounded response so clients can retain their last good view.
                self.send(503, "text/plain; charset=utf-8", b"Status is temporarily unavailable.")

        def send_view(self):
            port = self.server.server_address[1]
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in allowed:
                return self.send(403, "text/plain", b"Local host required.")
            if self.path == "/":
                data = page.render(feed.read(), live=True)
                return self.send(200, "text/html; charset=utf-8", data, page.policy(True))
            if self.path not in ("/api/status", "/api/status?verify=1"):
                return self.send(404, "text/plain", b"Not found.")
            origin = self.headers.get("Origin")
            if ((origin is not None and origin != "http://" + self.headers["Host"])
                    or self.headers.get("Sec-Fetch-Site") == "cross-site"):
                return self.send(403, "text/plain", b"Same-origin request required.")
            snapshot = feed.read(verify=urlsplit(self.path).query == "verify=1")
            payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            return self.send(200, "application/json; charset=utf-8", payload)

        do_HEAD = do_GET

    return Handler


def export_snapshot(target, page, roots):
    target = target.expanduser().absolute()
    if ".experience-strategy" in target.resolve().parts:
        raise ValueError("Choose an HTML destination outside the Harness state directory.")
    if target.exists() or target.is_symlink():
        raise FileExistsError("Choose a new output file: " + str(target))
    data = page.render(build_snapshot(roots, verify_files=True))
    # Publish the complete private file atomically without replacing an existing snapshot.
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".harness-status-") as output:
        output.write(data)
        output.flush()
        os.link(output.name, target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", type=Path, help="Project root (repeat for multiple projects; defaults to cwd).")
    parser.add_argument("--port", default=0, type=int, help="Loopback port; default 0 picks an available port.")
    parser.add_argument("--export", type=Path, metavar="FILE", help="Write a new offline HTML snapshot and exit.")
    parser.add_argument("--open", action="store_true", help="Open the live view in the default browser.")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535.")
    if args.export and (args.open or args.port):
        parser.error("Use --export alone or choose live server options.")
    roots = list(dict.fromkeys(path.expanduser().absolute() for path in args.root or [Path.cwd()]))
    page = Dashboard.load()
    if args.export:
        print(export_snapshot(args.export, page, roots))
        return
    feed = StatusFeed(roots)
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(page, feed)) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(url, flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit(str(error))
