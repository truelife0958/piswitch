#!/usr/bin/env python3
"""Measure where piswitch actually spends time, so optimisation targets real cost
instead of guesswork. Isolates data the same way smoke_gui.py does.
"""
from __future__ import annotations

import cProfile
import io
import os
import pstats
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

real_agent = Path.home() / ".pi" / "agent"
tmp = Path(tempfile.mkdtemp(prefix="piswitch_bench_"))
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

t0 = time.perf_counter()
import piswitch  # noqa: E402
import core  # noqa: E402
t_import = time.perf_counter() - t0

t0 = time.perf_counter()
app = piswitch.App()
app.update()
t_start = time.perf_counter() - t0

providers = list(app.provider_tree.get_children())
print(f"import modules      {t_import*1000:8.1f} ms")
print(f"App() + first paint {t_start*1000:8.1f} ms   ({len(providers)} providers)")


def timeit(label, fn, n=20):
    fn()  # warm
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    dt = (time.perf_counter() - t0) / n
    print(f"{label:<20}{dt*1000:8.2f} ms/call")


timeit("refresh_providers", lambda: app.refresh_providers())
timeit("_render_provider_rows", lambda: app._render_provider_rows())
timeit("_load_provider", lambda: app._load_provider(providers[0]))
timeit("_apply_action_states", lambda: app._apply_action_states())

# filter keystroke cost: what the user feels while typing
def type_filter():
    for ch in ("e", "l", "y"):
        app.provider_filter_var.set(app.provider_filter_var.get() + ch)
    app.provider_filter_var.set("")


timeit("filter 3 keystrokes", type_filter, n=10)

print("\n=== cProfile: 20x refresh_providers ===")
pr = cProfile.Profile()
pr.enable()
for _ in range(20):
    app.refresh_providers()
pr.disable()
s = io.StringIO()
pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(14)
print("\n".join(s.getvalue().splitlines()[4:24]))

app.destroy()
shutil.rmtree(tmp, ignore_errors=True)
