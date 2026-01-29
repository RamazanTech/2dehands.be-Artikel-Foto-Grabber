# 2dehands photo grabber

Grab and download photos from a 2dehands listing URL. Works as a local Flask web app, a CLI script, and a serverless Vercel deployment.

## Project info

- Version: 1.0.0
- Last updated: 2026-01-29
- License: Not specified

## Features

- Extracts listing photos and filters duplicates
- Normalizes 2dehands image quality rules
- Select which photos to download and zip
- Local web app and CLI
- Serverless Vercel deployment included

## Local web app

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run:

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

De serverless versie staat in `vercel/`. Je kan op twee manieren deployen:

- Vanuit de repo root (aanbevolen): `vercel.json` is aanwezig, geen Root Directory nodig.
- Vanuit `vercel/`: zet Root Directory op `vercel` in Vercel.

Zie `vercel/README.md` voor details.
