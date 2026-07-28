# piswitch

piswitch 是一个轻量的 pi 模型供应商管理工具，用于维护 `~/.pi/agent/models.json` 和 `auth.json` 中的自定义 provider。

主要功能：

- 查看自定义模型供应商
- 新增、编辑和删除供应商
- 配置 Base URL、API 类型和 API Key
- 为供应商增加或删除模型
- 测试 API 连接并从 `/v1/models` 批量导入模型
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

WSL 环境需要启用 WSLg 或配置可用的 X server。

## 使用

左侧显示所有自定义供应商。选择供应商后，可在右侧修改显示名称、Base URL、API 类型和 API Key。

新增供应商：

1. 点击“新增”。
2. 填写 Provider ID、名称、Base URL 和 API 类型。
3. 点击“保存供应商”。
4. 点击“拉取模型”从服务端多选导入，或点击“增加模型”手工输入 Model ID。

“测试连接”会使用当前表单中的 Base URL 和 API Key 请求模型接口。网络请求在后台运行，不会阻塞窗口。使用 `$ENV_VAR` Key 时，需要先在启动 piswitch 的环境中设置对应变量。

“拉取模型”窗口默认不选择任何模型。可点击单行或聚焦后按空格切换勾选状态，也可使用“全选”和“清空”批量操作。

保存第三方 `openai-completions` 供应商时，piswitch 会在 `compat` 中补充安全默认值：启用会话亲和请求头，并关闭长缓存参数。已有 `compat` 显式设置优先，不会被默认值覆盖。
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
python3 -m py_compile core.py piswitch.py
bash -n bin/piswitch install.sh
```
