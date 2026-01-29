import os
import re
import zipfile
from io import BytesIO
from urllib.parse import urlparse

from flask import Flask, abort, render_template, request, send_file, send_from_directory, session, url_for

from grab_2dehands_photos import (
    IMAGE_EXTENSIONS,
    dedupe_in_order,
    download_images,
    extract_image_urls,
    fetch_html,
    filter_candidates,
    safe_slug_from_url,
)


app = Flask(__name__)
app.secret_key = os.urandom(24)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def normalize_input_url(raw_url):
    url = (raw_url or "").strip()
    if not url:
        return ""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"
    return url


def parse_max(raw_value):
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        return None
    return value if value > 0 else None


def is_safe_slug(slug):
    return bool(slug and SLUG_RE.match(slug))


def clear_download_dir(directory):
    if not os.path.isdir(directory):
        return
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
            continue
        os.remove(path)


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/grab")
def grab():
    raw_url = request.form.get("url", "")
    url = normalize_input_url(raw_url)

    if not url:
        return render_template("index.html", error="Vul een geldige URL in.")

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return render_template("index.html", error="Ongeldige URL.")

    try:
        html = fetch_html(url)
    except Exception as exc:
        return render_template(
            "index.html",
            error=f"Kon de pagina niet ophalen: {exc}",
            url=url,
        )

    base_url = f"{parsed.scheme}://{parsed.netloc}"
    raw_urls = extract_image_urls(html, base_url)
    candidates = filter_candidates(dedupe_in_order(raw_urls))

    if not candidates:
        return render_template(
            "index.html",
            error="Geen foto's gevonden op deze pagina.",
            url=url,
        )

    slug = safe_slug_from_url(url)
    
    # Store candidates in session for later download
    session['candidates'] = candidates
    session['slug'] = slug
    session['listing_url'] = url

    images = []
    for idx, img_url in enumerate(candidates):
        images.append({
            "index": idx,
            "url": img_url,
        })

    return render_template(
        "index.html",
        url=url,
        total_candidates=len(candidates),
        images=images,
        slug=slug,
    )


@app.post("/download")
def download():
    selected_indices = request.form.getlist("selected")
    candidates = session.get('candidates', [])
    slug = session.get('slug')
    listing_url = session.get('listing_url')

    if not candidates or not slug:
        return render_template(
            "index.html",
            error="Sessie verlopen. Haal de foto's opnieuw op.",
        )

    if not selected_indices:
        # Show images again with error
        images = [{"index": idx, "url": url} for idx, url in enumerate(candidates)]
        return render_template(
            "index.html",
            url=listing_url,
            total_candidates=len(candidates),
            images=images,
            slug=slug,
            error="Selecteer minstens één foto.",
        )

    # Filter selected URLs
    selected_urls = []
    for idx_str in selected_indices:
        try:
            idx = int(idx_str)
            if 0 <= idx < len(candidates):
                selected_urls.append(candidates[idx])
        except ValueError:
            continue

    if not selected_urls:
        images = [{"index": idx, "url": url} for idx, url in enumerate(candidates)]
        return render_template(
            "index.html",
            url=listing_url,
            total_candidates=len(candidates),
            images=images,
            slug=slug,
            error="Geen geldige selectie.",
        )

    output_dir = os.path.join(DOWNLOADS_DIR, slug)
    clear_download_dir(output_dir)
    saved_files = download_images(selected_urls, output_dir)

    if not saved_files:
        images = [{"index": idx, "url": url} for idx, url in enumerate(candidates)]
        return render_template(
            "index.html",
            url=listing_url,
            total_candidates=len(candidates),
            images=images,
            slug=slug,
            error="Er konden geen foto's worden gedownload.",
        )

    downloaded_images = []
    downloaded_names = []
    for filepath in saved_files:
        name = os.path.basename(filepath)
        downloaded_names.append(name)
        downloaded_images.append({
            "name": name,
            "url": url_for("downloaded_file", slug=slug, filename=name),
        })

    session["last_downloaded"] = downloaded_names
    session["last_slug"] = slug

    display_output = os.path.relpath(output_dir, BASE_DIR)
    return render_template(
        "index.html",
        url=listing_url,
        downloaded_count=len(downloaded_images),
        downloaded_images=downloaded_images,
        zip_url=url_for("download_zip", slug=slug),
        output_dir=display_output,
    )


@app.get("/files/<slug>/<path:filename>")
def downloaded_file(slug, filename):
    if not is_safe_slug(slug):
        abort(404)
    directory = os.path.join(DOWNLOADS_DIR, slug)
    if not os.path.isdir(directory):
        abort(404)
    return send_from_directory(directory, filename)


@app.get("/zip/<slug>")
def download_zip(slug):
    if not is_safe_slug(slug):
        abort(404)
    directory = os.path.join(DOWNLOADS_DIR, slug)
    if not os.path.isdir(directory):
        abort(404)

    filenames = []
    last_slug = session.get("last_slug")
    last_downloaded = session.get("last_downloaded", [])
    if last_slug == slug and last_downloaded:
        for name in last_downloaded:
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                filenames.append(name)
    else:
        for name in os.listdir(directory):
            if not os.path.isfile(os.path.join(directory, name)):
                continue
            if os.path.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
                continue
            filenames.append(name)
    if not filenames:
        abort(404)

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_handle:
        for name in sorted(filenames):
            path = os.path.join(directory, name)
            zip_handle.write(path, arcname=name)

    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{slug}.zip",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)
