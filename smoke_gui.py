#!/usr/bin/env python3
"""Headless GUI smoke test — construct App() against a copy of the real pi config
and exercise every provider-load / dialog path, printing full tracebacks.

Isolates data into a temp dir so the real ~/.pi/agent files are never touched.
Every messagebox/simpledialog is stubbed: an unstubbed modal blocks forever with no
one to click it, which is how the previous version hung on the no-backups dialog.

Run under the current display, or a virtual one:  xvfb-run -a python3 smoke_gui.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from tkinter import simpledialog

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

# --- isolate data ----------------------------------------------------------
real_agent = Path.home() / ".pi" / "agent"
tmp = Path(tempfile.mkdtemp(prefix="piswitch_smoke_"))
agent = tmp / "agent"
agent.mkdir(parents=True)
data = tmp / "data"
data.mkdir(parents=True)
for name in ("settings.json", "models.json", "auth.json", "models-store.json"):
    src = real_agent / name
    if src.exists():
        shutil.copy2(src, agent / name)
os.environ["PI_AGENT_DIR"] = str(agent)
os.environ["PISWITCH_DATA_DIR"] = str(data)
os.environ["PISWITCH_DEBUG"] = "1"

failures: list[str] = []


def step(label: str, fn) -> None:
    try:
        fn()
        print(f"  ok: {label}")
    except Exception:  # noqa: BLE001 - smoke test wants every traceback
        failures.append(label)
        print(f"  FAIL: {label}")
        traceback.print_exc()


def _stub_modals(piswitch) -> list[str]:
    """Replace every blocking dialog with a recorder.

    A real modal has no one to dismiss it here, so it would hang the run.
    """
    opened: list[str] = []

    def record(kind, default=None):
        def call(title="", message="", **_kwargs):
            opened.append(f"{kind}:{title}")
            return default
        return call

    piswitch.messagebox.showinfo = record("info")
    piswitch.messagebox.showerror = record("error")
    piswitch.messagebox.showwarning = record("warning")
    piswitch.messagebox.askyesno = record("askyesno", default=False)
    simpledialog.askstring = record("askstring", default=None)
    return opened


def _describe(widget) -> str:
    return f"{widget.winfo_width()}x{widget.winfo_height()} mapped={bool(widget.winfo_ismapped())}"


def _buttons(widget) -> dict:
    found = {}
    for child in widget.winfo_children():
        if child.winfo_class() in ("TButton", "Button"):
            found[str(child.cget("text"))] = child
        found.update(_buttons(child))
    return found


def main() -> int:
    import tkinter as tk

    import core
    import piswitch

    opened = _stub_modals(piswitch)

    try:
        app = piswitch.App()
    except tk.TclError as exc:
        print(f"[smoke] cannot open a display ({exc}). Re-run under xvfb-run.")
        return 2
    print("App() constructed; startup refresh_providers ran clean.")

    # Force a real layout pass so geometry below is meaningful, not zeros.
    app.update()
    print(f"\nwindow      {_describe(app)}")
    print(f"provider_tree {_describe(app.provider_tree)}")
    print(f"model_tree    {_describe(app.model_tree)}")
    print(f"status        {app.status_var.get()!r}")

    rows = app.provider_tree.get_children()
    print(f"\nprovider rows ({len(rows)}): {rows}")
    for iid in rows:
        step(f"_load_provider({iid})", lambda iid=iid: app._load_provider(iid))

    step("new_provider()", app.new_provider)

    # Backup-restore dialog. Make a snapshot first so the dialog actually opens
    # instead of short-circuiting on "no backups".
    core.light_backup("20260730-000000")

    def open_backup():
        app.open_backup_restore()
        app.update()
        dialogs = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
        if not dialogs:
            raise AssertionError("restore dialog did not open")
        labels = _buttons(dialogs[0])
        print(f"    restore dialog buttons: {sorted(labels)}")
        for required in ("恢复所选", "取消"):
            if required not in labels:
                raise AssertionError(f"missing {required} button")
            if not labels[required].winfo_ismapped():
                raise AssertionError(f"{required} button is not rendered")
        for w in dialogs:
            w.destroy()

    step("open_backup_restore() has working buttons", open_backup)

    def show_remote():
        app._show_remote_models(
            [{"id": "m1", "name": "M1"}, {"id": "m2", "name": "M2"}],
            rows[0] if rows else "x",
        )
        app.update()
        dialogs = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
        if not dialogs:
            raise AssertionError("remote-models dialog did not open")
        print(f"    remote dialog buttons: {sorted(_buttons(dialogs[0]))}")
        for w in dialogs:
            w.destroy()

    step("_show_remote_models()", show_remote)

    if opened:
        print(f"\ndialogs suppressed during run: {opened}")
    app.update_idletasks()
    app.destroy()
    print(f"\nsmoke complete: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
