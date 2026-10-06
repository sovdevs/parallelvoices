"""Turn a preview EPUB into static files the SPA's reader can show:
   static/preview/<slug>/index.json   chapters [{title, file}] + book info
   static/preview/<slug>/NN.html      each chapter's body markup (footnote asides dropped)
   static/preview/<slug>/chars.css    the character-colour rules from the EPUB's stylesheet
   static/preview/<slug>/<slug>.epub  the file itself, for download
Usage (from epubber/):  python -m doppeltextplus.site.build_preview <preview.epub> <slug> "<Title>" "<Author>" ru|ro
"""
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build(epub: Path, slug: str, title: str, author: str, lang: str) -> None:
    out = HERE / "static" / "preview" / slug
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    z = zipfile.ZipFile(epub)
    files = [n for n in z.namelist() if n.endswith(".xhtml") and not n.endswith("nav.xhtml")]
    chapters = []
    for i, n in enumerate(sorted(files, key=lambda n: (n.split("/")[-1] != "guide.xhtml", n))):
        s = z.read(n).decode("utf-8")
        body = re.search(r"<body[^>]*>(.*)</body>", s, re.S).group(1)
        body = re.sub(r"<aside\b.*?</aside>", "", body, flags=re.S)
        body = re.sub(r"<script\b.*?</script>", "", body, flags=re.S)
        t = re.search(r"<title>(.*?)</title>", s, re.S)
        (out / f"{i:02d}.html").write_text(body.strip(), encoding="utf-8")
        chapters.append({"title": re.sub(r"<[^>]+>", "", t.group(1)) if t else f"Part {i}", "file": f"{i:02d}.html"})
    css = z.read(next(n for n in z.namelist() if n.endswith("dtp.css"))).decode("utf-8")
    (out / "chars.css").write_text(css[css.index("/* character name highlights */"):], encoding="utf-8")  # per-character colours only
    shutil.copy2(epub, out / f"{slug}.epub")
    (out / "index.json").write_text(json.dumps(
        {"slug": slug, "title": title, "author": author, "lang": lang, "epub": f"{slug}.epub", "chapters": chapters},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(chapters)} sections -> {out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    build(Path(a[0]), a[1], a[2], a[3], a[4])
