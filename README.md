# KhervePDF

A WYSIWYG PDF viewer and annotation editor with built-in Git history.

Sibling tool to [KherveTeX](https://github.com/gkerherve/kherveDOC) and
KherveSheet — same look, same workflow, same theme set.

## Features (target)

- Tabbed PDF view, one document per tab.
- Annotation tools: pen (multi-colour), highlight, text, line, arrow,
  rectangle, ellipse, sticky note, signature, redact.
- Page operations: insert, delete, rotate, reorder, merge, split.
- Form filling (AcroForm): fill fields on the page or in a table, then
  optionally flatten them.
- References: hover a `[12]` citation (or a citation link) to read the
  reference in a popup; import every DOI in a paper into KherveRef
  (details fetched from doi.org).
- Compare two PDFs, or the open PDF with one of its git commits, side
  by side with the text differences highlighted.
- Reading: remembers each file's last page and zoom; night reading
  (invert, soft dark, sepia); read aloud with the spoken sentence
  highlighted.
- Preparing documents: edit properties (title, author, keywords), crop
  pages (to content or by margins), stamps (Approved / Draft /
  Confidential…), page numbers and Bates numbering, outline editing.
- AI assistant: ask about a selected area of the page, plus presets
  (summarise the paper, list the methods…) that cite page numbers.
- Text search across pages.
- 13 KherveTeX themes (Light, Dark, Nord, Dracula, Gruvbox, Monokai,
  One Dark, GitHub, Catppuccin, …).
- Slideshow: present the PDF one whole page at a time, in the app
  window or full screen, by hand or continuously (a page every N
  seconds). View → Slideshow, F5 / Shift+F5, or the view buttons at
  the bottom right of the window.
- Per-document Git repo: auto-commit, history browser, GitHub remote.

## Stack

Python 3.12+, PySide6, PyMuPDF, pikepdf, pygit2, qtawesome.

## Run

```
pip install -r requirements.txt
python KhervePDF.py
```

## Status

v0.1 — application shell (menus, toolbar, tabs, status bar, themes,
git-aware title bar). Rendering, tools, and git backend land in
subsequent commits.

## License

GPL-3.0.
