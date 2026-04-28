"""Parse saved chimesmusic.com pages into ``books.js`` and back-fill
``book_ids`` on the rows in ``songs.js``.

Expected inputs (saved HTML in ``html/``):
    abrsm_g7_list_a.html  abrsm_g7_list_b.html
    abrsm_g8_list_a.html  abrsm_g8_list_b.html
    trinity_g7.html       trinity_g8.html

(Name them after whichever pages you saved; the filename is used only for
logging. Any ``.html`` file in ``html/`` will be processed.)

For each page we:
  1. Find the songs listed on that page (title + composer).
  2. Find the songbooks linked from that page (title + URL).
  3. Match each song to a row in ``songs.js`` by normalised title + surname.
  4. Append every book on the page to every matched song's ``book_ids``.

Step 4 is deliberately coarse: chimesmusic pages bundle 'books containing
pieces from this list', so most books on a page do contain most pieces on
the page. Edit ``books.js`` / ``songs.js`` by hand if you want finer detail.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
HTML_DIR = ROOT / "html"
SONGS_PATH = ROOT / "songs.js"
BOOKS_PATH = ROOT / "books.js"


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def norm_title(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[‘’'\"`]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def surname(composer: str) -> str:
    composer = re.sub(r"\(.*?\)", "", composer).strip()
    tokens = [t for t in re.split(r"[\s,]+", composer) if t]
    if not tokens:
        return ""
    if "," in composer:
        return tokens[0].lower()
    return tokens[-1].lower()


def load_songs() -> list[dict]:
    if not SONGS_PATH.exists():
        return []
    text = SONGS_PATH.read_text()
    m = re.search(r"window\.SONGS\s*=\s*(\[.*\]);?\s*$", text, re.DOTALL)
    if not m:
        return []
    return json.loads(m.group(1))


def write_songs(rows: list[dict]) -> None:
    SONGS_PATH.write_text(
        "window.SONGS = " + json.dumps(rows, indent=2, ensure_ascii=False) + ";\n"
    )


def write_books(books: list[dict]) -> None:
    BOOKS_PATH.write_text(
        "window.BOOKS = " + json.dumps(books, indent=2, ensure_ascii=False) + ";\n"
    )


def extract_songs_from_page(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Return a list of (title, composer) from a chimesmusic syllabus page.

    Chimesmusic marks up each piece as a heading followed by the composer,
    e.g. ``<h3>Come away, death</h3><p>Sibelius</p>``. Layouts vary, so we
    fall back to a permissive scan of table rows and list items.
    """
    results: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for h in soup.select("h2, h3, h4"):
        title = h.get_text(" ", strip=True)
        if not title or len(title) > 200:
            continue
        sib = h.find_next_sibling()
        composer = ""
        if sib and sib.name in ("p", "div", "span"):
            composer = sib.get_text(" ", strip=True)
        if _looks_like_song(title, composer):
            key = (norm_title(title), surname(composer))
            if key not in seen:
                seen.add(key)
                results.append((title, composer))

    for row in soup.select("tr"):
        cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
        if len(cells) >= 2 and _looks_like_song(cells[0], cells[1]):
            key = (norm_title(cells[0]), surname(cells[1]))
            if key not in seen:
                seen.add(key)
                results.append((cells[0], cells[1]))

    return results


def _looks_like_song(title: str, composer: str) -> bool:
    if not title or not composer:
        return False
    if len(title) > 200 or len(composer) > 200:
        return False
    junk = ("click here", "add to basket", "view cart", "search", "menu", "home")
    lowered = (title + " " + composer).lower()
    if any(j in lowered for j in junk):
        return False
    return bool(re.search(r"[A-Za-z]", title)) and bool(re.search(r"[A-Za-z]", composer))


def extract_books_from_page(soup: BeautifulSoup) -> list[dict]:
    """Pull every product link on the page that looks like a songbook.

    Chimesmusic product URLs live under /shop/ or /products/. We de-dup by URL.
    """
    books: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"/(shop|products|product|store)/", href):
            continue
        text = a.get_text(" ", strip=True)
        if not text or len(text) < 5 or len(text) > 200:
            continue
        if text.lower() in ("more info", "view", "buy", "add to cart", "click here"):
            continue
        parsed = urlparse(href)
        if not parsed.scheme:
            href = "https://www.chimesmusic.com" + (href if href.startswith("/") else "/" + href)
        book_id = slugify(text)[:80]
        if not book_id:
            continue
        books.setdefault(book_id, {
            "id": book_id,
            "title": text,
            "publisher": "",
            "isbn": "",
            "url": href,
            "notes": "",
        })
    return list(books.values())


def match_song(page_song: tuple[str, str], songs_by_key: dict) -> dict | None:
    t_norm = norm_title(page_song[0])
    s_norm = surname(page_song[1])
    if (t_norm, s_norm) in songs_by_key:
        return songs_by_key[(t_norm, s_norm)]
    for (t, s), row in songs_by_key.items():
        if t == t_norm:
            return row
    return None


def main() -> int:
    HTML_DIR.mkdir(exist_ok=True)
    songs = load_songs()
    if not songs:
        print("No songs.js yet. Run parse_pdfs.py first.")
        return 1

    songs_by_key = {(norm_title(s["title"]), surname(s["composer"])): s for s in songs}

    books_by_id: dict[str, dict] = {}
    unmatched: list[tuple[str, str, str]] = []
    pages = sorted(HTML_DIR.glob("*.html"))

    if not pages:
        print(f"No .html files in {HTML_DIR.relative_to(ROOT)}/. Nothing to do.")
        write_books([])
        return 0

    for page_path in pages:
        print(f"Parsing {page_path.name}...")
        soup = BeautifulSoup(page_path.read_text(), "html.parser")
        page_songs = extract_songs_from_page(soup)
        page_books = extract_books_from_page(soup)
        for b in page_books:
            books_by_id.setdefault(b["id"], b)
        page_book_ids = [b["id"] for b in page_books]

        matched = 0
        for title, composer in page_songs:
            row = match_song((title, composer), songs_by_key)
            if row is None:
                unmatched.append((page_path.name, title, composer))
                continue
            matched += 1
            for bid in page_book_ids:
                if bid not in row["book_ids"]:
                    row["book_ids"].append(bid)
        print(f"  {len(page_songs)} songs on page, {matched} matched, {len(page_books)} books")

    write_songs(songs)
    write_books(sorted(books_by_id.values(), key=lambda b: b["title"].lower()))
    print(f"\nWrote {BOOKS_PATH.relative_to(ROOT)} ({len(books_by_id)} books)")
    print(f"Updated {SONGS_PATH.relative_to(ROOT)} with book_ids")

    if unmatched:
        print(f"\n{len(unmatched)} unmatched song(s) — add to syllabus rows by hand or adjust matching:")
        for fn, title, composer in unmatched[:40]:
            print(f"  [{fn}] {title} — {composer}")
        if len(unmatched) > 40:
            print(f"  ... and {len(unmatched) - 40} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
