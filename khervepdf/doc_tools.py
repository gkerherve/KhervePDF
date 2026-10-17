"""Document-level PDF helpers that need no GUI: properties, cropping,
stamps, Bates numbering, writing the outline, form fields, DOI and
reference-list extraction, citation lookup and text comparison.

Like page_ops, everything works on a `fitz.Document` and leaves undo,
re-rendering and thumbnails to the caller.
"""
from __future__ import annotations

import difflib
import re
from typing import Optional

import fitz

# ----- document properties -----

META_KEYS = ("title", "author", "subject", "keywords", "creator", "producer")


def get_properties(doc: fitz.Document) -> dict[str, str]:
    meta = doc.metadata or {}
    return {k: meta.get(k) or "" for k in META_KEYS}


def set_properties(doc: fitz.Document, values: dict[str, str]) -> None:
    meta = dict(doc.metadata or {})
    for k in META_KEYS:
        if k in values:
            meta[k] = values[k]
    doc.set_metadata(meta)


# ----- cropping -----

def content_rect(page: fitz.Page, pad: float = 6.0) -> fitz.Rect:
    """Bounding box of everything drawn on the page (text, images,
    vector graphics), padded — what "trim to content" crops to."""
    r = fitz.Rect()
    for b in page.get_text("blocks"):
        r |= fitz.Rect(b[:4])
    for d in page.get_drawings():
        r |= d["rect"]
    for info in page.get_image_info():
        r |= fitz.Rect(info["bbox"])
    if r.is_empty:
        return fitz.Rect(page.mediabox)
    r = fitz.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad)
    return r & page.rect


def crop_pages(doc: fitz.Document, pages: list[int],
               margins: Optional[tuple[float, float, float, float]] = None
               ) -> int:
    """Set the crop box of each page. `margins` (left, top, right,
    bottom, in points) trims from the page edges; None trims each page
    to its own content. Returns how many pages changed."""
    n = 0
    for i in pages:
        page = doc[i]
        mb = page.mediabox
        if margins is None:
            # content_rect is in (unrotated-at-0) page space; the crop
            # box lives in mediabox space, which only differs by origin.
            r = content_rect(page)
            r = fitz.Rect(r.x0 + mb.x0, r.y0 + mb.y0,
                          r.x1 + mb.x0, r.y1 + mb.y0)
        else:
            left, top, right, bottom = margins
            r = fitz.Rect(mb.x0 + left, mb.y0 + top,
                          mb.x1 - right, mb.y1 - bottom)
        r &= mb
        if r.is_empty or r.width < 20 or r.height < 20:
            continue
        page.set_cropbox(r)
        n += 1
    return n


def reset_crop(doc: fitz.Document, pages: list[int]) -> None:
    for i in pages:
        doc[i].set_cropbox(doc[i].mediabox)


# ----- stamps -----

STAMPS = {
    "APPROVED": (0.18, 0.55, 0.24),
    "DRAFT": (0.45, 0.45, 0.45),
    "CONFIDENTIAL": (0.78, 0.16, 0.16),
    "FINAL": (0.08, 0.40, 0.75),
    "REVIEWED": (0.40, 0.23, 0.72),
    "NOT APPROVED": (0.78, 0.16, 0.16),
}

STAMP_POSITIONS = ("top-right", "top-left", "bottom-right", "bottom-left",
                   "center")


def stamp_rect(page: fitz.Page, text: str, fontsize: float,
               position: str) -> fitz.Rect:
    w = fitz.get_text_length(text, fontname="hebo", fontsize=fontsize) + fontsize
    h = fontsize * 1.7
    r = page.rect
    m = 28.0
    x = {"left": r.x0 + m, "right": r.x1 - m - w}.get(
        position.split("-")[-1], r.x0 + (r.width - w) / 2)
    y = {"top": r.y0 + m, "bottom": r.y1 - m - h}.get(
        position.split("-")[0], r.y0 + (r.height - h) / 2)
    return fitz.Rect(x, y, x + w, y + h)


def add_stamp(page: fitz.Page, text: str,
              color: tuple[float, float, float] = (0.78, 0.16, 0.16),
              position: str = "top-right", fontsize: float = 22.0,
              date: str = "") -> fitz.Rect:
    """Draw a rubber-stamp style box (border + bold capitals, optional
    date line) into the page content."""
    label = text.upper()
    rect = stamp_rect(page, label, fontsize, position)
    if date:
        rect.y1 += fontsize * 0.6
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(color=color, width=2.2, stroke_opacity=0.85)
    inner = fitz.Rect(rect.x0 + 3, rect.y0 + 3, rect.x1 - 3, rect.y1 - 3)
    shape.draw_rect(inner)
    shape.finish(color=color, width=0.6, stroke_opacity=0.85)
    shape.commit()
    tw = fitz.get_text_length(label, fontname="hebo", fontsize=fontsize)
    base = rect.y0 + fontsize * 1.25
    page.insert_text((rect.x0 + (rect.width - tw) / 2, base), label,
                     fontname="hebo", fontsize=fontsize, color=color,
                     fill_opacity=0.85)
    if date:
        ds = fontsize * 0.45
        dw = fitz.get_text_length(date, fontname="helv", fontsize=ds)
        page.insert_text((rect.x0 + (rect.width - dw) / 2,
                          base + fontsize * 0.65), date,
                         fontname="helv", fontsize=ds, color=color)
    return rect


# ----- page numbering / Bates -----

def page_label(i: int, total: int, style: str, prefix: str = "",
               start: int = 1, digits: int = 6) -> str:
    """Text of the stamp on page index `i`. Styles: "n / total",
    "Page n of total", "n", "bates" (prefix + zero-padded number)."""
    n = start + i
    if style == "bates":
        return f"{prefix}{n:0{max(1, digits)}d}"
    last = start + total - 1
    core = {"n": f"{n}", "Page n of total": f"Page {n} of {last}"}.get(
        style, f"{n} / {last}")
    return prefix + core


def number_pages(doc: fitz.Document, style: str = "n / total",
                 prefix: str = "", start: int = 1, digits: int = 6,
                 position: str = "bottom-center", fontsize: float = 10.0,
                 pages: Optional[list[int]] = None) -> int:
    total = doc.page_count
    pages = list(range(total)) if pages is None else pages
    for i in pages:
        page = doc[i]
        r = page.rect
        txt = page_label(i, total, style, prefix, start, digits)
        tw = fitz.get_text_length(txt, fontname="helv", fontsize=fontsize)
        vert, _, horiz = position.partition("-")
        x = {"left": r.x0 + 36, "right": r.x1 - 36 - tw}.get(
            horiz, r.x0 + (r.width - tw) / 2)
        y = r.y0 + 24 + fontsize if vert == "top" else r.y1 - 24
        page.insert_text((x, y), txt, fontname="helv", fontsize=fontsize,
                         color=(0.15, 0.15, 0.15))
    return len(pages)


# ----- outline -----

def normalise_toc(toc: list[list]) -> list[list]:
    """Make a TOC acceptable to set_toc: first level 1, no level jumps
    deeper by more than one, pages clamped to >= 1."""
    out: list[list] = []
    prev = 0
    for lvl, title, page, *rest in toc:
        lvl = max(1, min(int(lvl), prev + 1))
        out.append([lvl, str(title), max(1, int(page))])
        prev = lvl
    return out


def write_toc(doc: fitz.Document, toc: list[list]) -> None:
    doc.set_toc(normalise_toc(toc))


# ----- forms -----

def form_fields(doc: fitz.Document) -> list[dict]:
    """Every fillable widget: page, name, type label, value, options."""
    out = []
    for page in doc:
        for w in page.widgets() or []:
            out.append({
                "page": page.number,
                "name": w.field_name or "",
                "type": w.field_type_string,
                "value": w.field_value,
                "options": list(w.choice_values or []),
                "on_state": (w.on_state() if w.field_type in (
                    fitz.PDF_WIDGET_TYPE_CHECKBOX,
                    fitz.PDF_WIDGET_TYPE_RADIOBUTTON) else None),
                "xref": w.xref,
                "rect": tuple(w.rect),
            })
    return out


def set_field_value(doc: fitz.Document, page_idx: int, xref: int,
                    value) -> bool:
    for w in doc[page_idx].widgets() or []:
        if w.xref != xref:
            continue
        if w.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX,
                            fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
            w.field_value = w.on_state() if value else "Off"
        else:
            w.field_value = "" if value is None else str(value)
        w.update()
        return True
    return False


def flatten_forms(doc: fitz.Document) -> None:
    """Burn the filled-in fields into the page content and drop the
    widgets, so the result can no longer be edited."""
    doc.bake(annots=False, widgets=True)


# ----- DOIs and references -----

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>{}]+)", re.I)
_REF_HEAD_RE = re.compile(
    r"^\s*(\d+\.?\s*)?(references|bibliography|literature cited|"
    r"works cited|references and notes)\s*$", re.I)


def clean_doi(raw: str) -> str:
    doi = raw.strip().rstrip(".,;:)]}'\"")
    # A ")" belongs to the DOI only when it is balanced inside it.
    while doi.endswith(")") and doi.count("(") < doi.count(")"):
        doi = doi[:-1]
    return doi


def find_dois(doc: fitz.Document) -> list[str]:
    """Every distinct DOI in the text and link targets, in order of
    first appearance (case-insensitive)."""
    seen: dict[str, str] = {}

    def add(raw: str) -> None:
        doi = clean_doi(raw)
        if len(doi) > 8:
            seen.setdefault(doi.lower(), doi)

    for page in doc:
        # Joining hyphenated line breaks recovers DOIs split over lines.
        text = re.sub(r"-\n(?=\S)", "-", page.get_text())
        for m in DOI_RE.finditer(text.replace("\n", " ")):
            add(m.group(1))
        for link in page.get_links():
            uri = link.get("uri") or ""
            m = DOI_RE.search(uri)
            if m:
                add(m.group(1))
    return list(seen.values())


def _reference_lines(doc: fitz.Document) -> list[tuple[int, str]]:
    """(page, line) of everything after the last References heading."""
    lines: list[tuple[int, str]] = []
    for page in doc:
        for ln in page.get_text().splitlines():
            if ln.strip():
                lines.append((page.number, ln.strip()))
    start = None
    for i, (_p, ln) in enumerate(lines):
        if _REF_HEAD_RE.match(ln):
            start = i + 1
    return lines[start:] if start is not None else []


_NUM_START = re.compile(r"^\s*(?:\[(\d{1,4})\]|(\d{1,4})\.)\s*(.*)$")


def reference_list(doc: fitz.Document) -> dict[int, dict]:
    """Numbered references from the bibliography: {n: {"text", "page"}}.
    Handles "[12] Author…" and "12. Author…" styles; continuation lines
    are joined to the reference above them."""
    refs: dict[int, dict] = {}
    current: Optional[int] = None
    expected = 1
    for page, ln in _reference_lines(doc):
        m = _NUM_START.match(ln)
        n = int(m.group(1) or m.group(2)) if m else None
        # Only accept a number that continues the sequence, so a line
        # starting "2. " inside an entry isn't taken as a new reference.
        if n is not None and (n == expected or (current is None and n <= 3)
                              or n == expected + 1):
            current = n
            expected = n + 1
            refs[n] = {"text": m.group(3), "page": page}
        elif current is not None:
            prev = refs[current]["text"]
            joiner = "" if prev.endswith("-") else " "
            refs[current]["text"] = (prev[:-1] if joiner == "" else prev) + joiner + ln
    return refs


_CITE_RE = re.compile(r"\[(\d{1,4}(?:\s*[,–—-]\s*\d{1,4})*)\]")


def parse_citation(text: str) -> list[int]:
    """Numbers cited by "[3]", "[3,5]", "[3–6]" (empty list otherwise)."""
    m = _CITE_RE.search(text)
    if not m:
        return []
    out: list[int] = []
    for part in re.split(r"\s*,\s*", m.group(1)):
        bits = re.split(r"\s*[–—-]\s*", part)
        if len(bits) == 2 and bits[0].isdigit() and bits[1].isdigit():
            a, b = int(bits[0]), int(bits[1])
            if 0 < b - a < 50:
                out.extend(range(a, b + 1))
                continue
        if bits[0].isdigit():
            out.append(int(bits[0]))
    return out


def link_target_text(doc: fitz.Document, link: dict,
                     max_chars: int = 600) -> str:
    """Text at the destination of an internal link — for a citation
    link this is the reference itself."""
    if link.get("kind") not in (fitz.LINK_GOTO, fitz.LINK_NAMED):
        return ""
    pno = link.get("page", -1)
    if pno is None or not (0 <= pno < doc.page_count):
        return ""
    page = doc[pno]
    to = link.get("to")
    y = to.y if to is not None else 0
    # "to" is in PDF (bottom-up) space for most producers; take the
    # block nearest to either reading of it.
    cands = [y, page.rect.height - y]
    best, best_d = "", float("inf")
    for b in page.get_text("blocks"):
        if b[6] != 0:
            continue
        for cy in cands:
            d = abs(b[1] - cy) if b[1] >= cy - 4 else abs(b[1] - cy) + 40
            if d < best_d:
                best, best_d = b[4], d
    return " ".join(best.split())[:max_chars]


# ----- comparison -----

def page_words(page: fitz.Page) -> list[tuple]:
    return [w for w in page.get_text("words", sort=True)]


def compare_documents(a: fitz.Document, b: fitz.Document
                      ) -> tuple[dict[int, list], dict[int, list], dict]:
    """Word-level diff over the whole documents. Returns
    (removed rects per page of a, added rects per page of b, stats)."""
    wa = [(p.number, w) for p in a for w in page_words(p)]
    wb = [(p.number, w) for p in b for w in page_words(p)]
    sm = difflib.SequenceMatcher(
        None, [w[4] for _, w in wa], [w[4] for _, w in wb], autojunk=False)
    removed: dict[int, list] = {}
    added: dict[int, list] = {}
    stats = {"removed": 0, "added": 0, "changed": 0}
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        for pno, w in wa[i1:i2]:
            removed.setdefault(pno, []).append(fitz.Rect(w[:4]))
        for pno, w in wb[j1:j2]:
            added.setdefault(pno, []).append(fitz.Rect(w[:4]))
        stats["removed"] += i2 - i1
        stats["added"] += j2 - j1
        stats["changed"] += 1
    return removed, added, stats
