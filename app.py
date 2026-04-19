from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from lora_reconstruction import LoRaTelemetryReconstructor, demo_packets


ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"
reconstructor = LoRaTelemetryReconstructor()


class TelemetryHandler(BaseHTTPRequestHandler):
    server_version = "LoRaTelemetryDemo/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._serve_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self._serve_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/demo-stream":
            payload = [reconstructor.ingest(packet) for packet in demo_packets()]
            self._write_json(HTTPStatus.OK, {"items": payload})
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "Route not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/ingest":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Route not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length).decode("utf-8") if content_length else ""
        try:
            body = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "Body must be valid JSON"})
            return

        packet = body.get("packet")
        if not isinstance(packet, str) or not packet.strip():
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "Field 'packet' must be a non-empty string"})
            return

        payload = reconstructor.ingest(packet)
        self._write_json(HTTPStatus.OK, payload)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Static file not found"})
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write_json(self, status: HTTPStatus, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    host = "0.0.0.0"
    port = int(os.environ.get('PORT', 8000))
    server = ThreadingHTTPServer((host, port), TelemetryHandler)
    print(f"Serving LoRa telemetry demo at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
