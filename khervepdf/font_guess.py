"""Best guess at the font behind a PDF text span, for Edit Text.

A PDF names its fonts however the producer liked ("ABCDEF+TimesNewRoman
PS-BoldMT", "CMR10", "NimbusRomNo9L-Regu", "F1", "T1_0") and the font
itself is usually an embedded subset that cannot type new letters. So
the guess is a family that is *installed here* and looks the same:

  1. the PDF's own family name, if this machine has it;
  2. a known metric-compatible / look-alike family (TeX, URW, Liberation,
     Office fonts …), first installed candidate wins;
  3. otherwise a generic class — serif, sans or mono — from the name and
     the span's font flags (PyMuPDF: bit 1 italic, 2 serif, 3 mono,
     4 bold).

Bold and italic come from the same name + flags, so the editor opens
with the style the paragraph actually has.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# PyMuPDF span flag bits.
_ITALIC, _SERIF, _MONO, _BOLD = 2, 4, 8, 16

_SERIF_FALLBACK = ["Times New Roman", "Times", "Georgia", "STIX Two Text",
                   "Liberation Serif", "DejaVu Serif", "Noto Serif"]
_SANS_FALLBACK = ["Helvetica", "Arial", "Helvetica Neue", "Liberation Sans",
                  "DejaVu Sans", "Noto Sans", "Segoe UI"]
_MONO_FALLBACK = ["Courier New", "Courier", "Menlo", "Consolas",
                  "Liberation Mono", "DejaVu Sans Mono"]

# (compact-name prefix, class, candidate families). Compact = lower case
# with spaces, dashes and underscores removed. Longest prefix wins.
_ALIASES: list[tuple[str, str, list[str]]] = [
    # Times family and its clones
    ("timesnewroman", "serif", ["Times New Roman", "Times"]),
    ("times", "serif", ["Times New Roman", "Times"]),
    ("nimbusrom", "serif", ["Times New Roman", "Times"]),
    ("liberationserif", "serif", ["Liberation Serif", "Times New Roman"]),
    ("tinos", "serif", ["Tinos", "Times New Roman"]),
    ("texgyretermes", "serif", ["TeX Gyre Termes", "Times New Roman"]),
    ("stix", "serif", ["STIX Two Text", "STIXGeneral", "Times New Roman"]),
    ("utm", "serif", ["Times New Roman"]),            # txfonts / newtx
    ("ntx", "serif", ["Times New Roman"]),
    ("txr", "serif", ["Times New Roman"]),
    # Helvetica / Arial and clones
    ("arialmt", "sans", ["Arial", "Helvetica"]),
    ("arial", "sans", ["Arial", "Helvetica"]),
    ("helveticaneue", "sans", ["Helvetica Neue", "Helvetica", "Arial"]),
    ("helvetica", "sans", ["Helvetica", "Arial"]),
    ("nimbussan", "sans", ["Helvetica", "Arial"]),
    ("liberationsans", "sans", ["Liberation Sans", "Arial"]),
    ("arimo", "sans", ["Arimo", "Arial"]),
    ("texgyreheros", "sans", ["TeX Gyre Heros", "Helvetica"]),
    ("uhv", "sans", ["Helvetica", "Arial"]),
    # Courier and clones
    ("couriernew", "mono", ["Courier New", "Courier"]),
    ("courier", "mono", ["Courier New", "Courier"]),
    ("nimbusmon", "mono", ["Courier New", "Courier"]),
    ("liberationmono", "mono", ["Liberation Mono", "Courier New"]),
    ("cousine", "mono", ["Cousine", "Courier New"]),
    # TeX Computer Modern / Latin Modern
    ("cmr", "serif", ["CMU Serif", "Latin Modern Roman", "Computer Modern",
                      "Times New Roman"]),
    ("cmbx", "serif", ["CMU Serif", "Latin Modern Roman", "Times New Roman"]),
    ("cmti", "serif", ["CMU Serif", "Latin Modern Roman", "Times New Roman"]),
    ("cmsl", "serif", ["CMU Serif", "Latin Modern Roman", "Times New Roman"]),
    ("cmmi", "serif", ["CMU Serif", "Latin Modern Math", "Times New Roman"]),
    ("cmsy", "serif", ["CMU Serif", "Latin Modern Math", "Times New Roman"]),
    ("cmss", "sans", ["CMU Sans Serif", "Latin Modern Sans", "Helvetica"]),
    ("cmtt", "mono", ["CMU Typewriter Text", "Latin Modern Mono",
                      "Courier New"]),
    ("sfrm", "serif", ["CMU Serif", "Latin Modern Roman", "Times New Roman"]),
    ("sfbx", "serif", ["CMU Serif", "Latin Modern Roman", "Times New Roman"]),
    ("sfti", "serif", ["CMU Serif", "Latin Modern Roman", "Times New Roman"]),
    ("lmroman", "serif", ["Latin Modern Roman", "CMU Serif",
                          "Times New Roman"]),
    ("lmsans", "sans", ["Latin Modern Sans", "CMU Sans Serif", "Helvetica"]),
    ("lmmono", "mono", ["Latin Modern Mono", "CMU Typewriter Text",
                        "Courier New"]),
    ("latinmodern", "serif", ["Latin Modern Roman", "CMU Serif",
                              "Times New Roman"]),
    # Palatino / Bookman / Century / Garamond / Office fonts
    ("palatino", "serif", ["Palatino", "Palatino Linotype", "Book Antiqua",
                           "TeX Gyre Pagella"]),
    ("urwpalladio", "serif", ["Palatino", "TeX Gyre Pagella"]),
    ("texgyrepagella", "serif", ["TeX Gyre Pagella", "Palatino"]),
    ("upl", "serif", ["Palatino", "TeX Gyre Pagella"]),
    ("texgyrebonum", "serif", ["TeX Gyre Bonum"]),
    ("texgyreschola", "serif", ["TeX Gyre Schola"]),
    ("urwbookman", "serif", ["Bookman Old Style", "TeX Gyre Bonum"]),
    ("centuryschl", "serif", ["Century Schoolbook", "TeX Gyre Schola"]),
    ("ncs", "serif", ["Century Schoolbook", "TeX Gyre Schola"]),
    ("carlito", "sans", ["Carlito"]),
    ("caladea", "serif", ["Caladea"]),
    ("cmusansserif", "sans", ["CMU Sans Serif"]),
    ("cmutypewriter", "mono", ["CMU Typewriter Text"]),
    ("cmu", "serif", ["CMU Serif"]),
    ("bookantiqua", "serif", ["Book Antiqua", "Palatino",
                              "TeX Gyre Pagella"]),
    ("bookman", "serif", ["Bookman Old Style", "Bookman", "TeX Gyre Bonum"]),
    ("centuryschoolbook", "serif", ["Century Schoolbook", "New Century "
                                    "Schoolbook", "TeX Gyre Schola"]),
    ("garamond", "serif", ["Garamond", "EB Garamond", "Adobe Garamond Pro",
                           "Georgia"]),
    ("minion", "serif", ["Minion Pro", "Times New Roman"]),
    ("cambria", "serif", ["Cambria", "Caladea", "Georgia"]),
    ("georgia", "serif", ["Georgia"]),
    ("calibri", "sans", ["Calibri", "Carlito", "Helvetica Neue", "Arial"]),
    ("candara", "sans", ["Candara", "Helvetica Neue"]),
    ("segoeui", "sans", ["Segoe UI", "Helvetica Neue", "Arial"]),
    ("verdana", "sans", ["Verdana", "Arial"]),
    ("tahoma", "sans", ["Tahoma", "Verdana", "Arial"]),
    ("myriad", "sans", ["Myriad Pro", "Helvetica Neue", "Arial"]),
    ("frutiger", "sans", ["Frutiger", "Helvetica Neue", "Arial"]),
    ("gillsans", "sans", ["Gill Sans", "Gill Sans MT", "Helvetica"]),
    ("futura", "sans", ["Futura", "Helvetica"]),
    ("dejavusans", "sans", ["DejaVu Sans", "Verdana"]),
    ("dejavuserif", "serif", ["DejaVu Serif", "Georgia"]),
    ("consolas", "mono", ["Consolas", "Menlo", "Courier New"]),
    ("menlo", "mono", ["Menlo", "Courier New"]),
    ("sourcecodepro", "mono", ["Source Code Pro", "Menlo"]),
    ("sourcesans", "sans", ["Source Sans Pro", "Source Sans 3", "Helvetica"]),
    ("sourceserif", "serif", ["Source Serif Pro", "Source Serif 4",
                              "Georgia"]),
    ("roboto", "sans", ["Roboto", "Helvetica"]),
    ("opensans", "sans", ["Open Sans", "Helvetica"]),
    ("lato", "sans", ["Lato", "Helvetica"]),
    ("symbol", "serif", ["Symbol", "Times New Roman"]),
]
_ALIASES.sort(key=lambda a: -len(a[0]))

_BOLD_RE = re.compile(r"(bold|black|heavy|semibold|demibold|demi\b|"
                      r"[-,_]bd\b|[-,_]sb\b|^cmbx|^sfbx|^cmb)", re.I)
_ITALIC_RE = re.compile(r"(italic|oblique|slanted|[-,_]it\b|[-,_]bi\b|"
                        r"[-,_]i\b|^cmti|^cmmi|^cmsl|^sfti)", re.I)
_SANS_HINT = re.compile(r"(sans|grotesk|gothic|helv|arial|heros)", re.I)
_MONO_HINT = re.compile(r"(mono|courier|typewriter|code|consol)", re.I)


@dataclass
class FontGuess:
    family: str          # installed family to show / use
    generic: str         # "serif" | "sans" | "mono"
    bold: bool
    italic: bool
    source: str          # the PDF's own (cleaned) name, for the label
    exact: bool          # the PDF's family itself is installed


def strip_subset(raw: str) -> str:
    """Drop the 6-letter subset prefix: "ABCDEF+Foo" → "Foo"."""
    return raw.split("+", 1)[1] if re.match(r"^[A-Z]{6}\+", raw or "") \
        else (raw or "")


def _family_variants(name: str) -> list[str]:
    """Spellings of the PDF family to try against installed fonts."""
    base = re.split(r"[,\-_]", name, maxsplit=1)[0]
    for suf in ("MT", "PS", "MS", "PSMT", "Std", "Pro", "LT"):
        if base.endswith(suf) and len(base) > len(suf) + 2:
            base = base[: -len(suf)]
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced).strip()
    # Drop a weight word glued to the name ("Arial Bold").
    plain = re.sub(r"\s+(Bold|Italic|Regular|Roman|Light|Medium|"
                   r"Semibold|Black)$", "", spaced)
    out = []
    for v in (spaced, plain, base):
        if v and v not in out:
            out.append(v)
    return out


def guess_font(raw: str, flags: int = 0,
               installed: set[str] | None = None) -> FontGuess:
    if installed is None:
        try:
            from . import font_library
            font_library.register_with_qt()
            from PySide6.QtGui import QFontDatabase
            installed = set(QFontDatabase.families())
        except Exception:
            installed = set()
    lower_installed = {f.lower(): f for f in installed}
    name = strip_subset(raw or "")
    compact = re.sub(r"[\s\-_,]", "", name).lower()
    style_part = name
    bold = bool(flags & _BOLD) or bool(_BOLD_RE.search(style_part))
    italic = bool(flags & _ITALIC) or bool(_ITALIC_RE.search(style_part))

    alias = next((a for a in _ALIASES if compact.startswith(a[0])), None)
    if alias is not None:
        generic = alias[1]
    elif flags & _MONO or _MONO_HINT.search(name):
        generic = "mono"
    elif _SANS_HINT.search(name):
        generic = "sans"
    elif flags & _SERIF:
        generic = "serif"
    else:
        # No name hint and no serif flag: most untagged body text in
        # the wild is sans (Office, web exports); TeX names hit aliases.
        generic = "sans" if name else "serif"

    variants = _family_variants(name) if name else []
    for v in variants:
        hit = lower_installed.get(v.lower())
        if hit:
            return FontGuess(hit, generic, bold, italic,
                             variants[0], True)
    fallback = {"serif": _SERIF_FALLBACK, "sans": _SANS_FALLBACK,
                "mono": _MONO_FALLBACK}[generic]
    for cand in (alias[2] if alias else []) + fallback:
        hit = lower_installed.get(cand.lower())
        if hit:
            return FontGuess(hit, generic, bold, italic,
                             variants[0] if variants else "", False)
    first = (alias[2] if alias else fallback)[0]
    return FontGuess(first, generic, bold, italic,
                     variants[0] if variants else "", False)


def guess_size(sizes_by_chars: dict[float, int]) -> float:
    """Dominant size, snapped to the nearest 0.5 pt when it is within
    0.06 pt of it (PDF sizes are often 10.9589 for an intended 11)."""
    if not sizes_by_chars:
        return 11.0
    s = max(sizes_by_chars, key=sizes_by_chars.get)
    snapped = round(s * 2) / 2
    return snapped if abs(snapped - s) <= 0.06 else round(s, 1)


def size_text(size: float) -> str:
    """"11" / "10.5" — no trailing ".0" in the size box."""
    return f"{round(size, 1):g}"
