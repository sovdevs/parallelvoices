// Parallel Voices: a small hash-routed SPA. No build step, no dependencies.
// Routes: #/ (home) · #/preview (reader) · #/request (offer form) · #/sent (confirmation)

const PREVIEW = "/static/preview/animale-bolnave/";
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const view = $("#view");
const cache = {};

async function load(path, json = false) {
  if (!cache[path]) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(path);
    cache[path] = json ? r.json() : r.text();
  }
  return cache[path];
}

// Character colours: injected once, globally, so names are coloured on the page and in the reader.
let charsCss = false;
async function ensureCharColors() {
  if (charsCss) return;
  charsCss = true;
  try {
    const st = document.createElement("style");
    st.textContent = await load(PREVIEW + "chars.css");
    document.head.append(st);
  } catch { /* the page still works uncoloured */ }
}

// ---- preview markup -> units -------------------------------------------------------------------
// The EPUB is a flat run of: <p> translation, <div.dtp-sec-inline> original, [<div.dtp-vocab-inline> word notes].
// Group those into one .unit per paragraph so the language order is a CSS switch, and make word marks tappable.
function toUnits(html) {
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  const out = document.createElement("div");
  let unit = null;
  for (const el of [...tpl.content.children]) {
    if (el.matches("p[id]")) {
      unit = Object.assign(document.createElement("div"), { className: "unit" });
      el.className = "trans";
      unit.append(el);
      out.append(unit);
    } else if (el.matches(".dtp-sec-inline") && unit) {
      const p = el.querySelector("p");
      p.className = "orig";
      p.lang = el.getAttribute("lang") || "";
      unit.append(p);
    } else if (el.matches(".dtp-vocab-inline") && unit) {
      const box = Object.assign(document.createElement("div"), { className: "notes" });
      for (const item of el.querySelectorAll(".dtp-vocab-item")) {
        const n = item.querySelector(".dtp-vocab-num")?.textContent;
        item.querySelector(".dtp-vocab-num")?.remove();
        const note = Object.assign(document.createElement("div"), { className: "note", hidden: true });
        note.dataset.n = n;
        note.innerHTML = item.innerHTML.trim();
        box.append(note);
      }
      unit.append(box);
    } else {
      out.append(el); // headings, lists, anything else, as-is
      unit = null;
    }
  }
  wireNotes(out);
  return out;
}

function wireNotes(root) {
  for (const unit of root.querySelectorAll(".unit")) {
    for (const mark of unit.querySelectorAll(".dtp-vocab")) {
      const n = mark.querySelector(".dtp-vocab-num")?.textContent;
      const note = unit.querySelector(`.note[data-n="${n}"]`);
      if (!note) continue;
      mark.setAttribute("role", "button");
      mark.tabIndex = 0;
      mark.setAttribute("aria-expanded", "false");
      const toggle = () => {
        note.hidden = !note.hidden;
        mark.setAttribute("aria-expanded", String(!note.hidden));
      };
      mark.addEventListener("click", toggle);
      mark.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
    }
  }
}

// ---- home --------------------------------------------------------------------------------------
async function home() {
  view.innerHTML = `
  <div class="wrap">
    <section class="hero">
      <div>
        <h1>Read the novel in its own language. The English is right underneath.</h1>
        <p class="lede">Parallel editions of Russian and Romanian books. Every paragraph is followed by its English translation, hard words are explained where they appear, and each character keeps one color from the first page to the last.</p>
        <div class="actions">
          <a class="btn" href="#/preview">Read a free preview</a>
          <a class="btn ghost" href="#/request">Ask us to make a book</a>
        </div>
      </div>
      <figure class="page" id="specimen" aria-label="Sample page"><p class="status">Loading a sample page…</p></figure>
    </section>

    <section class="band" aria-label="Languages">
      <p class="lang-name" lang="ru">Русский<small>Russian to English</small></p>
      <p class="lang-name" lang="ro">Română<small>Romanian to English</small></p>
    </section>

    <section class="how">
      <h2>What is on the page</h2>
      <div>
        <div><h3>Each paragraph, then its translation</h3>
          <p>The original comes first, set in a book typeface. The English translation sits right under it, matched sentence by sentence, so you can check yourself without losing your place. You can switch the order whenever you like.</p></div>
        <div><h3>Hard words, explained in context</h3>
          <p>Rare words, idioms and tricky sentence structures carry a dotted underline. Tap one to see what it means in that sentence, and how the translator handled it.</p></div>
        <div><h3>Characters in color</h3>
          <p>Names are highlighted, one color per character, in both languages. Each book ends with a profile of its main characters.</p></div>
        <div><h3>The plot, chapter by chapter</h3>
          <p>Every edition closes with a plot outline: a summary of each chapter and its key events. It contains spoilers, so it sits at the back.</p></div>
        <div><h3>Set it up your way</h3>
          <p>Choose which language comes first, how much vocabulary help you want (beginner, intermediate or advanced), and whether the other language is printed under each paragraph or appears in a pop-up.</p></div>
        <div><h3>An ordinary ebook</h3>
          <p>Editions are EPUB files, the standard ebook format that most reading apps open.</p></div>
      </div>
    </section>

    <section class="cta">
      <h2>Missing a book you would read this way?</h2>
      <p>Tell us which one and what it is worth to you. Offers are non-binding, and we use them to decide what to make next.</p>
      <div class="actions"><a class="btn" href="#/request">Request a book</a></div>
    </section>
  </div>`;
  await ensureCharColors();
  try {
    const idx = await load(PREVIEW + "index.json", true);
    // the first paragraph that shows off the features (a word mark and a character name, not too long), from any excerpt
    let unit = null;
    for (const c of idx.chapters.filter((c) => /Excerpt/.test(c.title))) {
      const frag = toUnits(await load(PREVIEW + c.file));
      unit = [...frag.querySelectorAll(".unit")].find((u) =>
        u.querySelector(".orig .dtp-vocab") && u.querySelector(".dtp-ch") && u.textContent.length < 900);
      if (unit) break;
    }
    const fig = $("#specimen");
    if (!unit) throw new Error("no sample");
    fig.replaceChildren(unit);
    fig.insertAdjacentHTML("beforeend", `<figcaption>From <em>${esc(idx.title)}</em> by ${esc(idx.author)}. Tap a dotted word.</figcaption>`);
  } catch {
    $("#specimen").remove();
  }
}

// ---- preview reader ----------------------------------------------------------------------------
async function preview() {
  view.innerHTML = `<div class="wrap"><p class="status">Loading the preview…</p></div>`;
  await ensureCharColors();
  const idx = await load(PREVIEW + "index.json", true);
  const parts = idx.chapters.filter((c) => !/^How to read/.test(c.title));
  view.innerHTML = `
  <div class="wrap">
    <h1>Free preview</h1>
    <p><em>${esc(idx.title)}</em> by ${esc(idx.author)}, ${parts.length - 1} short passages from the book as they appear in the edition. Tap a dotted word for its explanation.</p>
    <div class="reader-bar">
      <div class="seg" role="group" aria-label="Which language comes first">
        <button type="button" data-order="orig" aria-pressed="true">Romanian first</button>
        <button type="button" data-order="en" aria-pressed="false">English first</button>
      </div>
      <a class="btn ghost" href="${PREVIEW}${esc(idx.epub)}" download>Download the EPUB</a>
    </div>
    <p class="hint">The download is the English-first edition with beginner vocabulary and the interleaved layout.</p>
    <div class="tabs" role="tablist" aria-label="Passages"></div>
    <article class="reading" id="reading" aria-live="polite"></article>
    <section class="cta"><h2>Want a book like this?</h2>
      <p>Tell us which one, and what it is worth to you.</p>
      <div class="actions"><a class="btn" href="#/request">Request a book</a></div></section>
  </div>`;
  const reading = $("#reading"), tabs = $(".tabs");
  const show = async (i) => {
    for (const b of tabs.children) b.setAttribute("aria-selected", String(+b.dataset.i === i));
    reading.replaceChildren(toUnits(await load(PREVIEW + parts[i].file)));
  };
  parts.forEach((c, i) => {
    const b = Object.assign(document.createElement("button"), { type: "button", textContent: c.title.replace(/ \(chapter \d+\)/, "") });
    b.setAttribute("role", "tab");
    b.dataset.i = i;
    b.addEventListener("click", () => show(i));
    tabs.append(b);
  });
  $(".seg").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    for (const x of $(".seg").children) x.setAttribute("aria-pressed", String(x === b));
    reading.classList.toggle("en-first", b.dataset.order === "en");
  });
  show(0);
}

// ---- request form ------------------------------------------------------------------------------
const LANG = { ru: "Russian", ro: "Romanian" };
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

function request() {
  view.innerHTML = `
  <div class="wrap">
    <h1>Ask us to make a book</h1>
    <p>Tell us which book you would like in this format and what it is worth to you. Offers are non-binding: you are not charged anything, and we use them to decide which books to make next.</p>
    <form class="form" id="offer" novalidate>
      <fieldset>
        <legend>Language of the original</legend>
        <div class="radios">
          <label><input type="radio" name="language" value="ru" checked> Russian to English</label>
          <label><input type="radio" name="language" value="ro"> Romanian to English</label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Find the book by</legend>
        <div class="radios">
          <label><input type="radio" name="mode" value="title" checked> Author and title</label>
          <label><input type="radio" name="mode" value="isbn"> ISBN</label>
        </div>
      </fieldset>

      <div id="by-title">
        <div class="two">
          <div><label class="field" for="author">Author</label><input type="text" id="author" name="author" autocomplete="off" maxlength="200"></div>
          <div><label class="field" for="title">Title</label><input type="text" id="title" name="title" autocomplete="off" maxlength="200"></div>
        </div>
        <p class="hint">Spelling does not have to be exact. Matches from a public catalog appear as you type; pick one, or keep what you typed.</p>
        <ul class="matches" id="matches" aria-label="Matching books"></ul>
        <div class="status" id="match-status" role="status"></div>
      </div>

      <div id="by-isbn" hidden>
        <label class="field" for="isbn">ISBN (10 or 13 digits)</label>
        <input type="text" id="isbn" name="isbn" inputmode="text" autocomplete="off" maxlength="20" placeholder="978-…">
        <div class="status" id="isbn-status" role="status"></div>
      </div>
      <div id="picked" class="picked" hidden></div>

      <fieldset>
        <legend>Your edition</legend>
        <div class="choices">
          <p class="choice-title">Which language comes first on the page</p>
          <label><input type="radio" name="order" value="original" checked> <span><strong id="first-orig">Russian first</strong><small>The original, with the English translation beneath it.</small></span></label>
          <label><input type="radio" name="order" value="english"> <span><strong>English first</strong><small>The English translation, with the original beneath it.</small></span></label>

          <p class="choice-title">Vocabulary level</p>
          <label><input type="radio" name="level" value="beginner" checked> <span><strong>Beginner</strong><small>Most hard words and constructions explained, including the less common everyday ones.</small></span></label>
          <label><input type="radio" name="level" value="intermediate"> <span><strong>Intermediate</strong><small>Idioms, figurative language and less common vocabulary.</small></span></label>
          <label><input type="radio" name="level" value="advanced"> <span><strong>Advanced</strong><small>Only rare, archaic, literary or regional words and subtle idioms.</small></span></label>

          <p class="choice-title">Layout</p>
          <label><input type="radio" name="layout" value="interleaved" checked> <span><strong>Interleaved</strong><small>The other language is printed under every paragraph. Works in any reading app.</small></span></label>
          <label><input type="radio" name="layout" value="popup"> <span><strong>Popup</strong><small>Tap a paragraph to reveal the other language in a pop-up note. Needs a reading app that shows footnote pop-ups.</small></span></label>
        </div>
        <p class="hint">Every edition also includes a plot outline with a summary of each chapter, and profiles of the characters.</p>
      </fieldset>

      <div><label class="field" for="email">Your email</label>
        <input type="email" id="email" name="email" autocomplete="email" maxlength="254" required>
        <p class="hint">So we can reach you about this offer.</p></div>

      <div><label class="field" for="bid">Your offer in US dollars</label>
        <div class="money"><span aria-hidden="true">$</span><input type="number" id="bid" name="bid" min="1" max="100000" step="0.01" inputmode="decimal" required></div>
        <p class="hint">Non-binding. Nothing is charged.</p></div>

      <div class="hp" aria-hidden="true"><label>Leave this empty <input type="text" name="website" tabindex="-1" autocomplete="off"></label></div>

      <p class="error" id="error" role="alert"></p>
      <div><button class="btn" type="submit" id="send">Send offer</button></div>
    </form>
  </div>`;

  const f = $("#offer");
  const val = (n) => f.elements[n].value.trim();
  const lang = () => f.elements.language.value;
  const mode = () => f.elements.mode.value;
  let picked = null;

  const setPicked = (b) => {
    picked = b;
    const box = $("#picked");
    box.hidden = !b;
    if (b) box.innerHTML = `Selected: <strong>${esc(b.title)}</strong> by ${esc(b.authors.join(", ") || "unknown author")}${b.year ? ` (${esc(b.year)})` : ""}${b.isbn ? `, ISBN ${esc(b.isbn)}` : ""}`;
  };

  const firstLabel = () => { $("#first-orig").textContent = `${LANG[lang()]} first`; };
  firstLabel();

  f.addEventListener("change", (e) => {
    if (e.target.name === "language") firstLabel();
    if (e.target.name === "mode") {
      $("#by-title").hidden = mode() !== "title";
      $("#by-isbn").hidden = mode() !== "isbn";
      setPicked(null);
    }
    if (e.target.name === "language") search();
  });

  const search = debounce(async () => {
    if (mode() !== "title") return;
    const author = val("author"), title = val("title"), ul = $("#matches"), st = $("#match-status");
    ul.replaceChildren();
    if (author.length + title.length < 3) { st.textContent = ""; return; }
    st.textContent = "Searching…";
    try {
      const r = await fetch(`/api/search?lang=${lang()}&author=${encodeURIComponent(author)}&title=${encodeURIComponent(title)}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail);
      st.textContent = j.results.length ? "" : "No match in the catalog. You can still send the offer with what you typed.";
      for (const b of j.results) {
        const li = document.createElement("li");
        const btn = Object.assign(document.createElement("button"), { type: "button" });
        btn.innerHTML = `<strong>${esc(b.title)}</strong> <span class="by">${esc(b.authors.join(", "))}${b.year ? ", " + esc(b.year) : ""}</span>`;
        btn.addEventListener("click", () => {
          f.elements.author.value = b.authors[0] || author;
          f.elements.title.value = b.title;
          setPicked(b);
          ul.replaceChildren();
        });
        li.append(btn);
        ul.append(li);
      }
    } catch (e) {
      st.textContent = e.message || "Search is unavailable. You can still enter the book by hand.";
    }
  }, 400);
  f.elements.author.addEventListener("input", () => { setPicked(null); search(); });
  f.elements.title.addEventListener("input", () => { setPicked(null); search(); });

  f.elements.isbn.addEventListener("change", async () => {
    const st = $("#isbn-status"), v = val("isbn");
    setPicked(null);
    if (!v) { st.textContent = ""; return; }
    st.textContent = "Looking it up…";
    try {
      const r = await fetch(`/api/isbn/${encodeURIComponent(v)}`);
      const j = await r.json();
      if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "That ISBN doesn't look right.");
      st.textContent = j.book ? "" : "Not in the catalog. You can still send the offer.";
      if (j.book) setPicked(j.book);
    } catch (e) {
      st.textContent = e.message;
    }
  });

  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("#error"), btn = $("#send");
    err.textContent = "";
    const body = {
      mode: mode(), language: lang(), email: val("email"), bid: Number(val("bid")),
      order: f.elements.order.value, level: f.elements.level.value, layout: f.elements.layout.value,
      isbn: val("isbn"), author: val("author"), title: val("title"), picked, website: val("website"),
    };
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(body.email)) { err.textContent = "Enter a valid email address."; f.elements.email.focus(); return; }
    if (!(body.bid >= 1)) { err.textContent = "Enter an amount of at least 1 US dollar."; f.elements.bid.focus(); return; }
    if (body.mode === "title" && (body.author.length < 2 || body.title.length < 2)) { err.textContent = "Enter both the author and the title."; return; }
    if (body.mode === "isbn" && !body.isbn) { err.textContent = "Enter the ISBN."; f.elements.isbn.focus(); return; }
    btn.disabled = true;
    btn.textContent = "Sending…";
    try {
      const r = await fetch("/api/offer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        const d = j.detail;
        throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => String(x.msg).replace(/^Value error, /, "")).join(" ") : "Something went wrong. Please try again.");
      }
      sessionStorage.setItem("sent", JSON.stringify({ ...body, picked: picked ? picked.title : null }));
      location.hash = "#/sent";
    } catch (e2) {
      err.textContent = e2.message;
      btn.disabled = false;
      btn.textContent = "Send offer";
    }
  });
}

function sent() {
  let s = null;
  try { s = JSON.parse(sessionStorage.getItem("sent")); } catch { /* fall through */ }
  if (!s) { location.hash = "#/request"; return; }
  const what = s.mode === "isbn" ? `ISBN ${esc(s.isbn)}` : `${esc(s.title)} by ${esc(s.author)}`;
  view.innerHTML = `
  <div class="wrap">
    <h1>Offer sent</h1>
    <div class="sent">
      <p>Thank you. Nothing has been charged. If we decide to make this book, we will write to <strong>${esc(s.email)}</strong>.</p>
      <dl><dt>Book</dt><dd>${what}</dd><dt>Language</dt><dd>${LANG[s.language]} to English</dd><dt>Edition</dt><dd>${s.order === "english" ? "English" : LANG[s.language]} first, ${esc(s.level)} vocabulary, ${esc(s.layout)} layout</dd><dt>Your offer</dt><dd>$${Number(s.bid).toFixed(2)} (non-binding)</dd></dl>
      <div class="actions"><a class="btn" href="#/preview">Read the free preview</a><a class="btn ghost" href="#/request">Make another offer</a></div>
    </div>
  </div>`;
}

// ---- router ------------------------------------------------------------------------------------
const routes = { "": home, preview, request, sent };
const TITLES = { "": "", preview: "Free preview", request: "Request a book", sent: "Offer sent" };

async function route() {
  const name = (location.hash.replace(/^#\/?/, "") || "").split("/")[0];
  const fn = routes[name] ?? home;
  for (const a of document.querySelectorAll(".top nav a")) {
    a.toggleAttribute("aria-current", a.dataset.route === name);
    if (a.dataset.route === name) a.setAttribute("aria-current", "page");
  }
  document.title = (TITLES[name] ? TITLES[name] + " · " : "") + "Parallel Voices";
  await fn();
  window.scrollTo(0, 0);
  view.focus({ preventScroll: true });
}
addEventListener("hashchange", route);
route();
