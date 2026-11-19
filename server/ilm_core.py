"""ilm core: read a book in any supported format, keep it searchable, track which ideas the reader has met.

Standard library only. Optional extras, imported lazily:
  pypdf                    - PDF files
  youtube-transcript-api   - YouTube captions
All data lives in one SQLite file on the user's machine.
"""
import html.parser
import json
import os
import posixpath
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

TARGET_CHARS = 1800   # preferred fragment size
MAX_CHARS = 2600      # hard ceiling before a fragment is split
MAX_FILE_BYTES = 200 * 1024 * 1024    # refuse source files larger than this
MAX_PART_BYTES = 50 * 1024 * 1024     # refuse a single unpacked chapter larger than this
MAX_BOOK_CHARS = 30 * 1000 * 1000     # refuse sources that unpack to more text than this
FOLLOW_UP_DAYS = 14                   # stop asking about an idea after this long
TEXT_EXT = {".txt", ".md", ".markdown", ".rst"}
HTML_EXT = {".html", ".htm"}
SUPPORTED = sorted(TEXT_EXT | HTML_EXT | {".pdf", ".epub", ".fb2", ".docx"})
AUDIO_EXT = {".mp3", ".m4a", ".m4b", ".wav", ".ogg", ".flac", ".aac", ".opus"}
HEADING_RE = re.compile(
    r"^\s*(глава|часть|раздел|chapter|part|section|bob|bo['‘’`]?lim|qism)\s+(\d+|[IVXLCDM]+)\b.{0,80}$", re.IGNORECASE
)
YT_ID_RE = re.compile(r"(?:youtu\.be/|[?&]v=|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")


class IlmError(Exception):
    """An error whose message is safe and useful to show to the assistant and the user."""


# ---------------------------------------------------------------- text helpers

def _clean(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\u00ad", "")     # no-break space, soft hyphen
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_text(text):
    """Split long text into fragments of about TARGET_CHARS on paragraph, then sentence, borders."""
    text = _clean(text)
    if len(text) <= MAX_CHARS:
        return [text] if text else []
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) < 2:
        paras = [p for p in text.split("\n") if p.strip()]
    pieces = []
    for p in paras:
        if len(p) <= MAX_CHARS:
            pieces.append(p)
            continue
        buf = ""
        for s in re.split(r"(?<=[.!?…])\s+", p):
            if len(s) > MAX_CHARS:               # no sentence borders at all
                cut = [s[i:i + MAX_CHARS] for i in range(0, len(s), MAX_CHARS)]
                pieces.extend(cut[:-1])
                s = cut[-1]
            if buf and len(buf) + len(s) > TARGET_CHARS:
                pieces.append(buf)
                buf = s
            else:
                buf = (buf + " " + s).strip()
        if buf:
            pieces.append(buf)
    out, buf = [], ""
    for p in pieces:
        if buf and len(buf) + len(p) > MAX_CHARS:
            out.append(buf)
            buf = p
        else:
            buf = (buf + "\n\n" + p).strip()
        if len(buf) >= TARGET_CHARS:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def _timestamp(seconds):
    s = int(seconds)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _stems(query):
    """Crude stems for prefix search, so that word forms match (связи -> связ*, habits -> habi*)."""
    out = []
    for w in re.findall(r"\w+", query.lower()):
        if len(w) < 3 or w.isdigit():
            continue
        stem = w if len(w) <= 4 else w[: max(4, len(w) - 2)]
        if stem not in out:
            out.append(stem)
    return out[:24]


class _HtmlText(html.parser.HTMLParser):
    SKIP = {"script", "style", "head", "nav"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.heading, self._skip, self._in_h, self._h = [], "", 0, False, []

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self._skip = 0           # an unclosed <head> or <nav> must not swallow the text
        if tag in self.SKIP:
            self._skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n\n")
        if tag in ("h1", "h2", "h3") and not self.heading:
            self._in_h, self._h = True, []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag in ("h1", "h2", "h3") and self._in_h:
            self._in_h = False
            self.heading = " ".join("".join(self._h).split())
        if tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._in_h:
            self._h.append(data)


def _html_to_text(markup):
    p = _HtmlText()
    p.feed(markup)
    return p.heading, _clean("".join(p.parts))


def _decode(raw):
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1")


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _local(tag):
    return tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------- extractors
# Each returns (title, units, mergeable): units = [(location, text)].
# mergeable units (PDF pages, caption lines) are small and get joined into fragments.

def _read_text_file(path):
    text = _decode(_read_bytes(path))
    units, loc, buf = [], "", []
    for line in text.replace("\r\n", "\n").split("\n"):
        if HEADING_RE.match(line) and len(line.strip()) < 100:
            if "".join(buf).strip():
                units.append((loc, "\n".join(buf)))
            loc, buf = line.strip(), [line]
        else:
            buf.append(line)
    if "".join(buf).strip():
        units.append((loc, "\n".join(buf)))
    return "", units, False


def _read_html_file(path):
    heading, text = _html_to_text(_decode(_read_bytes(path)))
    return heading, [("", text)], False


def _strip_running_lines(pages):
    """Drop headers/footers (a line repeated at the edge of many pages) and bare page numbers."""
    def norm(line):
        return re.sub(r"[\d\s]+", "", line).lower()

    seen = {}
    for lines in pages:
        edge = [l for l in lines if l.strip()]
        for key in {norm(l) for l in edge[:2] + edge[-2:]}:
            if len(key) >= 3:
                seen[key] = seen.get(key, 0) + 1
    repeated = {k for k, n in seen.items() if n > max(3, 0.4 * len(pages))}

    def junk(line):
        t = line.strip()
        return not t or t.isdigit() or norm(t) in repeated

    out = []
    for lines in pages:
        a, b = 0, len(lines)
        while a < b and junk(lines[a]):
            a += 1
        while b > a and junk(lines[b - 1]):
            b -= 1
        out.append(lines[a:b])
    return out


def _join_pdf_lines(lines):
    text = "\n".join(l.rstrip() for l in lines)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)                     # undo end-of-line hyphenation
    return re.sub(r"(?<![.!?:;…»\"”])\n(?!\n)", " ", text)           # re-join wrapped lines


def _read_pdf(path):
    try:
        import pypdf
    except ImportError:
        raise IlmError("Reading PDF needs the 'pypdf' package. Install it with:  pip install pypdf  - then load the book again.")
    try:
        reader = pypdf.PdfReader(path)
        if reader.is_encrypted:
            reader.decrypt("")
        pages = [(page.extract_text() or "").split("\n") for page in reader.pages]
        units = [(i, _join_pdf_lines(lines)) for i, lines in enumerate(_strip_running_lines(pages), 1)]
        title = ""
        try:
            title = (reader.metadata.title or "").strip() if reader.metadata else ""
            if re.search(r"^(microsoft word|untitled)|\.(docx?|pdf|rtf|indd|qxd|tex)$", title, re.IGNORECASE):
                title = ""      # a file name left by the converter, not a book title
        except Exception:
            pass
    except IlmError:
        raise
    except Exception as e:
        raise IlmError(f"Could not read this PDF ({type(e).__name__}: {e}). It may be damaged or password-protected.")
    chars = sum(len(t.strip()) for _, t in units)
    if not units or chars < 20 * len(units):
        raise IlmError(
            "This PDF has no text layer - its pages are scanned images, so there is no text to read. "
            "Use a text version of the book (EPUB, FB2, DOCX or a PDF where text can be selected)."
        )
    return title, units, True


def _read_epub(path):
    try:
        with zipfile.ZipFile(path) as z:
            container = ET.fromstring(z.read("META-INF/container.xml"))
            opf_path = next(e.attrib["full-path"] for e in container.iter() if _local(e.tag) == "rootfile")
            opf = ET.fromstring(z.read(opf_path))
            base = posixpath.dirname(opf_path)
            title, manifest, spine = "", {}, []
            for e in opf.iter():
                tag = _local(e.tag)
                if tag == "title" and not title:
                    title = (e.text or "").strip()
                elif tag == "item":
                    manifest[e.attrib.get("id")] = e.attrib.get("href", "")
                elif tag == "itemref":
                    spine.append(e.attrib.get("idref"))
            units = []
            names, done = set(z.namelist()), set()
            for n, idref in enumerate(spine, 1):
                href = urllib.parse.unquote(manifest.get(idref, "").split("#")[0])
                name = posixpath.normpath(posixpath.join(base, href)) if href else ""
                if name not in names or name in done or z.getinfo(name).file_size > MAX_PART_BYTES:
                    continue
                done.add(name)
                heading, text = _html_to_text(_decode(z.read(name)))
                if text:
                    units.append((heading or f"section {n}", text))
    except (KeyError, StopIteration, zipfile.BadZipFile, ET.ParseError) as e:
        raise IlmError(f"Could not read this EPUB ({type(e).__name__}). The file may be damaged or DRM-protected.")
    return title, units, False


def _read_fb2(path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise IlmError(f"Could not read this FB2 file ({e}).")
    title = ""
    for e in root.iter():
        if _local(e.tag) == "book-title":
            title = " ".join("".join(e.itertext()).split())
            break
    units = []

    def walk(section, inherited):
        loc, paras = inherited, []
        for child in section:
            tag = _local(child.tag)
            if tag == "title":
                loc = " ".join("".join(child.itertext()).split()) or inherited
            elif tag != "section":
                t = " ".join("".join(child.itertext()).split())
                if t:
                    paras.append(t)
        if paras:
            units.append((loc, "\n\n".join(paras)))
        for child in section:
            if _local(child.tag) == "section":
                walk(child, loc)

    for e in root:
        if _local(e.tag) == "body":
            walk(e, "")
    return title, units, False


def _read_docx(path):
    try:
        with zipfile.ZipFile(path) as z:
            doc = ET.fromstring(z.read("word/document.xml"))
            title = ""
            if "docProps/core.xml" in z.namelist():
                for e in ET.fromstring(z.read("docProps/core.xml")).iter():
                    if _local(e.tag) == "title":
                        title = (e.text or "").strip()
    except (KeyError, zipfile.BadZipFile, ET.ParseError) as e:
        raise IlmError(f"Could not read this DOCX file ({type(e).__name__}).")
    units, loc, buf = [], "", []
    for p in doc.iter():
        if _local(p.tag) != "p":
            continue
        text = "".join(t.text or "" for t in p.iter() if _local(t.tag) == "t").strip()
        if not text:
            continue
        style = next((v for s in p.iter() if _local(s.tag) == "pStyle" for k, v in s.attrib.items() if _local(k) == "val"), "")
        if re.match(r"(heading|заголовок|title)", style, re.IGNORECASE) and len(text) < 120:
            if buf:
                units.append((loc, "\n\n".join(buf)))
            loc, buf = text, [text]
        else:
            buf.append(text)
    if buf:
        units.append((loc, "\n\n".join(buf)))
    return title, units, False


def fetch_youtube_transcript(video_id):
    """Return captions as [{'start': seconds, 'text': str}]. Uses captions that already exist; no audio is downloaded."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        raise IlmError(
            "Reading YouTube captions needs the 'youtube-transcript-api' package. "
            "Install it with:  pip install youtube-transcript-api  - then load the video again."
        )
    try:
        if hasattr(YouTubeTranscriptApi, "get_transcript") and not hasattr(YouTubeTranscriptApi, "fetch"):
            listing = list(YouTubeTranscriptApi.list_transcripts(video_id))       # old API (< 1.0)
        else:
            listing = list(YouTubeTranscriptApi().list(video_id))
        if not listing:
            raise IlmError("This video has no captions, so there is no text to read.")
        listing.sort(key=lambda t: bool(getattr(t, "is_generated", False)))    # human-made captions first
        fetched = listing[0].fetch()
        rows = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else fetched
        return [{"start": float(r["start"]), "text": r["text"]} for r in rows]
    except IlmError:
        raise
    except Exception as e:
        raise IlmError(
            f"Could not get captions for this video ({type(e).__name__}). "
            "The video may have no captions, be private, or YouTube may be blocking requests from this network."
        )


def _youtube_title(video_id):
    try:
        url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(
            f"https://www.youtube.com/watch?v={video_id}", safe="")
        with urllib.request.urlopen(url, timeout=8) as r:
            return json.loads(r.read().decode("utf-8")).get("title", "")
    except Exception:
        return ""


READERS = {".pdf": _read_pdf, ".epub": _read_epub, ".fb2": _read_fb2, ".docx": _read_docx}
READERS.update({e: _read_text_file for e in TEXT_EXT})
READERS.update({e: _read_html_file for e in HTML_EXT})


def _make_chunks(units, mergeable, kind):
    """Turn extractor units into [(location, text)] fragments."""
    chunks = []
    if not mergeable:
        for loc, text in units:
            for piece in _split_text(text):
                chunks.append((loc, piece))
        return [(loc or f"fragment {i}", text) for i, (loc, text) in enumerate(chunks, 1)]

    def label(first, last):
        if kind == "youtube":
            return _timestamp(first)
        return f"p. {first}" if first == last else f"p. {first}-{last}"

    buf, first, last = "", None, None

    def flush():
        nonlocal buf, first, last
        if buf.strip():
            for piece in _split_text(buf):
                chunks.append((label(first, last), piece))
        buf, first, last = "", None, None

    for loc, text in units:
        text = _clean(text)
        if not text:
            continue
        if buf and len(buf) + len(text) > MAX_CHARS:
            flush()
        if first is None:
            first = loc
        last = loc
        buf = (buf + ("\n\n" if kind == "pdf" else " ") + text).strip()
        if len(buf) >= TARGET_CHARS:
            flush()
    flush()
    return chunks


# ---------------------------------------------------------------- storage

SCHEMA = """
CREATE TABLE IF NOT EXISTS books(
  id INTEGER PRIMARY KEY, source_key TEXT UNIQUE, title TEXT, kind TEXT,
  total_chunks INTEGER, mapped_upto INTEGER DEFAULT 0, active INTEGER DEFAULT 0, created_at REAL);
CREATE TABLE IF NOT EXISTS chunks(
  book_id INTEGER, seq INTEGER, location TEXT, text TEXT, PRIMARY KEY(book_id, seq));
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, book_id UNINDEXED, seq UNINDEXED, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS concepts(
  id INTEGER PRIMARY KEY, book_id INTEGER, name TEXT, summary TEXT, chapter TEXT, location TEXT,
  author_example TEXT, use_when TEXT DEFAULT '', status TEXT DEFAULT 'new', met_count INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, concept_id INTEGER, kind TEXT, situation TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, text TEXT, created_at REAL);
"""


class Store:
    def __init__(self, data_dir):
        os.makedirs(data_dir, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(data_dir, "ilm.db"))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ---- helpers
    def _active(self, required=True):
        row = self.db.execute("SELECT * FROM books WHERE active=1").fetchone()
        if not row and required:
            raise IlmError("No book is loaded yet. Ask the user for a book file or a YouTube link and call ilm_load_source.")
        return row

    def _activate(self, book_id):
        with self.db:
            self.db.execute("UPDATE books SET active=0")
            self.db.execute("UPDATE books SET active=1 WHERE id=?", (book_id,))

    def _counts(self, book_id):
        counts = {"applied": 0, "met": 0, "new": 0}
        for r in self.db.execute("SELECT status, COUNT(*) n FROM concepts WHERE book_id=? GROUP BY status", (book_id,)):
            counts[r["status"]] = r["n"]
        return counts

    # ---- sources
    def load_source(self, source, title=None, confirm_switch=False):
        source = (source or "").strip().strip('"').strip("'")
        yt = YT_ID_RE.search(source) if re.match(r"https?://", source) else None
        if yt:
            key, kind, ext = "youtube:" + yt.group(1), "youtube", ""
        elif re.match(r"https?://", source):
            raise IlmError("Only YouTube links are supported as web sources. For anything else, give a file on this computer.")
        else:
            path = os.path.abspath(os.path.expanduser(source))
            ext = os.path.splitext(path)[1].lower()
            if not os.path.isfile(path):
                raise IlmError(f"File not found: {path}")
            if ext in AUDIO_EXT:
                raise IlmError("Audio files are not supported yet: this version reads text and YouTube captions only.")
            if ext not in READERS:
                raise IlmError(f"Unsupported file type '{ext}'. Supported: {', '.join(SUPPORTED)}, or a YouTube link.")
            if os.path.getsize(path) > MAX_FILE_BYTES:
                raise IlmError("This file is too large to be a book (over 200 MB).")
            key, kind = os.path.normcase(path), ext.lstrip(".")

        active = self._active(required=False)
        existing = self.db.execute("SELECT * FROM books WHERE source_key=?", (key,)).fetchone()
        if active and (not existing or existing["id"] != active["id"]) and not confirm_switch:
            return {
                "loaded": False, "needs_confirmation": True, "current_book": active["title"],
                "message": "Another book is active. Tell the user: switching makes the new source the active book; "
                           "progress on the current book is kept and they can return to it later; what you remember "
                           "about them stays. If they agree, call ilm_load_source again with confirm_switch=true.",
            }
        if existing:
            self._activate(existing["id"])
            return {"loaded": True, "returned_to_existing": True, "title": existing["title"],
                    "chunks": existing["total_chunks"], "progress": self._counts(existing["id"])}

        if kind == "youtube":
            rows = fetch_youtube_transcript(yt.group(1))
            found, units, mergeable = "", [(r["start"], r["text"].replace("\n", " ")) for r in rows], True
            if not title:
                found = _youtube_title(yt.group(1)) or f"YouTube video {yt.group(1)}"
        else:
            try:
                found, units, mergeable = READERS[ext](path)
            except IlmError:
                raise
            except Exception as e:
                raise IlmError(f"Could not read this file ({type(e).__name__}). "
                               "It may be damaged or saved in an unusual encoding.")
            if not found or len(found) < 3:
                found = re.sub(r"[_\s]+", " ", os.path.splitext(os.path.basename(path))[0]).strip()
        if sum(len(t) for _, t in units) > MAX_BOOK_CHARS:
            raise IlmError("This source holds far more text than a book (over 30 million characters); not loaded.")
        chunks = _make_chunks(units, mergeable, kind)
        if not chunks:
            raise IlmError("No readable text was found in this source.")
        with self.db:
            cur = self.db.execute(
                "INSERT INTO books(source_key,title,kind,total_chunks,created_at) VALUES(?,?,?,?,?)",
                (key, title or found, kind, len(chunks), time.time()))
            book_id = cur.lastrowid
            self.db.executemany("INSERT INTO chunks VALUES(?,?,?,?)",
                                [(book_id, i, loc, text) for i, (loc, text) in enumerate(chunks)])
            self.db.executemany("INSERT INTO chunks_fts(text,book_id,seq) VALUES(?,?,?)",
                                [(text, book_id, i) for i, (_, text) in enumerate(chunks)])
        self._activate(book_id)
        return {
            "loaded": True, "title": title or found, "kind": kind, "chunks": len(chunks),
            "characters": sum(len(t) for _, t in chunks),
            "next_step": "Build the first part of the idea map now: call ilm_read_chunks, then ilm_save_concepts. "
                         "Map the first two portions now and later ones gradually; do not read the whole book at once.",
        }

    def books(self):
        return {"books": [
            {"id": b["id"], "title": b["title"], "kind": b["kind"], "active": bool(b["active"]),
             "progress": self._counts(b["id"])}
            for b in self.db.execute("SELECT * FROM books ORDER BY id")]}

    def switch_book(self, book_id):
        row = self.db.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if not row:
            raise IlmError(f"No book with id {book_id}. Call ilm_books to see the list.")
        self._activate(row["id"])
        return {"active": row["title"], "progress": self._counts(row["id"])}

    # ---- idea map
    def read_chunks(self, start=None, count=12):
        book = self._active()
        start = book["mapped_upto"] if start is None else max(0, int(start))
        count = max(1, min(int(count or 12), 50))
        rows = self.db.execute(
            "SELECT seq, location, text FROM chunks WHERE book_id=? AND seq>=? ORDER BY seq LIMIT ?",
            (book["id"], start, count)).fetchall()
        nxt = rows[-1]["seq"] + 1 if rows else None
        return {"chunks": [dict(r) for r in rows], "total_chunks": book["total_chunks"],
                "next_start": nxt if nxt is not None and nxt < book["total_chunks"] else None}

    def save_concepts(self, concepts, mapped_upto=0):
        book = self._active()
        ids = []
        known = {r["name"].casefold(): r["id"] for r in
                 self.db.execute("SELECT id, name FROM concepts WHERE book_id=?", (book["id"],))}
        with self.db:
            for c in concepts or []:
                name, summary = (c.get("name") or "").strip(), (c.get("summary") or "").strip()
                if not name or not summary:
                    raise IlmError("Every concept needs a 'name' and a 'summary'.")
                if name.casefold() in known:
                    ids.append(known[name.casefold()])
                    continue
                cur = self.db.execute(
                    "INSERT INTO concepts(book_id,name,summary,use_when,chapter,location,author_example) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (book["id"], name, summary, (c.get("use_when") or "").strip(), (c.get("chapter") or "").strip(),
                     (c.get("location") or "").strip(), (c.get("author_example") or "").strip()))
                ids.append(cur.lastrowid)
                known[name.casefold()] = cur.lastrowid
            upto = max(book["mapped_upto"], min(int(mapped_upto or 0), book["total_chunks"]))
            self.db.execute("UPDATE books SET mapped_upto=? WHERE id=?", (upto, book["id"]))
        return {"concept_ids": ids, "mapped_chunks": upto, "total_chunks": book["total_chunks"],
                "mapping_complete": upto >= book["total_chunks"]}

    def search(self, query, limit=4):
        book = self._active()
        stems = _stems(query or "")
        if not stems:
            return {"passages": [], "concepts": []}
        match = " OR ".join(f'"{s}"*' for s in stems)
        limit = max(1, min(int(limit or 4), 10))
        rows = self.db.execute(
            "SELECT c.seq, c.location, c.text FROM chunks_fts f JOIN chunks c ON c.book_id=f.book_id AND c.seq=f.seq "
            "WHERE chunks_fts MATCH ? AND f.book_id=? ORDER BY bm25(chunks_fts) LIMIT ?",
            (match, book["id"], limit)).fetchall()
        scored = []
        for c in self.db.execute("SELECT * FROM concepts WHERE book_id=?", (book["id"],)).fetchall():
            hay = " ".join((c["name"], c["summary"], c["use_when"], c["chapter"], c["author_example"])).lower()
            score = sum(1 for s in stems if re.search(r"\b" + re.escape(s), hay))
            if score:
                scored.append((score, c))
        scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        concepts = []
        for _, c in scored[:5]:
            seen = [r["situation"] for r in self.db.execute(
                "SELECT situation FROM events WHERE concept_id=? AND situation<>'' ORDER BY id DESC LIMIT 2",
                (c["id"],))]
            concepts.append({"id": c["id"], "name": c["name"], "summary": c["summary"], "use_when": c["use_when"],
                             "chapter": c["chapter"], "location": c["location"],
                             "author_example": c["author_example"], "status": c["status"],
                             "user_situations": seen})
        return {"passages": [dict(r) for r in rows], "concepts": concepts}

    # ---- progress and memory
    def mark(self, concept_id, status, situation=""):
        if status not in ("met", "applied"):
            raise IlmError("status must be 'met' or 'applied'.")
        c = self.db.execute("SELECT * FROM concepts WHERE id=?", (concept_id,)).fetchone()
        if not c:
            raise IlmError(f"No concept with id {concept_id}. Use ilm_search or ilm_progress to get ids.")
        new_status = "applied" if status == "applied" or c["status"] == "applied" else "met"
        with self.db:
            self.db.execute("UPDATE concepts SET status=?, met_count=met_count+? WHERE id=?",
                            (new_status, 1 if status == "met" else 0, concept_id))
            self.db.execute("INSERT INTO events(concept_id,kind,situation,created_at) VALUES(?,?,?,?)",
                            (concept_id, status, (situation or "")[:500], time.time()))
        return {"concept": c["name"], "status": new_status}

    def progress(self):
        book = self._active()
        rows = self.db.execute(
            "SELECT id,name,chapter,location,status FROM concepts WHERE book_id=? ORDER BY id", (book["id"],)).fetchall()
        return {"book": book["title"], "counts": self._counts(book["id"]),
                "mapped_chunks": book["mapped_upto"], "total_chunks": book["total_chunks"],
                "concepts": [dict(r) for r in rows]}

    def remember(self, note):
        note = (note or "").strip()
        if not note:
            raise IlmError("The note is empty.")
        note = note[:500]
        if self.db.execute("SELECT 1 FROM notes WHERE text=?", (note,)).fetchone():
            return {"saved": True, "already_known": True}
        with self.db:
            self.db.execute("INSERT INTO notes(text,created_at) VALUES(?,?)", (note, time.time()))
        return {"saved": True}

    def status(self):
        book = self._active(required=False)
        notes = [r["text"] for r in self.db.execute("SELECT text FROM notes ORDER BY id DESC LIMIT 40")][::-1]
        if not book:
            return {"book": None, "follow_up": None, "about_user": notes}
        ev = self.db.execute(
            "SELECT c.id, c.name, e.situation, e.created_at FROM events e JOIN concepts c ON c.id=e.concept_id "
            "WHERE c.book_id=? AND e.kind='met' AND c.status='met' AND e.created_at>? ORDER BY e.id DESC LIMIT 1",
            (book["id"], time.time() - FOLLOW_UP_DAYS * 86400)).fetchone()
        follow = None
        if ev:
            follow = {"concept_id": ev["id"], "concept": ev["name"], "situation": ev["situation"],
                      "days_ago": int((time.time() - ev["created_at"]) // 86400)}
        return {
            "book": {"id": book["id"], "title": book["title"], "kind": book["kind"],
                     "total_chunks": book["total_chunks"], "mapped_chunks": book["mapped_upto"],
                     "mapping_complete": book["mapped_upto"] >= book["total_chunks"],
                     "concepts": self._counts(book["id"])},
            "follow_up": follow, "about_user": notes,
        }

    def delete_all(self, confirm=False):
        if not confirm:
            raise IlmError("Nothing was deleted. This erases every book, all progress and everything remembered "
                           "about the user. Ask the user to confirm, then call again with confirm=true.")
        with self.db:
            for t in ("books", "chunks", "chunks_fts", "concepts", "events", "notes"):
                self.db.execute(f"DROP TABLE IF EXISTS {t}")
        self.db.executescript(SCHEMA)
        self.db.execute("VACUUM")        # rewrite the file so that no deleted text stays in it
        return {"deleted": True}
