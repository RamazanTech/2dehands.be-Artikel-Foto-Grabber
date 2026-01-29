import json
import os
import sys
import zipfile
from io import BytesIO
from http.server import BaseHTTPRequestHandler

import requests

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from _utils import (
    dedupe_in_order,
    guess_extension,
    is_allowed_image_url,
    normalize_image_url,
)

MAX_IMAGES = 20


def read_json(handler):
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def send_json(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def is_content_type_image(content_type):
    if not content_type:
        return False
    return content_type.split(";")[0].strip().lower().startswith("image/")


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            data = read_json(self)
            urls = data.get("urls", [])
            if not isinstance(urls, list) or not urls:
                return send_json(self, 400, {"error": "Geen foto's geselecteerd."})

            sanitized = []
            for url in urls:
                if not isinstance(url, str):
                    continue
                url = normalize_image_url(url)
                if not is_allowed_image_url(url):
                    continue
                sanitized.append(url)

            sanitized = dedupe_in_order(sanitized)[:MAX_IMAGES]
            if not sanitized:
                return send_json(self, 400, {"error": "Geen geldige foto's gevonden."})

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                )
            }

            buffer = BytesIO()
            added = 0
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_handle:
                for index, url in enumerate(sanitized, start=1):
                    try:
                        response = requests.get(url, headers=headers, timeout=30)
                        response.raise_for_status()
                    except requests.RequestException:
                        continue

                    content_type = response.headers.get("Content-Type", "")
                    if content_type and not is_content_type_image(content_type):
                        continue

                    ext = guess_extension(url, content_type)
                    filename = f"image_{index:03d}{ext}"
                    zip_handle.writestr(filename, response.content)
                    added += 1

            if added == 0:
                return send_json(self, 502, {"error": "Kon geen foto's downloaden."})

            buffer.seek(0)
            data = buffer.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", "attachment; filename=photos.zip")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            return send_json(self, 500, {"error": f"Server error: {exc}"})
