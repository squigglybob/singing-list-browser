"""Parse plain-text copies of the ABRSM and Trinity syllabus song lists into
songs.js.

Inputs live under ``docs/``:
    docs/abrsm-grade7.txt
    docs/trinity-grade7.txt

Only Grade 7 is in scope right now. Drop more files into ``docs/`` and add
them to ``INPUTS`` to extend coverage.

ABRSM text format
-----------------
Headers, numbered song rows, and indented edition rows. Tabs are tolerated
between the number and the song header text:

    LIST A EARLY & SACRED
    1\tT. A. Arne Under the greenwood tree.
        Eb (c – g ): Celebrated Songs, Book 1 (Chester CH55317)

Some pages copy out with the song header and its first edition collapsed
onto a single line; we split those back apart. ``T he`` ↦ ``The`` is a
common PDF copy-paste artifact and is normalised before parsing.

Trinity text format
-------------------
Tab-separated rows, preceded by grouping headers and voice headings:

    Group A: Songs in a dramatic context
    A(i): Opera, operetta & oratorio
        Key & range\tComposer\tSong\tBook\tPublisher & code
    Soprano
    1\tBm; d'-f#"\tBach, J S\tQuia respexit (...)\tMagnificat in D\tBärenreiter BA5103-90

The header row inside a group is recognised and skipped (its first cell is
not a digit).

Schema (per song)
-----------------
{
  id, board, grade, list, list_title, voice,
  number, title, composer,
  editions: [
    { key, range_low, range_high, range_low_midi, range_high_midi,
      book, publisher_code, languages }
  ],
  min_range_low_midi, max_range_high_midi,  # derived
  book_ids: []                                # back-filled by parse_books.py
}
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pitch import note_to_midi

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
OUT = ROOT / "songs.js"


def slugify(*parts):
    return re.sub(r"[^a-z0-9]+", "-", " ".join(str(p) for p in parts).lower()).strip("-")


def parse_range(s: str):
    """Return (low, high, low_midi, high_midi). Either MIDI may be None."""
    if not s:
        return "", "", None, None
    parts = re.split(r"\s*[–\-]\s*", s.strip(), maxsplit=1)
    if len(parts) != 2:
        return s.strip(), "", None, None
    low, high = parts[0].strip(), parts[1].strip()
    return low, high, note_to_midi(_clean_note(low)), note_to_midi(_clean_note(high))


def _clean_note(s: str) -> str:
    """Strip alternate-key/range markup so the residue is a single note name."""
    s = re.sub(r"\s*\[[^\]]*\]\s*", " ", s)         # ``[E♭]`` alt-key tags
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s)          # ``(a'')`` alt notes
    s = re.sub(r"\s+or\s+.*$", "", s, flags=re.IGNORECASE)  # ``g" or Cm``
    s = re.split(r"\s*[/,]\s*", s, maxsplit=1)[0]
    return s.strip()


def _clean_text(text: str) -> str:
    """Repair PDF copy-paste artifacts (`T he` ↦ `The`, private-use glyphs)."""
    text = text.replace("", "'").replace("", "''")
    # The PDF inserts a stray space before the prime glyphs; remove it inside note names.
    text = re.sub(r"\b([A-Ga-g][#b♭♯]?)\s+(?=')", r"\1", text)
    return re.sub(r"\bT h(?=[a-z])", "Th", text)


# ---------------------------------------------------------------------------
# ABRSM
# ---------------------------------------------------------------------------

ABRSM_LIST_RE = re.compile(r"^LIST\s+([A-E])\b\s*:?\s*(.*)$", re.IGNORECASE)
ABRSM_SONG_RE = re.compile(r"^(?P<num>\d+)\.?\s+(?P<rest>.+)$")
# Edition: optional key, optional (range), then `:`, then book.
ABRSM_EDITION_RE = re.compile(
    r"^(?P<key>[^():]*)"
    r"(?:\s*\((?P<range>[^)]*?[-–][^)]*?)\))?"
    r"(?:[^():]*)"          # multi-key tail like ", G min or F min"
    r"\s*:\s*"
    r"(?P<book>.+)$"
)
ABRSM_VOICE_TAG_RE = re.compile(r"^\(([MF](?:/[MF])?)\)\s*(.*)$")


def parse_abrsm(text: str, grade: int) -> list[dict]:
    text = _clean_text(text)
    rows: list[dict] = []
    state = {"song": None, "list": "", "list_title": ""}

    def flush():
        s = state["song"]
        if s and s["editions"]:
            rows.append(s)
        state["song"] = None

    def start_song(num: int, composer: str, title: str, voice_tag: str):
        flush()
        state["song"] = {
            "id": slugify(
                "abrsm", f"g{grade}", state["list"] or "x",
                f"{num:04d}", composer[:24],
            ),
            "board": "ABRSM",
            "grade": grade,
            "list": state["list"],
            "list_title": state["list_title"],
            "voice": voice_tag,
            "number": num,
            "title": title,
            "composer": composer,
            "editions": [],
            "book_ids": [],
        }

    def add_edition(line: str) -> bool:
        if state["song"] is None:
            return False
        m = ABRSM_EDITION_RE.match(line)
        if not m:
            return False
        state["song"]["editions"].append(
            _make_edition(m.group("key"), m.group("range"), m.group("book"))
        )
        return True

    for raw in text.splitlines():
        if not raw.strip():
            continue
        line = raw.strip()
        leading_ws = raw[0].isspace()

        m = ABRSM_LIST_RE.match(line)
        if m:
            flush()
            state["list"] = m.group(1).upper()
            state["list_title"] = m.group(2).strip()
            continue

        if not leading_ws:
            m = ABRSM_SONG_RE.match(line)
            if m:
                num = int(m.group("num"))
                rest = m.group("rest").strip()
                composer, title, voice_tag, trailing = _parse_abrsm_song_rest(rest)
                start_song(num, composer, title, voice_tag)
                if trailing:
                    add_edition(trailing)
                continue

        if add_edition(line):
            continue

        # Continuation of previous edition's book text (wrapped lines).
        s = state["song"]
        if s and s["editions"]:
            s["editions"][-1]["book"] += " " + line

    flush()
    return rows


def _parse_abrsm_song_rest(rest: str) -> tuple[str, str, str, str]:
    """Split a song header's text into (composer, title, voice_tag, trailing_edition).

    The title typically ends with ``.``, optionally followed by a
    ``(M)``/``(F)`` voice tag and/or an inline first edition.
    """
    candidates = [
        i for i, c in enumerate(rest)
        if c == "." and (i == len(rest) - 1 or rest[i + 1] in (" ", "\t"))
    ]
    for idx in reversed(candidates):
        head = rest[:idx]
        tail = rest[idx + 1:].strip()
        voice_tag = ""
        m = ABRSM_VOICE_TAG_RE.match(tail)
        if m:
            voice_tag = m.group(1)
            tail = m.group(2).strip()
        split = _try_split_composer_title(head)
        if not split:
            continue
        if not tail:
            return split[0], split[1], voice_tag, ""
        if ABRSM_EDITION_RE.match(tail):
            return split[0], split[1], voice_tag, tail

    split = _try_split_composer_title(rest.rstrip("."))
    if split:
        return split[0], split[1], "", ""
    return rest.rstrip(".").strip(), "", "", ""


def _try_split_composer_title(s: str) -> tuple[str, str] | None:
    s = s.strip()
    if not s:
        return None
    m = re.match(r"^(?P<composer>.+?)\s+[–—]\s+(?P<title>.+)$", s)
    if m:
        return m.group("composer").strip(), m.group("title").strip()
    return _try_split_abrsm_composer_title(s)


def _try_split_abrsm_composer_title(rest: str) -> tuple[str, str] | None:
    rest = rest.rstrip(".").strip()
    tokens = rest.split()
    if len(tokens) < 2:
        return None
    for n in range(min(len(tokens) - 1, 8), 0, -1):
        composer_tokens = tokens[:n]
        title_tokens = tokens[n:]
        if not _is_valid_composer_tokens(composer_tokens):
            continue
        first = title_tokens[0]
        if not first or (not first[0].isupper() and first[0] not in "(\"'"):
            continue
        return " ".join(composer_tokens), " ".join(title_tokens)
    return None


_COMPOSER_PREFIXES = ("attrib.", "arr.", "trad.")
_COMPOSER_JOINERS = {"&", "and", ","}
_NAME_PARTICLES = {
    "di", "de", "del", "della", "da", "von", "van", "der", "den",
    "du", "la", "le", "el", "y",
}
_INITIAL_RE = re.compile(r"^[A-Z]\.$")
_NAME_TOKEN_RE = re.compile(
    r"^[A-Z][A-Za-zéíóúñöüäåØøæœ'-]+(?:/[A-Z][A-Za-zéíóúñöüäåØøæœ'-]+)?$"
)


def _normalize_composer_tokens(tokens: list[str]) -> list[str]:
    """Split off trailing commas so ``Gershwin,`` becomes ``[Gershwin, ',']``."""
    out = []
    for t in tokens:
        if len(t) > 1 and t.endswith(","):
            out.append(t[:-1])
            out.append(",")
        else:
            out.append(t)
    return out


def _is_valid_composer_tokens(tokens: list[str]) -> bool:
    """True if ``tokens`` looks like a complete composer credit.

    Rules per joiner-separated name part:
      * If the part contains initials (``A.``), it must end with at most one
        surname (allowing initial-only credits like ``G.`` in ``G. & I. Gershwin``).
      * The first name part may be up to 3 capitalised words, accommodating
        ``Andrew Lloyd Webber``. Subsequent parts are capped at 2 — that
        prevents the heuristic from absorbing title words after the last
        composer.
    A leading ``attrib.``/``arr.``/``trad.`` prefix on the first part is allowed.
    """
    tokens = _normalize_composer_tokens(tokens)
    if not tokens:
        return False

    parts: list[list[str]] = [[]]
    for t in tokens:
        if t in _COMPOSER_JOINERS:
            if not parts[-1]:
                return False
            parts.append([])
        else:
            parts[-1].append(t)
    if not parts[-1]:
        return False

    for i, part in enumerate(parts):
        if i == 0 and part and part[0].lower() in _COMPOSER_PREFIXES:
            part = part[1:]
        if not _is_valid_name_part(part, allow_three=(i == 0)):
            return False
    return True


def _is_valid_name_part(tokens: list[str], allow_three: bool = False) -> bool:
    if not tokens:
        return False
    initials = 0
    names = 0
    for t in tokens:
        if _INITIAL_RE.fullmatch(t):
            if names > 0:
                return False
            initials += 1
        elif _NAME_TOKEN_RE.fullmatch(t):
            names += 1
        elif t.lower() in _NAME_PARTICLES:
            continue
        else:
            return False
    if initials > 0:
        return names <= 1
    max_names = 3 if allow_three else 2
    return 1 <= names <= max_names


_LANGUAGES = {
    "Eng", "Ger", "Fr", "Ital", "Span", "Latin", "Cat", "Catalan",
    "Hebrew", "Heb", "Pol", "Polish", "Russ", "Russ cyrillic",
    "Russ Cyrillic", "Russian", "Ice", "Icelandic", "Welsh", "Nor",
    "Swed", "Czech", "Port", "Greek", "Dut", "German", "French",
    "Italian", "English", "Spanish", "Norwegian", "Swedish", "Hungarian",
    "Neapolitan dialect",
}


def _make_edition(key_str, range_str, book_str):
    low, high, low_m, high_m = parse_range(range_str or "")
    book = (book_str or "").strip()

    lang = ""
    m = re.search(r"\(([^)]+)\)\s*$", book)
    if m:
        inner = m.group(1).strip()
        parts = [p.strip() for p in inner.split("/")]
        if parts and all(p in _LANGUAGES for p in parts):
            lang = inner
            book = book[:m.start()].rstrip()

    return {
        "key": (key_str or "").strip(),
        "range_low": low,
        "range_high": high,
        "range_low_midi": low_m,
        "range_high_midi": high_m,
        "book": book,
        "languages": lang,
        "publisher_code": "",
    }


# ---------------------------------------------------------------------------
# Trinity
# ---------------------------------------------------------------------------

TRINITY_GROUP_RE = re.compile(r"^Group\s+([A-Z])(?:\((i|ii|iii|iv|v)\))?\s*:\s*(.+)$")
TRINITY_SUBGROUP_RE = re.compile(r"^([A-Z])\((i|ii|iii|iv|v)\)\s*:\s*(.+)$")
TRINITY_VOICES = {
    "soprano": "Soprano",
    "mezzo-soprano, alto and countertenor": "Mezzo/Alto/CT",
    "mezzo soprano, alto and countertenor": "Mezzo/Alto/CT",
    "alto": "Alto",
    "countertenor": "Countertenor",
    "tenor": "Tenor",
    "baritone and bass": "Bar/Bass",
    "baritone": "Baritone",
    "bass": "Bass",
}


def parse_trinity(text: str, grade: int) -> list[dict]:
    text = _clean_text(text)
    rows = []
    state = {"group": "", "subgroup": "", "subgroup_title": "", "voice": ""}

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue

        if "\t" in line and line.count("\t") >= 3:
            cells = [c.strip() for c in line.split("\t")]
            if not re.fullmatch(r"\d+", cells[0]):
                continue
            cells = cells + [""] * (6 - len(cells))
            num_s, key_range, composer, title, book, code = cells[:6]
            rows.append(_build_trinity_song(
                num_s, key_range, composer, title, book, code, state, grade
            ))
            continue

        m = TRINITY_GROUP_RE.match(line.strip())
        if m:
            state["group"] = m.group(1)
            if m.group(2):
                state["subgroup"] = f"{m.group(1)}({m.group(2)})"
            else:
                state["subgroup"] = m.group(1)
            state["subgroup_title"] = m.group(3).strip()
            state["voice"] = ""
            continue

        m = TRINITY_SUBGROUP_RE.match(line.strip())
        if m:
            state["group"] = m.group(1)
            state["subgroup"] = f"{m.group(1)}({m.group(2)})"
            state["subgroup_title"] = m.group(3).strip()
            state["voice"] = ""
            continue

        voice = TRINITY_VOICES.get(line.strip().lower())
        if voice:
            state["voice"] = voice
            continue

    return rows


def _build_trinity_song(num_s, key_range, composer, title, book, code, state, grade):
    key, range_str = "", ""
    m = re.match(r"^(?P<key>[^;]+);\s*(?P<range>.+)$", key_range)
    if m:
        key = m.group("key").strip()
        range_str = m.group("range").strip()
    else:
        # Some rows have only a range, no key.
        range_str = key_range.strip()

    # Strip trailing alternate-key tags like " [E♭]" from the range.
    range_str = re.sub(r"\s*\[[^\]]+\]\s*$", "", range_str).strip()
    low, high, low_m, high_m = parse_range(range_str)

    list_label = state["subgroup"] or state["group"] or ""
    list_title = state["subgroup_title"] or ""

    song_id = slugify(
        "trinity", f"g{grade}", list_label or "x",
        state["voice"] or "any", f"{int(num_s):04d}", composer[:20],
    )
    return {
        "id": song_id,
        "board": "Trinity",
        "grade": grade,
        "list": list_label,
        "list_title": list_title,
        "voice": state["voice"],
        "number": int(num_s),
        "title": title,
        "composer": composer,
        "editions": [{
            "key": key,
            "range_low": low,
            "range_high": high,
            "range_low_midi": low_m,
            "range_high_midi": high_m,
            "book": book,
            "languages": "",
            "publisher_code": code,
        }],
        "book_ids": [],
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def derive_range_aggregates(rows):
    for r in rows:
        lows = [e["range_low_midi"] for e in r["editions"] if e.get("range_low_midi") is not None]
        highs = [e["range_high_midi"] for e in r["editions"] if e.get("range_high_midi") is not None]
        r["min_range_low_midi"] = min(lows) if lows else None
        r["max_range_high_midi"] = max(highs) if highs else None


def load_existing_book_ids(path):
    if not path.exists():
        return {}
    text = path.read_text()
    m = re.search(r"window\.SONGS\s*=\s*(\[.*\]);?\s*$", text, re.DOTALL)
    if not m:
        return {}
    try:
        existing = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
    return {r["id"]: r.get("book_ids", []) for r in existing if "id" in r}


def summarize(rows):
    from collections import Counter
    by_group = Counter(
        (r["board"], r["grade"], r.get("list", ""), r.get("voice", "") or "—")
        for r in rows
    )
    total_editions = sum(len(r["editions"]) for r in rows)
    unparsed = 0
    for r in rows:
        for e in r["editions"]:
            if e["range_low_midi"] is None or e["range_high_midi"] is None:
                unparsed += 1
    for (board, grade, lst, voice), n in sorted(by_group.items()):
        print(f"  {board} G{grade} list={lst} voice={voice}: {n}")
    print(f"Total: {len(rows)} songs, {total_editions} editions, {unparsed} unparsed ranges")


INPUTS = [
    ("abrsm-grade7.txt", parse_abrsm, 7),
    ("trinity-grade7.txt", parse_trinity, 7),
]


def main():
    DOCS_DIR.mkdir(exist_ok=True)
    prior = load_existing_book_ids(OUT)
    all_rows = []
    missing = []

    for filename, parser, grade in INPUTS:
        path = DOCS_DIR / filename
        if not path.exists():
            missing.append(filename)
            continue
        print(f"Parsing {filename}...")
        all_rows.extend(parser(path.read_text(encoding="utf-8"), grade))

    for r in all_rows:
        if r["id"] in prior:
            r["book_ids"] = prior[r["id"]]

    derive_range_aggregates(all_rows)
    summarize(all_rows)

    if missing:
        print(f"\nMissing text files (skipped): {', '.join(missing)}")
        print(f"Drop them into {DOCS_DIR.relative_to(ROOT)}/ and re-run.")

    OUT.write_text("window.SONGS = " + json.dumps(all_rows, indent=2, ensure_ascii=False) + ";\n")
    print(f"\nWrote {OUT.name} ({len(all_rows)} songs)")


if __name__ == "__main__":
    main()
