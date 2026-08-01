"""应用配色与可复用的 ttk 状态样式。"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, ttk


COLORS = {
    "background": "#f4f6f8",
    "surface": "#ffffff",
    "surface_alt": "#eef2f5",
    "border": "#cfd7df",
    "text": "#20262e",
    "muted": "#66717d",
    "accent": "#2367a8",
    "accent_hover": "#1d568c",
    "accent_soft": "#dceaf7",
    "success": "#18794e",
    "warning": "#946200",
    "danger": "#b42318",
    "danger_soft": "#fff0ee",
    "stripe": "#f8fafb",
}

WINDOW_TITLE = "piswitch"

UI_FONT_CANDIDATES = (
    "Noto Sans CJK SC",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Source Han Sans CN",
    "WenQuanYi Micro Hei",
    "PingFang SC",
)

TK_UI_FONTS = (
    "TkDefaultFont",
    "TkTextFont",
    "TkMenuFont",
    "TkHeadingFont",
    "TkCaptionFont",
    "TkSmallCaptionFont",
    "TkIconFont",
    "TkTooltipFont",
)


def _configure_ui_fonts(root) -> str:
    """Use one CJK-capable family instead of relying on per-glyph fallback."""
    available = {family.casefold(): family for family in tkfont.families(root)}
    family = next(
        (available[name.casefold()] for name in UI_FONT_CANDIDATES if name.casefold() in available),
        str(tkfont.nametofont("TkDefaultFont", root=root).actual("family")),
    )
    for name in TK_UI_FONTS:
        try:
            tkfont.nametofont(name, root=root).configure(family=family)
        except tk.TclError:  # pragma: no cover - named fonts vary between Tk builds
            continue
    root.option_add("*Font", "TkDefaultFont")
    root.option_add("*Menu.font", "TkMenuFont")
    return family


def apply(root) -> ttk.Style:
    font_family = _configure_ui_fonts(root)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:  # pragma: no cover - depends on the local Tk installation
        pass

    colors = COLORS
    root.configure(background=colors["background"])
    root.option_add("*Menu.background", colors["surface"])
    root.option_add("*Menu.foreground", colors["text"])
    root.option_add("*Menu.activeBackground", colors["accent_soft"])
    root.option_add("*Menu.activeForeground", colors["text"])

    style.configure(".", font="TkDefaultFont")
    style.configure("TFrame", background=colors["background"])
    style.configure("Toolbar.TFrame", background=colors["surface_alt"])
    style.configure("TLabel", background=colors["background"], foreground=colors["text"])
    style.configure(
        "Title.TLabel",
        background=colors["surface_alt"],
        foreground=colors["text"],
        font=(font_family, 13, "bold"),
    )
    style.configure("Muted.TLabel", foreground=colors["muted"])
    style.configure("Section.TLabel", font=(font_family, 11, "bold"))
    style.configure("Success.TLabel", foreground=colors["success"])
    style.configure("Warning.TLabel", foreground=colors["warning"])
    style.configure("Danger.TLabel", foreground=colors["danger"])
    style.configure("Dirty.TLabel", foreground=colors["warning"])
    style.configure(
        "Status.TLabel",
        background=colors["surface_alt"],
        foreground=colors["muted"],
        bordercolor=colors["border"],
    )

    style.configure(
        "TButton",
        width=0,
        padding=(9, 5),
        background=colors["surface_alt"],
        foreground=colors["text"],
        bordercolor=colors["border"],
        focuscolor=colors["accent"],
        relief="flat",
    )
    style.map(
        "TButton",
        background=[
            ("pressed", colors["accent_soft"]),
            ("active", "#e3e9ee"),
            ("disabled", colors["background"]),
        ],
        foreground=[("disabled", "#9aa3ad")],
    )
    style.configure(
        "Primary.TButton",
        background=colors["accent"],
        foreground="#ffffff",
        bordercolor=colors["accent"],
    )
    style.map(
        "Primary.TButton",
        background=[
            ("pressed", colors["accent_hover"]),
            ("active", colors["accent_hover"]),
            ("disabled", "#a8bfd4"),
        ],
        foreground=[("disabled", "#eef4f8")],
    )
    style.configure(
        "Danger.TButton",
        background=colors["danger_soft"],
        foreground=colors["danger"],
        bordercolor="#e6b8b3",
    )
    style.map("Danger.TButton", background=[("active", "#faddd9")])

    style.configure(
        "TEntry",
        fieldbackground=colors["surface"],
        foreground=colors["text"],
        bordercolor=colors["border"],
        insertcolor=colors["text"],
        padding=5,
    )
    style.configure(
        "TCombobox",
        fieldbackground=colors["surface"],
        background=colors["surface"],
        foreground=colors["text"],
        bordercolor=colors["border"],
        padding=4,
    )
    style.configure(
        "Treeview",
        background=colors["surface"],
        fieldbackground=colors["surface"],
        foreground=colors["text"],
        bordercolor=colors["border"],
        rowheight=27,
    )
    style.map(
        "Treeview",
        background=[("selected", colors["accent_soft"])],
        foreground=[("selected", "#173a59")],
    )
    style.configure(
        "Treeview.Heading",
        background=colors["surface_alt"],
        foreground="#34404c",
        bordercolor=colors["border"],
        relief="flat",
        padding=(6, 6),
        font=(font_family, 9, "bold"),
    )
    style.map("Treeview.Heading", background=[("active", "#e1e7ec")])
    style.configure("TCheckbutton", background=colors["background"], foreground=colors["text"])
    style.configure("TPanedwindow", background=colors["border"])
    return style


def configure_tree_tags(tree) -> None:
    colors = COLORS
    font_family = str(
        tkfont.nametofont("TkDefaultFont", root=tree).actual("family")
    )
    tree.tag_configure("stripe", background=colors["stripe"])
    tree.tag_configure(
        "default", foreground=colors["success"], font=(font_family, 9, "bold")
    )
    tree.tag_configure("healthy", foreground=colors["success"])
    tree.tag_configure("unhealthy", foreground=colors["danger"])
    tree.tag_configure("imported", foreground=colors["muted"])
    tree.tag_configure("missing", foreground=colors["warning"])
