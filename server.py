#!/usr/bin/env python3
"""Small stdlib web server for the Atalanta demo app."""

import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import atalanta


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
MAX_BODY_BYTES = 1_000_000


class AtalantaRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True})
            return
        self.serve_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/analyze":
            self.send_json({"error": "not found"}, status=404)
            return

        try:
            payload = self.read_json_body()
            if isinstance(payload, dict) and "spec" in payload:
                spec_payload = payload["spec"]
            else:
                spec_payload = payload
            if not isinstance(spec_payload, dict):
                raise ValueError("request body must be a JSON object spec, or {'spec': spec}")

            spec = atalanta.Spec.from_data(spec_payload, "browser_input")
            analysis = atalanta.analyze_spec_data(spec, "browser input")

            self.send_json(
                {
                    "analysis": analysis.to_json(),
                    "lean": analysis.original_lean,
                }
            )
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def serve_static(self, request_path):
        relative = unquote(request_path).lstrip("/") or "index.html"
        candidate = (WEB_ROOT / relative).resolve()
        if not str(candidate).startswith(str(WEB_ROOT.resolve())):
            self.send_error(403)
            return
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.exists() or not candidate.is_file():
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        print(f"{self.client_address[0]} - {format % args}")


def parse_args():
    parser = argparse.ArgumentParser(description="Serve the Atalanta web app and Lean analysis API.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    return parser.parse_args()


def main():
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AtalantaRequestHandler)
    print(f"Atalanta web app running at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
