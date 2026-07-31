# piswitch

piswitch 是一个轻量的 pi 模型供应商管理工具。它直接管理 pi 的供应商、模型、凭据和默认模型配置，同时提供桌面 GUI 与兼容命令行入口。

## 功能

- 新增、编辑、删除和筛选自定义供应商
- 从内置模板创建 OpenAI、Anthropic、Gemini、DeepSeek、Ollama 等供应商
- 从 `/v1/models` 拉取并批量导入模型，标记已导入项并提醒清理远端未返回项
- 编辑上下文窗口、最大输出、价格和推理能力等模型元数据
- 把选中模型设为 pi 的默认模型
- 测试模型列表接口，并对支持的 API 类型发送最小对话请求
- 并发检查全部供应商的可用性与延迟
- 使用统一的冷灰、蓝色和状态色，并优先使用系统中可用的中文字体
- 导入、导出不含明文 API Key 的供应商配置
- 自动备份、原子写入并支持从历史快照恢复
- 在切换供应商、刷新或退出前保护未保存修改

## 环境要求

- Python 3.10 或更高版本
- tkinter
- Linux 桌面、WSLg，或其他可用的 X/Wayland 图形环境

Ubuntu/WSL 缺少 tkinter 时可安装：

```bash
sudo apt install python3-tk
```

项目没有第三方 Python 运行时依赖。

## 直接运行

在项目目录执行：

```bash
./bin/piswitch
```

查看命令行帮助：

```bash
./bin/piswitch --help
```

## 安装

安装当前用户的 `piswitch` 命令、图标和桌面入口：

```bash
./install.sh
piswitch
```

安装脚本会把启动命令链接到 `~/.local/bin/piswitch`。请确认 `~/.local/bin` 已加入 `PATH`。

在 WSLg 中，Windows 开始菜单只扫描系统桌面入口，因此安装脚本还会通过 `sudo` 写入 `/usr/share/applications`。不需要开始菜单入口时可跳过：

```bash
PISWITCH_NO_SYSTEM_ENTRY=1 ./install.sh
```

## 基本使用

新增供应商：

1. 点击“新增”或“从模板”。
2. 填写 Provider ID、名称、Base URL、API 类型和 API Key。
3. 点击“保存供应商”。
4. 点击“拉取模型”批量导入，或在“管理”菜单中手工增加模型。
5. 选择模型并点击“设为默认”。

API Key 可以填写明文，也可以使用 `$ENV_VAR` 引用。推荐使用环境变量；界面会显示对应变量是否已设置。

“测试连接”先请求模型列表，再对支持的 API 类型发送一次 1-token 对话，用于发现只能列模型但无法真实对话的代理配置。顶部“检查全部”只请求模型列表，不产生对话费用。

双击模型行可编辑模型元数据；双击“默认”列可直接切换默认模型。内置供应商不可修改，但可以设为默认、隐藏或移除本地凭据。

## 命令行

带参数运行不会启动 GUI：

```bash
piswitch list             # 列出兼容旧版预设
piswitch use <名称>       # 切换到指定预设
piswitch model <query>    # 模糊匹配 provider/model 并切换
```

`model` 匹配多个结果时只会列出候选，不会修改配置。

## 配置与数据安全

piswitch 读取或修改以下 pi 配置：

```text
~/.pi/agent/settings.json
~/.pi/agent/models.json
~/.pi/agent/auth.json
~/.pi/agent/models-store.json  # 只读
```

每次写入前，现有的 `settings.json`、`models.json` 和 `auth.json` 会备份到：

```text
~/.local/share/piswitch/backups/switch-<时间戳>/
```

默认保留最近 20 个快照。恢复前也会备份当前状态，因此恢复操作仍可回退。

导出文件不会包含明文 API Key；`$ENV_VAR` 形式的变量引用会保留。开发或测试时可覆盖数据目录，避免接触真实配置：

```bash
PI_AGENT_DIR=/tmp/piswitch-agent \
PISWITCH_DATA_DIR=/tmp/piswitch-data \
./bin/piswitch
```

## 项目结构

```text
piswitch.py          GUI 入口与应用初始化
core/                不依赖 tkinter 的配置、备份、探测和切换逻辑
ui/                  供应商、模型、网络和表单行为
ui/theme.py           全局配色、控件和状态样式
layout.py            主窗口控件布局
dialogs.py           备份恢复和模型编辑对话框
config_dialogs.py    配置导入、导出和模板对话框
remote_dialog.py     远程模型导入和未返回模型清理
tests/               单元测试与 GUI 回归测试
smoke_gui.py         真实窗口冒烟检查
audit_layout.py      控件尺寸与布局审计
```

## 开发验证

完整的非交互检查：

```bash
python3 -m pytest -q
python3 -m py_compile piswitch.py dialogs.py config_dialogs.py remote_dialog.py layout.py \
  audit_layout.py smoke_gui.py ui/*.py core/*.py
bash -n bin/piswitch install.sh
```

GUI 检查需要可用显示器：

```bash
python3 smoke_gui.py
python3 audit_layout.py
```

无桌面环境时可使用 Xvfb：

```bash
xvfb-run -a python3 smoke_gui.py
xvfb-run -a python3 audit_layout.py
```
