# CLAUDE.md — working conventions for KhervePDF

Project: WYSIWYG PDF viewer & annotation editor with Git history.
Stack: Python 3.12+, PySide6, PyMuPDF (fitz), pikepdf, pygit2, qtawesome.
Remote: https://github.com/gkerherve/KhervePDF

Sibling projects (mirror their conventions): **KherveTeX** (`../kherveDOC`)
and **KherveSheet** (`../KherveSheet`).

## Branching: `dev` is the working branch

**All work goes on `dev` in the main repo checkout.** I do not commit to
`main` directly. `main` is the stable mainline that lags behind `dev`
until the user explicitly asks for a merge.

**Never work in a git worktree (e.g. `.claude/worktrees/...`) or on a
throwaway branch like `claude/<name>`.** The user watches commits land
on `dev` in PyCharm's Git Log; commits made on worktree branches do not
show up there. If I find myself in a worktree or on a non-`dev` branch,
switch to the main repo path
(`C:\Users\gwilh\OneDrive - Imperial College London\Documents\MEGAsync\Programs\Python\KhervePDF`)
and `git checkout dev` before editing anything.

Workflow:
1. Confirm I am in the main repo and on `dev`
   (`git rev-parse --abbrev-ref HEAD` → `dev`,
   `git rev-parse --show-toplevel` → the main repo path above).
2. Make the edits.
3. Run `py -m pytest tests/ -q` and verify all tests pass.
4. `git add` the specific files I changed (avoid bare `git add -A` —
   it sweeps in IDE configs).
5. `git commit` with a HEREDOC-formatted message explaining the **why**,
   not the what. **No `Co-Authored-By:` trailer** (KherveSheet rule).
6. `git push` — **never skip this step**. If the push fails (no network,
   auth), report it but do not retry destructively.

If the user explicitly asks for a merge into `main`, do it as a single
fast-forward or merge commit on `main`, push, then return to `dev`.

## Always commit and push after any change

After every code change, commit and push to `origin/dev` without being
asked. Never leave changes uncommitted at the end of a turn. This rule
holds for small edits too — README updates, comment fixes, one-line bug
fixes.

## Bump the version on every commit

`khervepdf/__init__.py` defines `__version__` as `"<major>.<minor>"` only
(e.g. `"0.5"`). The window title renders it as

> `KhervePDF v<major>.<minor>.<commit_count>+<sha7> — "<last commit subject>" — <filename>`

The patch component is the total commit count and the `+<sha7>` build
tag, plus the **last commit subject** (in quotes), are appended
automatically from `pygit2` at startup and on every commit. They update
on their own — **never put a third number in `__version__`**.

**Bump the minor (`"0.5" → "0.6"`) on every commit.** The user wants the
version to advance with each commit, mirroring how KherveTeX bumps for
any user-visible change. The only exception is a pure mechanical fix
(typo in a comment) the user asks for explicitly — and even then,
default to bumping.

Bump the **major** (`"0.x" → "1.0"`) only at the user's explicit
request.

Bump `__version__` in the **same commit** as the change that justifies it.

## Commit message format

`v0.XX: <imperative subject under 70 chars>` — matches KherveTeX style
(see kherveDOC `git log` for examples). Body explains *why*, not what.

## File size policy (from KherveSheet)

Every module in `khervepdf/` should stay near **1500 lines**. If a
change would push a file meaningfully past that, split the new code
into a new module and import.

## Project layout

- `KhervePDF.py` — entry script (`python KhervePDF.py`).
- `khervepdf/` — package; `python -m khervepdf` is the alternative entry.
  - `__init__.py`   — `__version__`, `version_string()`, last-commit info.
  - `__main__.py`   — module entry point.
  - `app.py`        — `main()`, app icon, crash log, theme bootstrap.
  - `themes.py`     — 13 themes copied from KherveTeX (Light, Solarized
                      Light, Sepia, Dark, Nord, Dracula, Gruvbox
                      Light/Dark, Monokai, One Dark, GitHub Light,
                      Catppuccin Mocha, Catppuccin Latte). Palette +
                      QSS generators identical in spirit.
  - `mainwindow.py` — `MainWindow` shell: menus, toolbars, status bar,
                      tab widget (one PDF per tab), title-bar refresh.
  - `pdftab.py`     — single-PDF tab (QGraphicsView page canvas).
  - `document.py`   — PDF document model wrapping `fitz.Document` —
                      **single source of truth** for pages, annotations,
                      and edits. All tools and serializers go through it.
  - `page_view.py`  — `QGraphicsScene`/`QGraphicsView` with zoom/pan.
  - `tools/`        — pen, text, line, shapes, highlight, comment,
                      signature, redact. Each tool is a class with
                      activate/deactivate + mouse handlers.
  - `toolbar.py`    — annotation toolbar (tool group, color palette,
                      stroke width, opacity).
  - `page_ops.py`   — insert/delete/rotate/reorder/merge/split pages.
  - `thumbnails.py` — side-panel page thumbnails.
  - `search.py`     — text search across pages.
  - `forms.py`      — AcroForm field fill.
  - `icons.py`      — qtawesome icon factory + custom QPainter glyphs.
                      **No shipped PNG/SVG files** (KherveTeX rule).
  - `git_backend.py`— per-document git repo: auto-commit, push, pull,
                      history, branches (pygit2). Reuse kherveDOC code.
  - `history_dialog.py` — commit browser with DAG, diff, restore.
  - `remote_dialog.py`  — GitHub remote setup dialog.
  - `examples.py`   — bundled sample PDFs.
- `tests/` — model + page_ops + annotation round-trip tests.
- `requirements.txt`, `README.md`, `LICENSE` (GPL-3.0).

## UI conventions (mirror KherveTeX/KherveSheet)

- **Window style**: Fusion with a themed `QPalette` (never the OS dark
  default — light icons would vanish on Windows dark mode).
- **Tabs**: one PDF per tab; same `QTabWidget` styling as KherveTeX
  (accent-coloured active indicator, bold active label).
- **File menu**: New, Open, Open Recent, Save, Save As, Export
  (PNG / text), Print, Close Tab, Exit.
- **Edit menu**: Undo, Redo, Cut, Copy, Paste, Find.
- **View menu**: Zoom In/Out, Fit Width, Fit Page, Rotate, Themes
  submenu (13 entries from `themes.THEME_NAMES`), Toggle Thumbnails.
- **Tools menu / toolbar**: Select, Pen (color + width), Highlight,
  Text, Line, Arrow, Rectangle, Ellipse, Sticky Note, Signature, Redact.
- **Pages menu**: Insert Blank, Delete, Rotate Left/Right, Reorder,
  Merge PDF…, Split…
- **Git menu**: Commit Now, History…, Remote…, Branch…
- **Status bar**: page N of M, zoom %, current tool, cursor coords,
  git branch.
- **Title bar**:
  `KhervePDF v0.X.N+sha7 — "last commit subject" — <filename>`.

## Annotation tools

- **Pen**: freehand stroke, 8 preset colors (black, red, blue, green,
  yellow, orange, purple, white) + custom color picker; width slider
  (1–20 px); opacity slider (highlighter mode uses ~30% alpha).
- **Text**: text box with font/size/color.
- **Line / Arrow / Rectangle / Ellipse**: stroke + fill, dashed option.
- **Highlight / Underline / Strikethrough**: text-layer aware via
  PyMuPDF.
- **Sticky Note (Comment)**: anchored popup with author + timestamp.
- **Signature**: image stamp from PNG or freehand draw.
- **Redact**: black box that flattens on save via `Page.apply_redactions`.

All annotations are persisted into the PDF on save through PyMuPDF
(`page.add_*_annot`) so they round-trip with other readers.

## Architectural invariants

- Comments only when the *why* is non-obvious; never narrate the *what*.
- `document.py` is the **single source of truth**. Tools mutate the
  document model; serializers read it. Never edit PDF bytes directly
  outside `document.py`.
- Tests in `tests/` cover model + page_ops + annotation serialization.
  Any change to those modules ships with matching tests in the **same
  commit**.
- Toolbar icons drawn at runtime via qtawesome or QPainter — **no PNG
  or SVG files in the repo** for UI chrome.
- The themed Fusion palette in `app.py` is intentional; do not remove
  it (Windows dark mode hides the icons otherwise).
- Auto-commits from the app (`git_backend.py`) read the user's git
  identity from their git config so they look identical to CLI commits.

## Licensing

GPL-3.0. New source files must carry the short GPL notice at the top.
