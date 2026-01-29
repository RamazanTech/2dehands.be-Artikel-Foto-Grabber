import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from _utils import (
    dedupe_in_order,
    extract_image_urls,
    fetch_html,
    filter_candidates,
    is_allowed_listing_url,
    normalize_input_url,
)


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


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        data = read_json(self)
        url = normalize_input_url(data.get("url", ""))
        if not url or not is_allowed_listing_url(url):
            return send_json(self, 400, {"error": "Ongeldige of niet-toegestane URL."})

        try:
            html = fetch_html(url)
        except Exception as exc:
            return send_json(self, 500, {"error": f"Kon de pagina niet ophalen: {exc}"})

        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        raw_urls = extract_image_urls(html, base_url)
        candidates = filter_candidates(dedupe_in_order(raw_urls))

        if not candidates:
            return send_json(self, 404, {"error": "Geen foto's gevonden."})

        images = [{"url": img_url, "index": idx} for idx, img_url in enumerate(candidates)]
        return send_json(self, 200, {"images": images, "total": len(images)})
