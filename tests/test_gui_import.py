import importlib
import re
import sys

import pytest

import core


def test_piswitch_module_imports():
    mod = importlib.import_module("piswitch")
    assert hasattr(mod, "App")
    assert hasattr(mod, "main")
    assert mod.ICON_PATH.is_file()


def test_gui_uses_core_dispatch(monkeypatch):
    mod = importlib.import_module("piswitch")
    called = {}

    def dispatch(args):
        called["args"] = args
        return 0

    monkeypatch.setattr(core, "dispatch", dispatch)
    monkeypatch.setattr(sys, "argv", ["piswitch", "ls"])
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert called["args"] == ["ls"]


def test_mutation_timestamp_is_path_safe():
    mod = importlib.import_module("piswitch")
    timestamp = mod.mutation_timestamp()
    assert re.fullmatch(r"\d{8}-\d{6}-\d{6}", timestamp)
