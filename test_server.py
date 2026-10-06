"""Runnable check (no pytest needed):  uv run python test_server.py   (from this directory)
Covers the parts that must not break: ISBN checksums, offer validation, header-injection safety,
honeypot, rate limit, and the no-SMTP behaviour."""
import os
import tempfile
from pathlib import Path

os.environ["SITE_DEV"] = "1"
os.environ.pop("SMTP_HOST", None)
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server

server.HERE = Path(tempfile.mkdtemp())  # keep the real offers.jsonl / outbox clean
server.DATA_DIR = server.HERE
(server.HERE / "static").mkdir()
c = TestClient(server.app)

assert server.clean_isbn("978-0-14-044917-4") == "9780140449174"
assert server.clean_isbn("0-14-044917-5") == "0140449175"  # ISBN-10 with a valid checksum
assert server.clean_isbn("0-14-044917-6") is None
assert server.clean_isbn("9780140449175") is None and server.clean_isbn("abc") is None
assert server.clean_isbn("080442957X") == "080442957X"  # X check digit

ok = {"mode": "title", "language": "ro", "email": "a@b.eu", "bid": 12.5, "author": "Nicolae Breban", "title": "Animale bolnave",
      "order": "english", "level": "advanced", "layout": "popup"}
r = c.post("/api/offer", json=ok)
assert r.status_code == 200 and r.json()["delivery"] == "outbox", r.text
eml = next((server.HERE / "outbox").glob("*.eml")).read_text()
assert "Reply-To: a@b.eu" in eml and "$12.50" in eml and "Romanian to English" in eml
assert "English first, advanced vocabulary, popup layout" in eml and "chapter summaries" in eml

for bad in ({**ok, "email": "nope"}, {**ok, "bid": 0}, {**ok, "bid": 1e9}, {**ok, "title": "x"},
            {**ok, "mode": "isbn", "isbn": "123"}, {**ok, "language": "de"}, {**ok, "level": "expert"}, {**ok, "layout": "enhanced"}, {**ok, "order": "x"}):
    server._hits.clear()
    assert c.post("/api/offer", json=bad).status_code == 422, bad

server._hits.clear()  # a newline in a text field must not reach a header
r = c.post("/api/offer", json={**ok, "title": "Evil\r\nBcc: x@y.z"})
assert r.status_code == 200
assert "\nBcc:" not in next(iter(sorted((server.HERE / "outbox").glob("*.eml"))[-1:])).read_text().split("\n\n")[0]

server._hits.clear()
n_before = len(list((server.HERE / "outbox").glob("*.eml")))
assert c.post("/api/offer", json={**ok, "website": "spam"}).json()["ok"]
assert len(list((server.HERE / "outbox").glob("*.eml"))) == n_before  # honeypot sends nothing

server._hits.clear()
codes = [c.post("/api/offer", json=ok).status_code for _ in range(7)]
assert codes[:5] == [200] * 5 and codes[5] == 429, codes

server._hits.clear()
os.environ.pop("SITE_DEV")
assert c.post("/api/offer", json=ok).status_code == 503  # prod with no SMTP fails loudly, not silently
# HTTPS mail path (hosts that block SMTP): one POST to the API with Reply-To set; failure -> 502, offer still saved + logged
os.environ["RESEND_API_KEY"], os.environ["MAIL_FROM"] = "k", "offers@example.com"
calls = []


class _R:
    def raise_for_status(self):
        pass


server.httpx.post = lambda url, **kw: (calls.append((url, kw)), _R())[1]
server._hits.clear()
assert c.post("/api/offer", json=ok).json()["delivery"] == "email"
url, kw = calls[0]
assert url == "https://api.resend.com/emails" and kw["json"]["reply_to"] == "a@b.eu" and kw["json"]["to"] == ["devs@cogtrix.eu"]
assert kw["json"]["from"] == "offers@example.com" and "English first, advanced" in kw["json"]["text"]


def _boom(url, **kw):
    raise server.httpx.ConnectError("down")


server.httpx.post = _boom
server._hits.clear()
assert c.post("/api/offer", json=ok).status_code == 502
assert (server.HERE / "offers.jsonl").read_text().count("\n") >= 2  # saved even though mail failed
del os.environ["RESEND_API_KEY"]
# PROXY_HOPS: the client is the n-th entry from the RIGHT of X-Forwarded-For; a spoofed leftmost entry is ignored
os.environ["PROXY_HOPS"] = "1"
server._hits.clear()
os.environ["SITE_DEV"] = "1"
for spoof in ("1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4", "5.5.5.5", "6.6.6.6"):  # same real IP, 6 different spoofed lefts
    r = c.post("/api/offer", json=ok, headers={"X-Forwarded-For": f"{spoof}, 9.9.9.9"})
assert r.status_code == 429, r.status_code
assert c.post("/api/offer", json=ok, headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 200  # a different real IP is separate
del os.environ["PROXY_HOPS"]
print("site server checks passed")
