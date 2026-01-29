import argparse
import hashlib
import json
import mimetypes
import os
import re
from urllib.parse import urljoin, urlparse, unquote

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

    # Meta tags (Open Graph, Twitter cards)
    for meta in soup.find_all("meta"):
        content = meta.get("content")
        prop = meta.get("property") or meta.get("name") or ""
        if content and ("image" in prop.lower()):
            add_url(urls, content, base_url)

    # Image tags (including lazy-loading attributes)
    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-original", "data-lazy", "data-image"):
            add_url(urls, img.get(attr), base_url)
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            for part in srcset.split(","):
                candidate = part.strip().split(" ")[0]
                add_url(urls, candidate, base_url)

    # JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        extract_from_json(data, urls, base_url)

    # Next.js data or other embedded JSON
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

    # Regex fallback for any remaining image urls in raw html
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
    """Extract a base pattern from URL to identify similar images."""
    parsed = urlparse(url)
    path = parsed.path
    # Remove size parameters like /76x76/, /500x500/ etc
    path = re.sub(r'/\d+x\d+/', '/', path)
    # Remove common suffixes like _thumb, _small, _large
    path = re.sub(r'_(thumb|small|medium|large|xl)\.(jpg|jpeg|png|webp)', r'.\1', path, flags=re.IGNORECASE)
    return path


def score_image_url(url):
    """Score an image URL - higher is better quality."""
    score = 0
    lower = url.lower()
    
    # Prefer larger dimensions in URL
    dimensions = re.findall(r'/(\d+)x(\d+)/', lower)
    if dimensions:
        w, h = map(int, dimensions[-1])
        score += w * h
    
    # Prefer certain keywords
    if any(kw in lower for kw in ['large', 'original', 'full', 'xl', 'xxl']):
        score += 1000000
    
    # Penalize small/thumbnail keywords
    if any(kw in lower for kw in ['thumb', 'small', 'tiny', 'icon']):
        score -= 1000000
    
    # Prefer 2dehands CDN URLs with specific patterns
    if 'i.ebayimg.com' in lower or 'apollo' in lower:
        score += 500000
    if 'images.2dehands.com' in lower:
        score += 400000

    rule_match = re.search(r"\$_(\d+)", lower)
    if rule_match:
        score += int(rule_match.group(1)) * 1000
    
    return score


def filter_candidates(urls):
    """Filter and deduplicate image URLs, keeping only the best quality versions."""
    # First pass: apply blacklist
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
    
    # Group by base pattern to find duplicates
    pattern_groups = {}
    for url in filtered:
        pattern = get_url_base_pattern(url)
        if pattern not in pattern_groups:
            pattern_groups[pattern] = []
        pattern_groups[pattern].append(url)
    
    # Keep only the best URL from each group
    best_urls = []
    for pattern, group in pattern_groups.items():
        if len(group) == 1:
            best_urls.append(group[0])
        else:
            # Sort by score (highest first) and take the best
            sorted_group = sorted(group, key=score_image_url, reverse=True)
            best_urls.append(sorted_group[0])
    
    return dedupe_in_order(best_urls)


def safe_slug_from_url(url):
    parsed = urlparse(url)
    slug = parsed.path.strip("/").split("/")[-1] or "listing"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", slug)
    return slug.strip("-") or "listing"


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


def build_filename(url, index, content_type):
    parsed = urlparse(url)
    base = unquote(os.path.basename(parsed.path))
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    ext = os.path.splitext(base)[1].lower()
    if not ext or ext not in IMAGE_EXTENSIONS:
        ext = guess_extension(url, content_type)
        base = f"image_{index:03d}{ext}"
    else:
        base = f"{index:03d}_{base}"
    return base


def unique_path(filepath):
    if not os.path.exists(filepath):
        return filepath
    root, ext = os.path.splitext(filepath)
    counter = 1
    while True:
        candidate = f"{root}_{counter}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def is_content_type_image(content_type):
    if not content_type:
        return False
    return content_type.split(";")[0].strip().lower().startswith("image/")


def download_images(urls, output_dir, max_images=None):
    os.makedirs(output_dir, exist_ok=True)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }
    seen_hashes = set()
    saved_files = []
    for index, url in enumerate(urls, start=1):
        if max_images and len(saved_files) >= max_images:
            break
        try:
            response = requests.get(url, headers=headers, timeout=30, stream=True)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"Skip (request failed): {url} ({exc})")
            continue

        content_type = response.headers.get("Content-Type", "")
        if content_type and not is_content_type_image(content_type):
            print(f"Skip (not image): {url} ({content_type})")
            continue
        if not content_type and not is_image_url(url):
            print(f"Skip (unknown type): {url}")
            continue

        filename = build_filename(url, index, response.headers.get("Content-Type"))
        filepath = unique_path(os.path.join(output_dir, filename))
        temp_path = unique_path(f"{filepath}.part")

        hasher = hashlib.sha256()
        bytes_written = 0
        with open(temp_path, "wb") as file_handle:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    file_handle.write(chunk)
                    hasher.update(chunk)
                    bytes_written += len(chunk)

        if bytes_written == 0:
            os.remove(temp_path)
            print(f"Skip (empty): {url}")
            continue
        
        # Skip very small images (likely icons/thumbnails)
        if bytes_written < 5000:  # Less than 5KB
            os.remove(temp_path)
            print(f"Skip (too small: {bytes_written} bytes): {url}")
            continue

        digest = hasher.hexdigest()
        if digest in seen_hashes:
            os.remove(temp_path)
            print(f"Skip (duplicate): {url}")
            continue

        seen_hashes.add(digest)
        os.replace(temp_path, filepath)
        saved_files.append(filepath)
        print(f"Saved: {filepath}")

    return saved_files


def main():
    parser = argparse.ArgumentParser(
        description="Grab photos from a 2dehands listing URL."
    )
    parser.add_argument("url", help="2dehands listing URL")
    parser.add_argument(
        "--out",
        default=None,
        help="Output folder (default: downloads/<listing-slug>)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="Max number of images to download",
    )
    args = parser.parse_args()

    html = fetch_html(args.url)
    base_url = f"{urlparse(args.url).scheme}://{urlparse(args.url).netloc}"
    raw_urls = extract_image_urls(html, base_url)
    candidates = filter_candidates(dedupe_in_order(raw_urls))

    if not candidates:
        print("No images found.")
        return

    slug = safe_slug_from_url(args.url)
    output_dir = args.out or os.path.join("downloads", slug)
    print(f"Found {len(candidates)} image candidates.")
    saved_files = download_images(candidates, output_dir, max_images=args.max)
    print(f"Downloaded {len(saved_files)} images to {output_dir}")


if __name__ == "__main__":
    main()
