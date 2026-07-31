"""The compatibility command line."""
from __future__ import annotations

from datetime import datetime

from .backups import light_backup
from .catalog import provider_model_map
from .presets import format_preset_row, load_presets, switch_to
from .settings import apply_settings
from .store import load_custom, load_models_store, load_settings

USAGE = (
    "piswitch — pi 自定义模型供应商管理工具\n"
    "  piswitch                启动供应商管理 GUI\n"
    "  piswitch --help         显示帮助\n"
    "\n兼容命令:\n"
    "  piswitch list | ls      列出旧版预设(*=当前)\n"
    "  piswitch use <名称>     按旧版预设名切换\n"
    "  piswitch model <query>  按 provider/model 子串直接切换\n"
)


def _default_ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def cli_list(out=print) -> int:
    settings = load_settings()
    presets = load_presets()
    if not presets:
        out("(无预设) 用 GUI 新增，或 `piswitch model <query>` 直接切换。")
        return 0
    for p in presets:
        out(format_preset_row(p, settings))
    return 0


def _find_preset(name: str):
    presets = load_presets()
    exact = [p for p in presets if p.get("name") == name]
    if exact:
        return exact[0]
    subs = [p for p in presets if name.lower() in (p.get("name", "").lower())]
    return subs[0] if len(subs) == 1 else (None if not subs else False)  # False=歧义


def cli_use(name: str, ts: str, out=print) -> int:
    hit = _find_preset(name)
    if hit is None:
        out(f'piswitch: 没有匹配预设 "{name}"')
        return 1
    if hit is False:
        out(f'piswitch: "{name}" 匹配到多个预设，请写更精确的名称')
        return 1
    core_switch = switch_to(hit, ts)
    out(
        f"已切换到预设 {hit.get('name')}: "
        f"{core_switch.get('defaultProvider')}/{core_switch.get('defaultModel')}"
    )
    return 0


def cli_model(query: str, ts: str, out=print) -> int:
    store, custom = load_models_store(), load_custom()
    pm = provider_model_map(store, custom)
    matches = set()
    q = query.lower()
    for prov, models in pm.items():
        for m in models:
            key = f"{prov}/{m['id']}"
            if q in key.lower():
                matches.add((prov, m["id"]))
    if not matches:
        out(f'piswitch: 无模型匹配 "{query}"')
        return 1
    if len(matches) > 1:
        out(f'piswitch: "{query}" 匹配到 {len(matches)} 个，请写更精确：')
        for prov, mid in sorted(matches)[:20]:
            out(f"  {prov}/{mid}")
        return 1
    prov, mid = next(iter(matches))
    light_backup(ts)
    apply_settings(prov, mid)
    out(f"pi 默认模型: {prov}/{mid}")
    return 0


def dispatch(args, ts=None):
    if not args:
        return None  # 启动 GUI
    ts = ts or _default_ts()
    cmd = args[0]
    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if cmd in ("list", "ls", "-l", "--list"):
        return cli_list()
    if cmd == "use":
        if len(args) < 2:
            print("用法: piswitch use <名称>")
            return 1
        return cli_use(" ".join(args[1:]), ts)
    if cmd == "model":
        if len(args) < 2:
            print("用法: piswitch model <query>")
            return 1
        return cli_model(" ".join(args[1:]), ts)
    print(f'piswitch: 未知命令 "{cmd}"\n\n{USAGE}')
    return 2
