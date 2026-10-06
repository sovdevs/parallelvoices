# Public site (SPA + offer endpoint)

Vanilla SPA (`static/`, hash routes: `#/`, `#/preview`, `#/request`, `#/sent`, no build step) plus a small
FastAPI backend (`server.py`): catalog search (Open Library, fuzzy-reranked), ISBN lookup, and
`POST /api/offer`, which emails a non-binding offer to `OFFER_TO` (default devs@cogtrix.eu).

This directory is its own small uv project (no need for the repo's heavy root dependencies). From here:

    uv sync
    SITE_DEV=1 uv run uvicorn server:app --port 8765     # local: offers go to outbox/*.eml
    uv run uvicorn server:app --host 0.0.0.0 --port 8765 # production: needs SMTP_* below

Config (env or `../.env`, i.e. `doppeltextplus/.env`): `SMTP_HOST`, `SMTP_PORT` (587; 465 = implicit TLS), `SMTP_USER`,
`SMTP_PASS`, `SMTP_FROM` (defaults to SMTP_USER), `OFFER_TO`. With no `SMTP_HOST` and no `SITE_DEV=1` the
offer endpoint answers 503 instead of silently dropping offers. Every offer is also appended to
`site/offers.jsonl` *before* sending (it contains emails: personal data, keep it out of git, and delete on request).

Rebuild the preview from a preview EPUB:

    uv run python build_preview.py <preview.epub> <slug> "<Title>" "<Author>" ro

(`static/app.js` reads `static/preview/animale-bolnave/`; change `PREVIEW` there for another book.)

Checks: `uv run python test_server.py`.

Brand name ("Parallel Voices") appears in `index.html`, `app.js` (`document.title`) only. Fonts (Source Serif 4,
Hanken Grotesk, OFL) are self-hosted in `static/fonts/`; the site makes no third-party requests from the browser.
Rate limits are in-memory per process (see the note in `server.py` about reverse proxies).

## Deploying on Railway (same shape as Deckcast)

One container, one process. Railway builds the `Dockerfile` in this folder (Python 3.12 + `uv sync --frozen`).
**Keep it to one replica:** the rate limiter is in-memory.

1. Make `site/` its own git repo and push it to GitHub (the surrounding `epubber/` is not a repo and holds large,
   copyrighted inputs). Commit `uv.lock`. In Railway: New Project, Deploy from GitHub repo.
2. Add a **Volume** mounted at `/data`.
3. Variables:

   | Variable | Value |
   |---|---|
   | `DATA_DIR` | `/data` (keeps `offers.jsonl` across deploys) |
   | `PROXY_HOPS` | `1` (`2` behind Cloudflare). Without it every visitor looks like one IP and the 5-offers-an-hour limit applies to the whole site |
   | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | the same SMTP account Deckcast uses. Without mail config the offer endpoint answers 503 |
   | `OFFER_TO` | optional, default `devs@cogtrix.eu` |
   | `RESEND_API_KEY`, `MAIL_FROM` | optional alternative to SMTP, over HTTPS (use it if SMTP is blocked on your plan) |

   **Leave unset:** `SITE_DEV` (it writes offers to disk instead of mailing them).
4. Generate a domain (Settings, Networking) or attach your own.

Updating: push to `main`; Railway rebuilds. Offers are emailed AND appended to `/data/offers.jsonl` before sending; an
offer that fails to send is also logged in full (`OFFER NOT EMAILED`). `offers.jsonl` holds visitors' emails: personal
data, so mention it in a privacy notice and delete on request.

Not done: backups of `/data`, anything stronger than the honeypot and the rate limit against form spam, and a
confirmation email to the visitor (deliberately not sent: it would let anyone use the form to email strangers).
The preview under `static/preview/` becomes public with the site: confirm you have the rights to that text first.
