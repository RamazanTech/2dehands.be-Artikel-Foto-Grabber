import json
import mimetypes
import os
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
PREFERRED_2DEHANDS_RULE = 86
URL_RE = re.compile(
    r"(https?://[^\"'\s)]+?\.(?:jpg|jpeg|png|webp|gif|bmp)(?:\?[^\"'\s)]*)?)",
    re.IGNORECASE,
)

BLACKLIST_SUBSTRINGS = (
    "sprite",
    "favicon",
    "icon",
    "logo",
    "tracking",
    "analytics",
    "placeholder",
    ".html",
    ".htm",
    "thumb",
    "thumbnail",
    "/76x76/",
    "/82x82/",
    "/134x134/",
    "avatar",
    "profile",
)

ALLOWED_LISTING_HOSTS = ("2dehands.be",)
ALLOWED_IMAGE_HOSTS = ("images.2dehands.com", "img.2dehands.com")


def normalize_input_url(raw_url):
    url = (raw_url or "").strip()
    if not url:
        return ""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"
    return url


def is_allowed_listing_url(url):
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    return parsed.scheme in ("http", "https") and host.endswith(ALLOWED_LISTING_HOSTS)


def is_allowed_image_url(url):
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    return parsed.scheme in ("http", "https") and host.endswith(ALLOWED_IMAGE_HOSTS)


def fetch_html(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def is_image_url(url):
    if not url or not isinstance(url, str):
        return False
    lower = url.lower()
    if lower.startswith("data:"):
        return False
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in IMAGE_EXTENSIONS)


def is_known_image_endpoint(url):
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if "images.2dehands.com" in host or "img.2dehands.com" in host:
        return True
    if "/listing-twh-p/images/" in path:
        return True
    return False


def normalize_image_url(url):
    if not url or not isinstance(url, str):
        return url
    lower = url.lower()
    if "images.2dehands.com" in lower and "rule=" in lower:
        def repl(match):
            value = int(match.group(2))
            return f"{match.group(1)}{max(value, PREFERRED_2DEHANDS_RULE)}"

        return re.sub(r"(\$_)(\d+)", repl, url)
    return url


def normalize_url(url, base_url):
    if not url:
        return None
    url = url.strip().replace("\\/", "/")
    if url.startswith("//"):
        url = f"https:{url}"
    if url.startswith("/"):
        url = urljoin(base_url, url)
    if not url.startswith("http"):
        return None
    return url


def add_url(urls, url, base_url):
    if not url:
        return
    if isinstance(url, list):
        for item in url:
            add_url(urls, item, base_url)
        return
    if isinstance(url, dict):
        for key in ("url", "contentUrl", "src", "image", "images", "thumbnailUrl"):
            if key in url:
                add_url(urls, url.get(key), base_url)
        return
    if isinstance(url, str):
        normalized = normalize_url(url, base_url)
        if normalized:
            urls.append(normalized)


def extract_from_json(obj, urls, base_url):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ("image", "images", "thumbnailUrl", "contentUrl", "photo"):
                add_url(urls, value, base_url)
            extract_from_json(value, urls, base_url)
    elif isinstance(obj, list):
        for item in obj:
            extract_from_json(item, urls, base_url)
    elif isinstance(obj, str):
        if obj.startswith("http") or obj.startswith("//") or obj.startswith("/"):
            add_url(urls, obj, base_url)


def extract_image_urls(html, base_url):
    urls = []
    soup = BeautifulSoup(html, "html.parser")

    for meta in soup.find_all("meta"):
        content = meta.get("content")
        prop = meta.get("property") or meta.get("name") or ""
        if content and ("image" in prop.lower()):
            add_url(urls, content, base_url)

    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-original", "data-lazy", "data-image"):
            add_url(urls, img.get(attr), base_url)
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            for part in srcset.split(","):
                candidate = part.strip().split(" ")[0]
                add_url(urls, candidate, base_url)

    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        extract_from_json(data, urls, base_url)

    for script in soup.find_all("script"):
        if script.get("type") not in (None, "application/json"):
            continue
        if not script.string:
            continue
        text = script.string.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            extract_from_json(data, urls, base_url)

    for match in URL_RE.findall(html):
        add_url(urls, match, base_url)

    return urls


def dedupe_in_order(items):
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def get_url_base_pattern(url):
    parsed = urlparse(url)
    path = parsed.path
    path = re.sub(r"/\\d+x\\d+/", "/", path)
    path = re.sub(
        r"_(thumb|small|medium|large|xl)\\.(jpg|jpeg|png|webp)",
        r".\\1",
        path,
        flags=re.IGNORECASE,
    )
    return path


def score_image_url(url):
    score = 0
    lower = url.lower()

    dimensions = re.findall(r"/(\\d+)x(\\d+)/", lower)
    if dimensions:
        w, h = map(int, dimensions[-1])
        score += w * h

    if any(kw in lower for kw in ["large", "original", "full", "xl", "xxl"]):
        score += 1000000

    if any(kw in lower for kw in ["thumb", "small", "tiny", "icon"]):
        score -= 1000000

    if "images.2dehands.com" in lower:
        score += 400000

    rule_match = re.search(r"\\$_(\\d+)", lower)
    if rule_match:
        score += int(rule_match.group(1)) * 1000

    return score


def filter_candidates(urls):
    filtered = []
    for url in urls:
        lower = url.lower()
        if any(word in lower for word in BLACKLIST_SUBSTRINGS):
            continue
        if is_image_url(url) or is_known_image_endpoint(url):
            filtered.append(normalize_image_url(url))

    if not filtered:
        filtered = [u for u in urls if is_image_url(u) or is_known_image_endpoint(u)]

    if not filtered:
        return []

    pattern_groups = {}
    for url in filtered:
        pattern = get_url_base_pattern(url)
        if pattern not in pattern_groups:
            pattern_groups[pattern] = []
        pattern_groups[pattern].append(url)

    best_urls = []
    for group in pattern_groups.values():
        if len(group) == 1:
            best_urls.append(group[0])
        else:
            sorted_group = sorted(group, key=score_image_url, reverse=True)
            best_urls.append(sorted_group[0])

    return dedupe_in_order(best_urls)


def guess_extension(url, content_type):
    path_ext = os.path.splitext(urlparse(url).path)[1].lower()
    if path_ext in IMAGE_EXTENSIONS:
        return path_ext
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext == ".jpe":
            ext = ".jpg"
        if ext:
            return ext
    return ".jpg"
