"""Convert a pitch string to a MIDI number.

Accepts two notations commonly used in singing syllabi:

- Helmholtz: ``C,, C, C c c' c''`` — apostrophes raise, commas lower.
  Middle C is ``c'``.
- Scientific: ``C4``, ``F#5``, ``Bb3``. Middle C is ``C4``.

Accidentals: ``#`` / ``♯`` sharpen, ``b`` / ``♭`` flatten. Unicode
ASCII and unicode are accepted.

Returns ``None`` for inputs that can't be parsed.
"""

from __future__ import annotations

import re

_PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_to_midi(s: str) -> int | None:
    if s is None:
        return None
    raw = s.strip()
    if not raw:
        return None
    raw = raw.replace("♯", "#").replace("♭", "b")

    m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d+)", raw)
    if m:
        letter, acc, octave = m.group(1).upper(), m.group(2), int(m.group(3))
        semitone = _PITCH_CLASS[letter] + (1 if acc == "#" else -1 if acc == "b" else 0)
        return (octave + 1) * 12 + semitone

    m = re.fullmatch(r"([A-Ga-g])([#b]?)(['’\"]*|,*)", raw)
    if m:
        letter, acc, marks = m.group(1), m.group(2), m.group(3).replace("’", "'")
        is_lower = letter.islower()
        base_octave = 3 if is_lower else 2
        if marks.startswith(","):
            octave = base_octave - len(marks)
        elif marks and marks[0] in "'\"":
            # Count octave levels: ' = 1, " = 2 (one double-prime)
            levels = sum(2 if c == '"' else 1 for c in marks)
            octave = base_octave + levels
        else:
            octave = base_octave
        semitone = _PITCH_CLASS[letter.upper()] + (
            1 if acc == "#" else -1 if acc == "b" else 0
        )
        return (octave + 1) * 12 + semitone

    return None


if __name__ == "__main__":
    cases = {
        "C4": 60, "c'": 60, "c''": 72, "c": 48, "C": 36, "C,": 24,
        "F#5": 78, "f#'": 66, "Bb3": 58, "bb": 58,
        "g'": 67, "g": 55, "A4": 69, "a'": 69,
        # Trinity double-prime style using "
        'f#"': 78, 'c"': 72, 'g"': 79,
        # Mixed
        "f#'\"": 90,  # one prime + one double = 3 levels up
    }
    bad = [k for k, want in cases.items() if note_to_midi(k) != want]
    if bad:
        for k in bad:
            print(f"FAIL {k!r}: got {note_to_midi(k)}, want {cases[k]}")
        raise SystemExit(1)
    print(f"pitch.py: {len(cases)} cases OK")
