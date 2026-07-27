# piswitch —— cc-switch 式的 pi 供应商切换器（设计 spec）

- 日期：2026-07-27
- 状态：已确认，待写实现计划
- 作者：truel + Claude

## 1. 背景与目标

`pi`（`@earendil-works/pi-coding-agent`）是一个终端编程 agent。围绕"切换 pi 的模型/供应商"，
用户主目录里散落了多个重叠工具：

- `~/.local/bin/pi-model`：98 行 Node CLI，只切换 `defaultProvider/defaultModel`（读 `models-store.json` → 写 `settings.json`）。可用。
- `~/.local/bin/piswitch` + `~/.local/share/piswitch/piswitch.py`：Python tkinter + 托盘 GUI。**当前 `piswitch.py` 被清空为 0 字节**，仅存 49 KB 的 `.bak`（1176 行，功能完整，是 pi-model 的严格超集）。
- `~/ebak/pi-gui`：第三方 Electron 桌面 App（clone 自 `minghinmatthewlam/pi-gui`），自带 provider 切换。**将删除**。
- 旁枝（不在范围）：`~/pi-magic-setup/`（pi + subagents + magic-context 安装器）、`~/pi_test/jiangshuo/`（无关 RAG 项目）。

**目标**：把这些切换器整合成**单一项目**——一个类似 cc-switch 的桌面应用：多套供应商**预设卡片**、
一键切换当前生效、托盘常驻、写入前备份；同时吸收 pi-model 的命令行能力。基于已还原的
tkinter piswitch 改造（复用其安全读写/备份逻辑），落在独立的 `~/piswitch/` 项目里。

### 已确认的关键决策
- 合并为**一个工具**。
- 形态：**GUI 优先**，改造成 **cc-switch 式预设切换器**；技术栈 = **Python/tkinter 改造**（WSL2 上最轻、复用现成代码）。
- 位置：独立 `~/piswitch/` 项目（可 git）。
- **吸收 pi-model** 为 CLI 子命令，随后删除 pi-model。
- **删除 `~/ebak/pi-gui`**（用户已确认放弃其 6 个未推送提交，`rm -rf`）。

## 2. cc-switch 参照的交互模型

cc-switch 的本质：把供应商配置抽象成用户维护的**预设卡片**（名称 / API 地址 / key / 模型），
点一下把某张设为"当前生效"，应用写入目标 CLI 的配置文件；带托盘、写入前备份、导入/导出。
本项目把写入目标从 `~/.claude` 换成 `~/.pi/agent`。

## 3. 数据模型

### 3.1 预设存储（新增）
`~/.local/share/piswitch/presets.json`：

```jsonc
{
  "presets": [
    { "id": "<uuid>", "name": "NewAPI·GPT-4o", "kind": "custom",
      "provider": "newapi", "model": "gpt-4o",
      "baseUrl": "https://gateway.example/v1", "api": "openai-completions",
      "apiKey": "$NEWAPI_API_KEY", "thinking": "off" },
    { "id": "<uuid>", "name": "DeepSeek 官方", "kind": "builtin",
      "provider": "deepseek", "model": "deepseek-chat", "thinking": "high" }
  ]
}
```

- `kind: "builtin"`：pi 自带 catalog 的 provider，切换只改 `settings.json`。
- `kind: "custom"`：自定义网关，切换时另把该 provider merge 进 `models.json`、key merge 进 `auth.json`。
- 字段可选：`baseUrl/api/apiKey` 仅 custom 需要；`thinking` 缺省沿用当前 settings。

### 3.2 pi 侧被写文件（经安全原子写）
- `~/.pi/agent/settings.json`：`defaultProvider / defaultModel / defaultThinkingLevel`（`theme` 由高级页管理）。
- `~/.pi/agent/models.json`：自定义 provider（`providers.<name> = {name,baseUrl,api,apiKey,models[...]}`）。
- `~/.pi/agent/auth.json`：`<provider> = {type:"apikey", key}`。
- `~/.pi/agent/models-store.json`：**只读**，枚举内置 catalog。

## 4. 一键切换语义

`switch_to(preset)`：
1. **轻量备份**：把 `settings.json / models.json / auth.json` 三个文件拷到
   `~/.local/share/piswitch/backups/switch-<YYYYmmdd-HHMMSS>/`（不整目录拷 `~/.pi/agent`，避免带上 `npm/node_modules`）。
2. 原子写 `settings.json`：设 `defaultProvider=preset.provider`、`defaultModel=preset.model`、
   若 preset 指定则 `defaultThinkingLevel=preset.thinking`。
3. 若 `kind=custom`：把 `preset` 对应 provider 配置 merge 进 `models.json`；把 `apiKey` merge 进 `auth.json`（保留 `$ENV` 写法原样）。
4. 刷新"当前生效"标记。

**当前生效判定**：`settings.json.defaultProvider == preset.provider && settings.json.defaultModel == preset.model`。

保留菜单里的**整目录全量备份/恢复**（复用旧 `backup_agent`/`restore_agent`，`sessions` 目录恢复时不覆盖）作为重操作，与每次切换的轻量备份并存。

## 5. 界面

### 5.1 主页 = 预设卡片
- 可滚动卡片列表；每张卡显示：名称、`provider/model`、api 类型徽标、有无 Key（✓/—）、「✓ 当前 / 切换」按钮。
- 工具条：`新增预设`、`编辑`、`删除`、`从当前 pi 配置导入为预设`、`导入/导出 JSON`。
- 「切换」→ 执行 §4，成功后状态栏提示并高亮当前卡。

### 5.2 预设编辑弹窗
- 通用：名称、provider、kind、可选 thinking。
- custom：baseUrl、api 类型（下拉 `API_TYPES`）、apiKey（支持 `$ENV`）、模型 id（逗号分隔），并可「从 `/v1/models` 拉取」（复用旧 `fetch_models`）。
- builtin：从 `models-store.json` catalog 选 provider + model。

### 5.3 「高级」标签页（保留旧代码，二级入口）
- API Key 管理（auth.json 增删改，复用旧 auth tab）。
- settings.json 原始编辑（复用旧 raw tab）。
- 内置 provider 转发（baseUrl / headers override，复用旧 `edit_builtin_override`）。
- 备注/标签（notes.json，复用旧逻辑）。
- 全量备份 & 恢复（复用旧 backup tab）。

### 5.4 其它复用
- 系统托盘（pystray，`PYSTRAY_BACKEND=xorg`）+ 无托盘时悬浮迷你窗兜底。
- 主题 dark/light、快捷键（Esc 最小化 / Ctrl+H 显隐 / Ctrl+R 刷新 / Ctrl+S 应用）、`.desktop` 安装。

## 6. CLI（吸收 pi-model）

`piswitch.py` 在 `main()` 顶部加无界面分支：**有参数即执行并退出，不创建 Tk 窗口**。

- `piswitch list` / `ls` → 列出所有预设，当前生效标 `*`。
- `piswitch use <名称>` → 按名称（精确优先，否则子串唯一匹配）激活预设（= §4 的 CLI 版）。
- `piswitch model <query>` → 兼容旧 pi-model：从 catalog 按 `provider/model` 子串切换，唯一匹配则写 `settings.json`。
- `piswitch --help` → 用法。
- 无参数 → 启动 GUI（今日行为）。

CLI 与 GUI 共用同一套 `load_*` / `save_json` / 备份函数。之后删除 `~/.local/bin/pi-model`。

## 7. 项目结构

```
~/piswitch/
├── piswitch.py         # 还原 .bak + 预设 UI 重构 + CLI 分支
├── bin/piswitch        # 启动器：export PYSTRAY_BACKEND=xorg; exec python3 ~/piswitch/piswitch.py "$@"
├── install.sh          # 软链 bin/piswitch → ~/.local/bin/piswitch；装 .desktop；幂等
├── README.md           # GUI/CLI 用法、presets 格式、涉及文件、WSL/X 说明
├── docs/               # 本 spec 等
└── .gitignore
```

- 运行数据留在 `~/.local/share/piswitch/`：`presets.json`、`notes.json`、`backups/`（代码路径写死于此）。
- `~/.local/bin/piswitch` 改为软链指向 `~/piswitch/bin/piswitch`，现有 `piswitch` 命令照常可用。

## 8. 删除 / 保留清单

- 删除：`~/ebak/pi-gui`（`rm -rf`）、`~/.local/bin/pi-model`、空的 `~/.local/share/piswitch/piswitch.py` 与过期 `__pycache__`。
- 保留：`~/.local/share/piswitch/`（运行数据）、`~/pi-magic-setup/`、`~/pi_test/jiangshuo/`、`~/.pi/agent`（仅经安全函数写）。
- `.bak` 在新仓库首次提交中留存作溯源。

## 9. 依赖与环境

- Python 3 + tkinter 8.6（已装）、PIL（已装）。pystray 无 Gtk 后端 → 自动走 xorg / 迷你窗兜底（已具备）。
- WSL2：GUI 需 X 显示（WSLg 提供）；无显示时 CLI 全功能可用，GUI 冒烟测标为手动。

## 10. 验证

- `python3 -m py_compile ~/piswitch/piswitch.py` 通过。
- `piswitch list` 正确列出预设并标当前。
- `piswitch use <名>`：`settings.json` 翻转到目标 provider/model，且生成 `backups/switch-<ts>/`；改前后 diff 确认，再还原。
- `piswitch model <query>`：等价旧 pi-model 行为。
- custom 预设切换：`models.json`/`auth.json` 正确 merge。
- 有 WSLg 时：GUI 启动、卡片切换、当前标记冒烟测。

## 11. 非目标（YAGNI）

- 不做 Tauri/Electron 重写、不打包 AppImage、不做自动更新。
- 不改 pi 本体，不动 `~/pi-magic-setup` 与 `~/pi_test`。
- 不做云同步；导入/导出仅本地 JSON 文件。
