#!/usr/bin/env python3
"""Layout audit: render the real window and measure it, reporting anything a user
would experience as broken layout.

This is the desktop equivalent of inspecting a page in devtools — a tkinter window has
no DOM, but every widget reports its realised geometry after an update() pass.

Checks:
  - Treeview column widths summing past the rendered width (columns get clipped)
  - Widgets that rendered at zero size or never got mapped
  - Requested (natural) size exceeding the window's own minsize
  - Text that overflows its label/button

Run: python3 audit_layout.py    (needs a display; use xvfb-run -a if headless)
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import tkinter.font as tkfont
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

real_agent = Path.home() / ".pi" / "agent"
tmp = Path(tempfile.mkdtemp(prefix="piswitch_audit_"))
agent = tmp / "agent"; agent.mkdir(parents=True)
data = tmp / "data"; data.mkdir(parents=True)
for name in ("settings.json", "models.json", "auth.json", "models-store.json"):
    src = real_agent / name
    if src.exists():
        shutil.copy2(src, agent / name)
os.environ["PI_AGENT_DIR"] = str(agent)
os.environ["PISWITCH_DATA_DIR"] = str(data)

problems: list[str] = []
notes: list[str] = []


def flag(msg: str) -> None:
    problems.append(msg)
    print(f"  PROBLEM  {msg}")


def note(msg: str) -> None:
    notes.append(msg)
    print(f"  note     {msg}")


def audit_tree(label: str, tree) -> None:
    cols = tree.cget("columns")
    total = sum(int(tree.column(c, "width")) for c in cols)
    rendered = tree.winfo_width()
    heading_font = tkfont.nametofont("TkHeadingFont", root=tree)
    print(f"\n[{label}] rendered={rendered}px  columns sum={total}px")
    for col in cols:
        title = str(tree.heading(col)["text"])
        width = int(tree.column(col, "width"))
        print(f"    {str(col):10s} width={tree.column(col, 'width'):>4}  "
              f"minwidth={tree.column(col, 'minwidth'):>3}  "
              f"stretch={tree.column(col, 'stretch')}  heading={title}")
        # Ttk headings need a little room around the measured label for theme padding.
        needed = heading_font.measure(title) + 10
        if width < needed:
            flag(f"{label}: {title!r} 表头需要约 {needed}px，当前列宽仅 {width}px")
    if total > rendered:
        flag(f"{label}: 列宽合计 {total}px 超出渲染宽度 {rendered}px，"
             f"末列被裁掉约 {total - rendered}px（用户需拖拽分隔条才能看全）")
    elif rendered - total > 120:
        note(f"{label}: 剩余空白 {rendered - total}px，可让某列 stretch 填满")


def walk(widget, depth=0):
    for child in widget.winfo_children():
        cls = child.winfo_class()
        w, h = child.winfo_width(), child.winfo_height()
        mapped = bool(child.winfo_ismapped())
        # Menus are intentionally unmapped until their Menubutton is opened.
        if not mapped and cls not in ("Toplevel", "Menu"):
            flag(f"未映射控件 {cls} ({child})")
        elif (w <= 1 or h <= 1) and cls not in ("Frame", "TFrame", "Toplevel", "Menu"):
            flag(f"零尺寸控件 {cls} {w}x{h} ({child})")
        # A button whose natural width exceeds its allotted width shows clipped text.
        if cls in ("TButton", "TLabel") and mapped:
            req = child.winfo_reqwidth()
            if req > w + 1:
                flag(f"{cls} 文本被裁: 需要 {req}px 只有 {w}px — {child.cget('text')!r}")
        walk(child, depth + 1)


def main() -> int:
    import tkinter as tk
    import piswitch

    try:
        app = piswitch.App()
    except tk.TclError as exc:
        print(f"[audit] no display ({exc}); re-run under xvfb-run")
        return 2
    app.update()

    print(f"window   geometry={app.winfo_width()}x{app.winfo_height()}  "
          f"minsize={app.minsize()}  requested={app.winfo_reqwidth()}x{app.winfo_reqheight()}")
    if app.winfo_reqwidth() > app.minsize()[0]:
        note(f"自然宽度 {app.winfo_reqwidth()}px > minsize 宽 {app.minsize()[0]}px："
             f"缩到最小尺寸时内容会被压缩")

    audit_tree("provider_tree", app.provider_tree)
    audit_tree("model_tree", app.model_tree)

    print("\n[widget tree]")
    walk(app)

    # Same audit at the smallest size the user is allowed to drag to.
    mw, mh = app.minsize()
    app.geometry(f"{mw}x{mh}")
    app.update()
    print(f"\n=== 缩到 minsize {mw}x{mh} 后 ===")
    audit_tree("provider_tree@min", app.provider_tree)
    audit_tree("model_tree@min", app.model_tree)
    print("\n[widget tree@min]")
    walk(app)

    app.destroy()
    print(f"\n审计完成：{len(problems)} 个问题，{len(notes)} 条提示")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
