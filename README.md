# KhervePDF

A WYSIWYG PDF viewer and annotation editor with built-in Git history.

Sibling tool to [KherveTeX](https://github.com/gkerherve/kherveDOC) and
KherveSheet — same look, same workflow, same theme set.

## Features (target)

- Tabbed PDF view, one document per tab.
- Annotation tools: pen (multi-colour), highlight, text, line, arrow,
  rectangle, ellipse, sticky note, signature, redact.
- Page operations: insert, delete, rotate, reorder, merge, split.
- Form filling (AcroForm).
- Text search across pages.
- 13 KherveTeX themes (Light, Dark, Nord, Dracula, Gruvbox, Monokai,
  One Dark, GitHub, Catppuccin, …).
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
