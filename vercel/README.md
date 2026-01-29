# Vercel deployment

This folder contains a serverless version of the app for Vercel.

## Deploy

1. Push this folder to a Git repo (or use `vercel` CLI).
2. In Vercel, set **Root Directory** to `vercel`.
3. Deploy.

The frontend is static in `public/`, and the API is in `api/`.

## If you deploy from repo root

You can deploy from the repository root using the `vercel.json` file.
In that case, you don't need to set Root Directory.
