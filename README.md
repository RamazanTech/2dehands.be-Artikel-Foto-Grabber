# 2dehands photo grabber

Fetch and download photos from a 2dehands listing URL, via CLI or a local web app.

## Setup

```bash
python -m pip install -r requirements.txt
```

## Web app

```bash
python app.py
```

Open `http://127.0.0.1:5000` in your browser.

## CLI usage

```bash
python grab_2dehands_photos.py "https://www.2dehands.be/v/..."
```

Options:

```bash
python grab_2dehands_photos.py "https://www.2dehands.be/v/..." --out downloads/my-listing --max 20
```

Downloads are saved to `downloads/<listing-slug>` by default.

## Vercel (gratis)

De serverless versie staat in `vercel/`. Bekijk `vercel/README.md` voor deploy‑stappen.
