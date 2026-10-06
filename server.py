"""Public site backend: serves the SPA and three endpoints --
  GET  /api/search?q=&author=&title=&lang=ru|ro   fuzzy catalog search (Open Library, reranked)
  GET  /api/isbn/{isbn}                           ISBN lookup (checksum-validated)
  POST /api/offer                                 non-binding offer, emailed to OFFER_TO

Run:  uvicorn doppeltextplus.site.server:app   (from epubber/)

Config (env or doppeltextplus/.env):
  mail, either   RESEND_API_KEY + MAIL_FROM    (HTTPS API: works on hosts that block SMTP, e.g. Render/Railway entry plans)
            or   SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, SMTP_FROM (defaults to SMTP_USER)
  OFFER_TO (devs@cogtrix.eu), DATA_DIR (where offers.jsonl goes; default: next to this file), PROXY_HOPS (see below)
With neither mail option set the offer endpoint answers 503 -- unless SITE_DEV=1, which writes
.eml files to site/outbox/ instead. Every offer is also appended to DATA_DIR/offers.jsonl BEFORE
sending, and logged in full if the send fails, so a mail failure doesn't lose one (on a host with
an ephemeral disk the log is the surviving copy; mount a volume and set DATA_DIR to keep the file).

ponytail: rate limits are in-memory per process: run ONE replica. The client address is the socket peer, or,
with PROXY_HOPS=n, the n-th entry from the RIGHT of X-Forwarded-For (the entries a visitor can spoof are on
the left; the ones the platform's proxies add are on the right). Railway: PROXY_HOPS=1 (2 behind Cloudflare).
Without it every visitor looks like the proxy and the whole site shares one 5-offers-an-hour bucket.
"""
from __future__ import annotations
import json
import logging
import os
import re
import smtplib
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Literal, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from rapidfuzz import fuzz

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR") or HERE)  # offers.jsonl lives here
load_dotenv(HERE.parent / ".env")
log = logging.getLogger("site")

OL_LANG = {"ru": "rus", "ro": "rum"}  # Open Library uses ISO 639-2/B codes
LANG_NAME = {"ru": "Russian", "ro": "Romanian"}
UA = {"User-Agent": "parallel-voices-site/0.1 (devs@cogtrix.eu)"}
OL_FIELDS = "key,title,author_name,first_publish_year,isbn,cover_i"
EMAIL_RE = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]{2,}$")

app = FastAPI(title="Parallel Voices", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


# ---- rate limiting ----------------------------------------------------------------------------
_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    hops = int(os.environ.get("PROXY_HOPS", "0") or 0)
    if hops:
        chain = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
        if len(chain) >= hops:
            return chain[-hops]
    return request.client.host if request.client else "?"


def _limit(request: Request, bucket: str, n: int, per: int) -> None:
    q, now = _hits[(bucket, _client_ip(request))], time.time()
    while q and q[0] < now - per:
        q.popleft()
    if len(q) >= n:
        raise HTTPException(429, "Too many requests. Please wait a bit and try again.")
    q.append(now)


# ---- ISBN -------------------------------------------------------------------------------------
def clean_isbn(s: str) -> Optional[str]:
    """Normalized ISBN-10/13 if the checksum holds, else None."""
    s = re.sub(r"[\s-]", "", s or "").upper()
    if re.fullmatch(r"\d{13}", s):
        ok = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s)) % 10 == 0
    elif re.fullmatch(r"\d{9}[\dX]", s):
        ok = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s)) % 11 == 0
    else:
        return None
    return s if ok else None


# ---- catalog ----------------------------------------------------------------------------------
def _ol_search(params: dict) -> list[dict]:
    try:
        r = httpx.get("https://openlibrary.org/search.json", params={**params, "fields": OL_FIELDS},
                      headers=UA, timeout=10)
        r.raise_for_status()
        return r.json().get("docs", [])
    except (httpx.HTTPError, ValueError) as e:
        log.warning("open library failed: %s", e)
        raise HTTPException(502, "The catalog is not reachable right now. You can still enter the book by hand.")


def _book(d: dict) -> dict:
    isbns = [i for i in (clean_isbn(x) for x in d.get("isbn", [])) if i]
    isbn13 = next((i for i in isbns if len(i) == 13), None)
    return {
        "key": d.get("key"), "title": d.get("title", ""), "authors": d.get("author_name", [])[:3],
        "year": d.get("first_publish_year"), "isbn": isbn13 or (isbns[0] if isbns else None),
        "cover": f"https://covers.openlibrary.org/b/id/{d['cover_i']}-M.jpg" if d.get("cover_i") else None,
    }


_search_cache: dict[tuple, tuple[float, list]] = {}  # (lang, q, author, title) -> (when, results); 10 min, 500 entries
_pool = ThreadPoolExecutor(4)


@app.get("/api/search")
def search(request: Request, lang: Literal["ru", "ro"], q: str = "", author: str = "", title: str = ""):
    _limit(request, "search", 60, 60)
    q, author, title = q.strip()[:200], author.strip()[:200], title.strip()[:200]
    text = q or f"{author} {title}".strip()
    if len(text) < 2:
        return {"results": []}
    ck = (lang, q, author, title)
    hit = _search_cache.get(ck)
    if hit and time.time() - hit[0] < 600:
        return {"results": hit[1]}
    base = {"language": OL_LANG[lang], "limit": 25}
    queries = [{**base, "q": text}]
    if author and title:  # structured query is precise; the free-text one above forgives typos in word order
        queries.append({**base, "q": f"title:({title}) AND author:({author})"})
    docs: dict[str, dict] = {}
    for result in _pool.map(_ol_search, queries):  # concurrently: Open Library is the slow part
        for d in result:
            docs.setdefault(d.get("key", ""), d)
    if len(docs) < 3:  # Open Library wants every word to match; a typo kills the query. Retry with ANY word
        toks = re.findall(r"\w{3,}", text)[:6]  # matching, then let the local fuzzy rerank sort it out
        for d in _ol_search({**base, "q": " OR ".join(toks), "limit": 40}) if toks else []:
            docs.setdefault(d.get("key", ""), d)
    books = [_book(d) for d in docs.values()]
    qt = [t for t in re.findall(r"\w+", text.lower()) if len(t) >= 2]
    for b in books:  # rerank: Open Library has no typo tolerance, so score locally. Each query word is
        # matched to its best word in "authors + title" and the scores averaged, so a MISSING word costs
        # points (rapidfuzz's WRatio rates any partial overlap ~86 and can't tell books apart).
        ct = re.findall(r"\w+", f"{' '.join(b['authors'])} {b['title']}".lower())
        b["score"] = sum(max((fuzz.ratio(q, c) for c in ct), default=0) for q in qt) / max(len(qt), 1)
    books.sort(key=lambda b: -b["score"])
    results = [b for b in books if b["score"] >= 58][:6]
    if len(_search_cache) >= 500:
        _search_cache.clear()
    _search_cache[ck] = (time.time(), results)
    return {"results": results}


@app.get("/api/isbn/{isbn}")
def by_isbn(request: Request, isbn: str):
    _limit(request, "search", 60, 60)
    clean = clean_isbn(isbn)
    if not clean:
        raise HTTPException(422, "That ISBN doesn't look right. Check the digits (10 or 13).")
    docs = _ol_search({"q": f"isbn:{clean}", "limit": 1})
    return {"isbn": clean, "book": _book(docs[0]) if docs else None}


# ---- offers -----------------------------------------------------------------------------------
class Offer(BaseModel):
    mode: Literal["isbn", "title"]
    language: Literal["ru", "ro"]
    email: str
    bid: float
    order: Literal["original", "english"] = "original"          # which language comes first on the page
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"  # vocabulary notes
    layout: Literal["popup", "interleaved"] = "interleaved"
    isbn: str = ""
    author: str = ""
    title: str = ""
    picked: Optional[dict] = None  # the catalog match the user chose, if any (informational)
    website: str = ""  # honeypot: real users never see or fill this

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 254 or not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("bid")
    @classmethod
    def _bid(cls, v: float) -> float:
        if not (1 <= v <= 100000):
            raise ValueError("Enter an amount between 1 and 100,000 USD.")
        return round(v, 2)

    @field_validator("author", "title")
    @classmethod
    def _txt(cls, v: str) -> str:
        v = " ".join(v.split())  # also strips any newlines, so nothing can reach a mail header
        if len(v) > 200:
            raise ValueError("That is too long (200 characters at most).")
        return v


def _one_line(s: str, n: int = 120) -> str:
    return " ".join(str(s).split())[:n]


def _compose(o: Offer, isbn: Optional[str]) -> EmailMessage:
    book = f"{o.title} by {o.author}" if o.mode == "title" else f"ISBN {isbn}"
    m = EmailMessage()
    m["Subject"] = _one_line(f"Non-binding offer: ${o.bid:,.2f} for {book} ({LANG_NAME[o.language]} to English)", 200)
    m["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "site@localhost"
    m["To"] = os.environ.get("OFFER_TO", "devs@cogtrix.eu")
    m["Reply-To"] = o.email
    picked = json.dumps(o.picked, ensure_ascii=False, indent=2) if o.picked else "(none -- entered by hand)"
    m.set_content(
        "A visitor sent a NON-BINDING offer.\n\n"
        f"Offer:      ${o.bid:,.2f} USD\n"
        f"Contact:    {o.email}  (Reply-To is set)\n"
        f"Language:   {LANG_NAME[o.language]} -> English\n"
        f"Edition:    {LANG_NAME[o.language] if o.order == 'original' else 'English'} first, "
        f"{o.level} vocabulary, {o.layout} layout\n"
        "Included:   plot outline, chapter summaries, character profiles (always)\n"
        f"Lookup by:  {'ISBN' if o.mode == 'isbn' else 'author and title'}\n"
        f"ISBN:       {isbn or '-'}\n"
        f"Author:     {o.author or '-'}\n"
        f"Title:      {o.title or '-'}\n"
        f"Received:   {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n\n"
        f"Catalog match chosen by the visitor:\n{picked}\n"
    )
    return m


def _deliver(m: EmailMessage) -> str:
    key = os.environ.get("RESEND_API_KEY")
    if key:  # HTTPS API: no SMTP port needed
        try:
            r = httpx.post("https://api.resend.com/emails", timeout=15, headers={"Authorization": f"Bearer {key}"}, json={
                "from": os.environ.get("MAIL_FROM") or m["From"], "to": [m["To"]], "reply_to": m["Reply-To"],
                "subject": m["Subject"], "text": m.get_content()})
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.error("offer email (resend) failed: %s", e)
            raise HTTPException(502, "We couldn't send your offer. Please try again in a few minutes, or email devs@cogtrix.eu.")
        return "email"
    host = os.environ.get("SMTP_HOST")
    if not host:
        if os.environ.get("SITE_DEV") != "1":
            raise HTTPException(503, "Offers are temporarily unavailable. Please email devs@cogtrix.eu instead.")
        out = HERE / "outbox"
        out.mkdir(exist_ok=True)
        (out / f"{int(time.time() * 1000)}.eml").write_bytes(bytes(m))
        return "outbox"
    port = int(os.environ.get("SMTP_PORT", "587"))
    try:
        cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        with cls(host, port, timeout=20) as s:
            if port != 465:
                s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
            s.send_message(m)
    except (smtplib.SMTPException, OSError) as e:
        log.error("offer email failed: %s", e)
        raise HTTPException(502, "We couldn't send your offer. Please try again in a few minutes, or email devs@cogtrix.eu.")
    return "email"


@app.post("/api/offer")
def offer(request: Request, o: Offer):
    _limit(request, "offer", 5, 3600)
    if o.website:  # bot: pretend it worked, send nothing
        return {"ok": True, "delivery": "email"}
    isbn = clean_isbn(o.isbn) if o.mode == "isbn" else None
    if o.mode == "isbn" and not isbn:
        raise HTTPException(422, "That ISBN doesn't look right. Check the digits (10 or 13).")
    if o.mode == "title" and (len(o.title) < 2 or len(o.author) < 2):
        raise HTTPException(422, "Enter both the author and the title.")
    m = _compose(o, isbn)
    rec = {"at": time.time(), "isbn": isbn, **o.model_dump(exclude={"website"})}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with (DATA_DIR / "offers.jsonl").open("a", encoding="utf-8") as f:  # saved first: a mail failure must not lose it
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    try:
        return {"ok": True, "delivery": _deliver(m)}
    except HTTPException:
        log.error("OFFER NOT EMAILED, recover from here: %s", json.dumps(rec, ensure_ascii=False))
        raise
