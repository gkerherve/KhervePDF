"""Named theme presets — palette colours, tab QSS, editor/status styling.

Each theme is a dict of named colour keys consumed by apply_theme() to
build a QPalette and by the QSS generators to style tabs, the editor
page/desk, and the status bar.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


# ------------------------------------------------------------------ #
# Theme definitions                                                    #
# ------------------------------------------------------------------ #

THEMES: dict[str, dict[str, str]] = {
    "Light": {
        "dark": "0",
        "base":         "#ffffff",
        "surface":      "#f7f7f7",
        "text":         "#1c1c1c",
        "text_muted":   "#666666",
        "accent":       "#1a6dd8",
        "accent2":      "#d96b00",
        "link":         "#1a6dd8",
        "highlight":    "#1a6dd8",
        "highlight_text": "#ffffff",
        "bright_text":  "#ff3333",
        "disabled":     "#9a9a9a",
        "placeholder":  "#888888",
        "alt_base":     "#eef1f5",
        "tab_active":   "#ffffff",
        "tab_inactive": "#e4e4e4",
        "tab_hover":    "#ececec",
        "desk_bg":      "#d0d4d8",
        "page_bg":      "#ffffff",
        "page_border":  "#b8bcc1",
        "status_text":  "#444444",
    },
    "Solarized Light": {
        "dark": "0",
        "base":         "#fdf6e3",
        "surface":      "#eee8d5",
        "text":         "#657b83",
        "text_muted":   "#93a1a1",
        "accent":       "#268bd2",
        "accent2":      "#cb4b16",
        "link":         "#268bd2",
        "highlight":    "#268bd2",
        "highlight_text": "#fdf6e3",
        "bright_text":  "#dc322f",
        "disabled":     "#93a1a1",
        "placeholder":  "#93a1a1",
        "alt_base":     "#eee8d5",
        "tab_active":   "#fdf6e3",
        "tab_inactive": "#e8e1ce",
        "tab_hover":    "#f0e9d5",
        "desk_bg":      "#d5cdb8",
        "page_bg":      "#fdf6e3",
        "page_border":  "#c9c1a8",
        "status_text":  "#657b83",
    },
    "Sepia": {
        "dark": "0",
        "base":         "#f5efe0",
        "surface":      "#ebe4d3",
        "text":         "#5b4636",
        "text_muted":   "#8a7560",
        "accent":       "#8b5e3c",
        "accent2":      "#b07038",
        "link":         "#7a5025",
        "highlight":    "#8b5e3c",
        "highlight_text": "#f5efe0",
        "bright_text":  "#c0392b",
        "disabled":     "#b0a08a",
        "placeholder":  "#a09080",
        "alt_base":     "#e8e0d0",
        "tab_active":   "#f5efe0",
        "tab_inactive": "#e0d7c6",
        "tab_hover":    "#ebe2d0",
        "desk_bg":      "#cdc4b2",
        "page_bg":      "#f5efe0",
        "page_border":  "#c5b9a5",
        "status_text":  "#6b5646",
    },
    "Dark": {
        "dark": "1",
        "base":         "#1e1e1e",
        "surface":      "#2d2d2d",
        "text":         "#d4d4d4",
        "text_muted":   "#858585",
        "accent":       "#4da6ff",
        "accent2":      "#f0a050",
        "link":         "#4da6ff",
        "highlight":    "#4da6ff",
        "highlight_text": "#ffffff",
        "bright_text":  "#ff5555",
        "disabled":     "#606060",
        "placeholder":  "#777777",
        "alt_base":     "#3a3a3a",
        "tab_active":   "#2d2d2d",
        "tab_inactive": "#1e1e1e",
        "tab_hover":    "#383838",
        "desk_bg":      "#1a1a1a",
        "page_bg":      "#2d2d2d",
        "page_border":  "#555555",
        "status_text":  "#aaaaaa",
    },
    "Nord": {
        "dark": "1",
        "base":         "#2e3440",
        "surface":      "#3b4252",
        "text":         "#d8dee9",
        "text_muted":   "#7b88a1",
        "accent":       "#88c0d0",
        "accent2":      "#ebcb8b",
        "link":         "#88c0d0",
        "highlight":    "#88c0d0",
        "highlight_text": "#2e3440",
        "bright_text":  "#bf616a",
        "disabled":     "#616e88",
        "placeholder":  "#616e88",
        "alt_base":     "#434c5e",
        "tab_active":   "#3b4252",
        "tab_inactive": "#2e3440",
        "tab_hover":    "#434c5e",
        "desk_bg":      "#242933",
        "page_bg":      "#3b4252",
        "page_border":  "#4c566a",
        "status_text":  "#a0aec0",
    },
    "Dracula": {
        "dark": "1",
        "base":         "#282a36",
        "surface":      "#44475a",
        "text":         "#f8f8f2",
        "text_muted":   "#8a8d9e",
        "accent":       "#bd93f9",
        "accent2":      "#ffb86c",
        "link":         "#8be9fd",
        "highlight":    "#bd93f9",
        "highlight_text": "#282a36",
        "bright_text":  "#ff5555",
        "disabled":     "#6272a4",
        "placeholder":  "#6272a4",
        "alt_base":     "#383a4a",
        "tab_active":   "#44475a",
        "tab_inactive": "#282a36",
        "tab_hover":    "#383a4a",
        "desk_bg":      "#1e1f29",
        "page_bg":      "#44475a",
        "page_border":  "#6272a4",
        "status_text":  "#bfc0cc",
    },
    "Gruvbox Light": {
        "dark": "0",
        "base":         "#fbf1c7",
        "surface":      "#ebdbb2",
        "text":         "#3c3836",
        "text_muted":   "#7c6f64",
        "accent":       "#458588",
        "accent2":      "#d65d0e",
        "link":         "#458588",
        "highlight":    "#458588",
        "highlight_text": "#fbf1c7",
        "bright_text":  "#cc241d",
        "disabled":     "#a89984",
        "placeholder":  "#928374",
        "alt_base":     "#f2e5bc",
        "tab_active":   "#fbf1c7",
        "tab_inactive": "#e8d8a8",
        "tab_hover":    "#f0e4b8",
        "desk_bg":      "#d5c4a1",
        "page_bg":      "#fbf1c7",
        "page_border":  "#bdae93",
        "status_text":  "#504945",
    },
    "Gruvbox Dark": {
        "dark": "1",
        "base":         "#282828",
        "surface":      "#3c3836",
        "text":         "#ebdbb2",
        "text_muted":   "#a89984",
        "accent":       "#83a598",
        "accent2":      "#fe8019",
        "link":         "#83a598",
        "highlight":    "#83a598",
        "highlight_text": "#282828",
        "bright_text":  "#fb4934",
        "disabled":     "#665c54",
        "placeholder":  "#7c6f64",
        "alt_base":     "#3c3836",
        "tab_active":   "#3c3836",
        "tab_inactive": "#282828",
        "tab_hover":    "#504945",
        "desk_bg":      "#1d2021",
        "page_bg":      "#3c3836",
        "page_border":  "#504945",
        "status_text":  "#bdae93",
    },
    "Monokai": {
        "dark": "1",
        "base":         "#272822",
        "surface":      "#3e3d32",
        "text":         "#f8f8f2",
        "text_muted":   "#90908a",
        "accent":       "#66d9ef",
        "accent2":      "#fd971f",
        "link":         "#66d9ef",
        "highlight":    "#49483e",
        "highlight_text": "#f8f8f2",
        "bright_text":  "#f92672",
        "disabled":     "#75715e",
        "placeholder":  "#75715e",
        "alt_base":     "#3e3d32",
        "tab_active":   "#3e3d32",
        "tab_inactive": "#272822",
        "tab_hover":    "#49483e",
        "desk_bg":      "#1e1f1c",
        "page_bg":      "#3e3d32",
        "page_border":  "#575747",
        "status_text":  "#a6e22e",
    },
    "One Dark": {
        "dark": "1",
        "base":         "#282c34",
        "surface":      "#2c313a",
        "text":         "#abb2bf",
        "text_muted":   "#636d83",
        "accent":       "#61afef",
        "accent2":      "#e5c07b",
        "link":         "#61afef",
        "highlight":    "#61afef",
        "highlight_text": "#282c34",
        "bright_text":  "#e06c75",
        "disabled":     "#5c6370",
        "placeholder":  "#5c6370",
        "alt_base":     "#2c313a",
        "tab_active":   "#2c313a",
        "tab_inactive": "#282c34",
        "tab_hover":    "#353b45",
        "desk_bg":      "#21252b",
        "page_bg":      "#2c313a",
        "page_border":  "#3e4451",
        "status_text":  "#9da5b4",
    },
    "GitHub Light": {
        "dark": "0",
        "base":         "#ffffff",
        "surface":      "#f6f8fa",
        "text":         "#24292f",
        "text_muted":   "#656d76",
        "accent":       "#0969da",
        "accent2":      "#cf222e",
        "link":         "#0969da",
        "highlight":    "#0969da",
        "highlight_text": "#ffffff",
        "bright_text":  "#cf222e",
        "disabled":     "#8c959f",
        "placeholder":  "#8c959f",
        "alt_base":     "#f6f8fa",
        "tab_active":   "#ffffff",
        "tab_inactive": "#eaeef2",
        "tab_hover":    "#f0f3f6",
        "desk_bg":      "#d0d7de",
        "page_bg":      "#ffffff",
        "page_border":  "#d0d7de",
        "status_text":  "#424a53",
    },
    "Catppuccin Mocha": {
        "dark": "1",
        "base":         "#1e1e2e",
        "surface":      "#313244",
        "text":         "#cdd6f4",
        "text_muted":   "#6c7086",
        "accent":       "#89b4fa",
        "accent2":      "#fab387",
        "link":         "#89dceb",
        "highlight":    "#89b4fa",
        "highlight_text": "#1e1e2e",
        "bright_text":  "#f38ba8",
        "disabled":     "#585b70",
        "placeholder":  "#585b70",
        "alt_base":     "#313244",
        "tab_active":   "#313244",
        "tab_inactive": "#1e1e2e",
        "tab_hover":    "#45475a",
        "desk_bg":      "#181825",
        "page_bg":      "#313244",
        "page_border":  "#45475a",
        "status_text":  "#a6adc8",
    },
    "Catppuccin Latte": {
        "dark": "0",
        "base":         "#eff1f5",
        "surface":      "#e6e9ef",
        "text":         "#4c4f69",
        "text_muted":   "#8c8fa1",
        "accent":       "#1e66f5",
        "accent2":      "#fe640b",
        "link":         "#1e66f5",
        "highlight":    "#1e66f5",
        "highlight_text": "#eff1f5",
        "bright_text":  "#d20f39",
        "disabled":     "#9ca0b0",
        "placeholder":  "#9ca0b0",
        "alt_base":     "#e6e9ef",
        "tab_active":   "#eff1f5",
        "tab_inactive": "#dce0e8",
        "tab_hover":    "#e6e9ef",
        "desk_bg":      "#ccd0da",
        "page_bg":      "#eff1f5",
        "page_border":  "#bcc0cc",
        "status_text":  "#5c5f77",
    },
}

THEME_NAMES: list[str] = list(THEMES.keys())


def is_dark(theme_name: str) -> bool:
    return THEMES.get(theme_name, THEMES["Light"])["dark"] == "1"


# ------------------------------------------------------------------ #
# QPalette builder                                                     #
# ------------------------------------------------------------------ #

def apply_theme(app: QApplication, theme_name: str) -> dict[str, str]:
    """Set the Fusion style + QPalette for the given theme. Returns the
    theme dict so callers can feed it to the QSS generators."""
    app.setStyle("Fusion")
    t = THEMES.get(theme_name, THEMES["Light"])
    pal = QPalette()

    pal.setColor(QPalette.Window,          QColor(t["surface"]))
    pal.setColor(QPalette.WindowText,      QColor(t["text"]))
    pal.setColor(QPalette.Base,            QColor(t["base"]))
    pal.setColor(QPalette.AlternateBase,   QColor(t["alt_base"]))
    pal.setColor(QPalette.ToolTipBase,     QColor(t["surface"]))
    pal.setColor(QPalette.ToolTipText,     QColor(t["text"]))
    pal.setColor(QPalette.Text,            QColor(t["text"]))
    pal.setColor(QPalette.Button,          QColor(t["surface"]))
    pal.setColor(QPalette.ButtonText,      QColor(t["text"]))
    pal.setColor(QPalette.BrightText,      QColor(t["bright_text"]))
    pal.setColor(QPalette.Link,            QColor(t["link"]))
    pal.setColor(QPalette.Highlight,       QColor(t["highlight"]))
    pal.setColor(QPalette.HighlightedText, QColor(t["highlight_text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(t["placeholder"]))

    disabled_color = QColor(t["disabled"])
    pal.setColor(QPalette.Disabled, QPalette.WindowText, disabled_color)
    pal.setColor(QPalette.Disabled, QPalette.Text,       disabled_color)
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, disabled_color)
    pal.setColor(QPalette.Disabled, QPalette.Highlight,  disabled_color)

    app.setPalette(pal)
    return t


# ------------------------------------------------------------------ #
# QSS generators                                                      #
# ------------------------------------------------------------------ #

def tab_stylesheet(t: dict[str, str]) -> str:
    """Polished tab bar styling with accent-coloured active indicator."""
    return f"""
        QTabWidget::pane {{
            border-top: 2px solid {t["accent"]};
            background: {t["base"]};
        }}
        QTabBar::tab {{
            background: {t["tab_inactive"]};
            color: {t["text_muted"]};
            padding: 7px 20px;
            border-top-left-radius: 5px;
            border-top-right-radius: 5px;
            margin-right: 2px;
            border: 1px solid transparent;
            border-bottom: none;
        }}
        QTabBar::tab:selected {{
            background: {t["tab_active"]};
            color: {t["text"]};
            border: 1px solid {t["accent"]};
            border-bottom: 2px solid {t["tab_active"]};
            font-weight: bold;
        }}
        QTabBar::tab:hover:!selected {{
            background: {t["tab_hover"]};
            color: {t["text"]};
        }}
    """


def editor_page_stylesheet(t: dict[str, str]) -> str:
    return f"#page {{ background: {t['page_bg']}; border: 1px solid {t['page_border']}; }}"


def editor_desk_stylesheet(t: dict[str, str]) -> str:
    return f"#desk {{ background: {t['desk_bg']}; }}"


def editor_textedit_stylesheet(t: dict[str, str]) -> str:
    return f"QTextEdit {{ background: {t['page_bg']}; color: {t['text']}; border: none; }}"


def latex_view_stylesheet(t: dict[str, str]) -> str:
    return f"QPlainTextEdit {{ background: {t['base']}; color: {t['text']}; }}"


def status_label_stylesheet(t: dict[str, str]) -> str:
    return f"color: {t['status_text']}; padding: 0 6px;"
