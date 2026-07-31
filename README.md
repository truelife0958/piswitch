# piswitch

piswitch 是一个轻量的 pi 模型供应商管理工具，用于维护 `~/.pi/agent/models.json` 和 `auth.json` 中的自定义 provider。

主要功能：

- 查看自定义模型供应商
- 新增、编辑和删除供应商
- 配置 Base URL、API 类型和 API Key
- 为供应商增加或删除模型
- 一键把 pi 的默认供应商/模型切换到选中的模型
- 编辑模型元数据（上下文窗口、最大输出、价格、是否支持推理）
- 测试 API 连接：先列模型，再真发一次最小对话
- 批量健康检查所有供应商，列表内显示 ✓/✗ 与延迟
- `$ENV_VAR` 形式的 Key 会就地提示变量是否已设置
- 从 `/v1/models` 批量导入模型，并尽量带上真实元数据
- 导出/导入供应商配置（不含 API Key）
- 浏览并恢复修改前的配置快照
- 删除当前默认供应商或模型时主动警告
- 修改前自动备份，JSON 配置原子写入

## 运行

需要 Python 3 和 tkinter：

```bash
./bin/piswitch
```

安装用户级命令和桌面入口：

```bash
./install.sh
piswitch
```

在 WSL 上，`install.sh` 会额外用 `sudo` 往 `/usr/share/applications` 装一份桌面入口——WSLg 只扫系统目录，放在 `~/.local/share/applications` 的入口不会出现在 Windows 开始菜单。设 `PISWITCH_NO_SYSTEM_ENTRY=1` 可跳过这步和它需要的 sudo。

WSL 环境需要启用 WSLg 或配置可用的 X server。

## 命令行

带参数运行时不启动图形界面，适合图形环境不可用的场合：

```bash
piswitch list             # 列出预设
piswitch use <名称>        # 切换到预设
piswitch model <query>     # 模糊匹配并切换模型，多个候选会列出来
```

## 使用

左侧显示所有自定义供应商。选择供应商后，可在右侧修改显示名称、Base URL、API 类型和 API Key。

新增供应商：

1. 点击“新增”。
2. 填写 Provider ID、名称、Base URL 和 API 类型。
3. 点击“保存供应商”。
4. 点击“拉取模型”从服务端多选导入，或点击“增加模型”手工输入 Model ID。

“测试连接”会使用当前表单中的 Base URL 和 API Key 请求模型接口，然后对选中的模型（未选中时取列表第一个）真发一次 1-token 对话。只列模型是不够的：不少第三方代理能正常返回模型列表，却在真实对话时因为 `prompt_cache_key` 之类的参数返回 400。`openai-completions`、`openai-responses`、`anthropic-messages`、`google-generative-ai` 支持对话探测；其余类型只验证模型接口。网络请求在后台运行，不会阻塞窗口。使用 `$ENV_VAR` Key 时，需要先在启动 piswitch 的环境中设置对应变量——API Key 输入框下方会直接提示该变量是否已设置。

顶部“检查全部”会并发检查列表中所有供应商，在“状态”列显示 ✓ 与延迟或 ✗。这一步只请求 `/v1/models`，不产生对话费用；需要验证真实对话时，请对单个供应商用“测试连接”。检查结果只用于显示，不会写入任何配置。

选中模型后点“设为默认”（或双击“默认”列）即可把 pi 的 `defaultProvider` / `defaultModel` 指向它，当前默认项在两个列表中以 ★ 标记。内置供应商虽然不可编辑，但同样可以设为默认。

双击模型行可编辑其元数据：上下文窗口、最大输出 tokens、每百万 tokens 的输入/输出价格、是否支持推理。留空表示未知，不会被写成 0。从 `/v1/models` 导入或手工新增模型时，piswitch 会先尝试沿用 `models-store.json` 中同名模型的元数据，再采用接口自身返回的 `context_length` / `pricing` 等字段，都拿不到时才回退到占位默认值。

“拉取模型”窗口默认不选择任何模型。可点击单行或聚焦后按空格切换勾选状态，也可使用“全选”和“清空”批量操作；Shift+点击可从上次点击行到当前行之间整段框选切换，整段统一进入或退出勾选状态。

顶部“导出”会把全部自定义供应商写成一个 JSON 文件。**导出文件不含 API Key**：字面量 Key 会被剔除，`$ENV_VAR` 形式的引用会保留（它只是变量名，不是密钥本身），因此该文件可以安全地提交到 git 或发给同事，导入方自行设置对应环境变量即可。“导入”会读取这样的文件；已存在的供应商可选择覆盖或跳过，内置供应商永远不会被覆盖，`auth.json` 全程不被修改。

保存第三方 `openai-completions` 供应商时，piswitch 会在 `compat` 中补充安全默认值：启用会话亲和请求头，并关闭长缓存参数。已有 `compat` 显式设置优先，不会被默认值覆盖。

在补全安全默认值之前创建的供应商（即 `compat` 块缺失或不完整的旧条目），会在每次载入时被自动补齐缺失的字段，并随下次任意写入操作原子持久化。这一迁移是幂等的，且不会覆盖用户显式设置值——主要目的是让旧预设免受第三方代理拒绝 `prompt_cache_key` 等参数导致的 400 错误。

删除供应商会同时删除该供应商的模型配置和 `auth.json` 中对应的 API Key。内置供应商来自 `models-store.json`，本工具不会修改或删除它们。

删除 pi 当前默认的供应商或模型时会显示额外警告。应先在 pi 中切换默认模型，再执行删除。

## 数据安全

工具修改：

- `~/.pi/agent/models.json`
- `~/.pi/agent/auth.json`

每次修改前，会把现有的 `settings.json`、`models.json` 和 `auth.json` 复制到：

```text
~/.local/share/piswitch/backups/switch-<时间戳>/
```

工具自动保留最近 20 个快照。点击顶部“恢复备份”可选择历史快照；恢复前也会保存当前状态，因此可以再次回退。

API Key 支持 `$ENV_VAR` 写法并原样保存。开发和测试时，可使用 `PI_AGENT_DIR` 与 `PISWITCH_DATA_DIR` 覆盖数据目录。

## 验证

```bash
python3 -m pytest -q
python3 -m py_compile core.py piswitch.py smoke_gui.py
bash -n bin/piswitch install.sh
```

`smoke_gui.py` 会把真实配置复制到临时目录，构造一次窗口并走完所有供应商加载与对话框路径，用于快速排查 GUI 回归：

```bash
python3 smoke_gui.py          # 有显示器时
xvfb-run -a python3 smoke_gui.py   # 无显示器时
```

`audit_layout.py` 渲染真实窗口后测量各控件的实际几何，报告用户会感知为"布局坏了"的问题：列宽之和超出可见宽度、控件零尺寸或未映射、自然尺寸超过窗口 minsize、文字溢出标签或按钮。改动 `layout.py` 后跑一次：

```bash
python3 audit_layout.py
xvfb-run -a python3 audit_layout.py   # 无显示器时
```
