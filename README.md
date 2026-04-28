# UK Singing Grades — Repertoire Browser

A local, offline static site for browsing ABRSM and Trinity Singing syllabus
song lists (Grades 7 & 8) with a "fits my voice" pitch-range filter.

## Using it

Open `index.html` in any modern browser. That's it — no server, no build.

Filters:

- **Search** — substring match on title / composer
- **Board / Grade / List** — dropdowns
- **Fits my voice** — enter your low and high notes (Helmholtz `c` / `g''` or
  scientific `C4` / `G5`); only songs whose range is inside yours are shown
- **Sort** by title, composer, lowest note, highest note, or list

Sheet-music and YouTube columns link to searches for title + composer.

## Populating the data

The site reads two files: `songs.js` and `books.js`. Both are generated.

### 1. Songs (from syllabus PDFs)

Drop the four syllabus PDFs into `pdfs/` with these names:

```
pdfs/abrsm_grade7.pdf
pdfs/abrsm_grade8.pdf
pdfs/trinity_grade7.pdf
pdfs/trinity_grade8.pdf
```

Then:

```sh
python3 -m venv .venv
.venv/bin/pip install pdfplumber beautifulsoup4
.venv/bin/python scripts/parse_pdfs.py
```

This writes `songs.js` and prints a summary, e.g. `ABRSM G7 A: 15`. Rows whose
range the parser couldn't understand are kept but show a blank range and are
excluded from the "fits my voice" filter.

Re-running `parse_pdfs.py` preserves `book_ids` from any previous run.

### 2. Books (from chimesmusic.com)

Save each relevant chimesmusic.com syllabus page as HTML into `html/`. Filenames
are for your own reference; any `.html` file is processed. Examples:

- `https://www.chimesmusic.com/latest/trinity-singing-grade-7-2018-2021/` → `html/trinity_g7.html`
- `https://www.chimesmusic.com/latest/abrsm-singing-grade-7-list-a/` → `html/abrsm_g7_list_a.html`

Then:

```sh
.venv/bin/python scripts/parse_books.py
```

This writes `books.js` and back-fills `book_ids` on `songs.js`. It prints any
songs found on chimesmusic that couldn't be matched to a syllabus row — either
edit the song titles in `songs.js` to match, or tweak the matching in
`scripts/parse_books.py`.

## When parsers mis-read

Both parsers are best-effort — ABRSM, Trinity, and chimesmusic each publish in
their own format, and those formats change between editions. If the output
looks off, either:

- Edit `songs.js` / `books.js` directly (they are plain JSON arrays inside a
  one-line `window.X = [...]` wrapper), **or**
- Adjust the parsers in `scripts/` and re-run.

## Layout

```
singing-grades/
  index.html          # site shell + filter UI
  style.css           # minimal styling
  songs.js            # generated
  books.js            # generated
  scripts/
    pitch.py          # note string -> MIDI
    parse_pdfs.py     # pdfs/ -> songs.js
    parse_books.py    # html/ -> books.js + book_ids
  pdfs/               # you provide
  html/               # you provide
```
