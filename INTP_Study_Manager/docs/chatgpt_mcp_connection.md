# ChatGPT Web + Secure MCP Tunnel 插件建立 Runbook

本文是面向操作者和自动化 Agent 的完整配置手册。它建立的是 ChatGPT Developer Mode 中的私有 Study MCP App，不是公开插件商店包。

OpenAI Docs：[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。官方说明中，`tunnel-client` 从本地网络发起 outbound HTTPS，把 OpenAI 侧排队的 MCP 请求转发给本地 stdio/HTTP server；不需要开放入站防火墙端口。Secure MCP Tunnel 支持私有连接和开发模式测试，不用于公开插件提交。

## 1. 组成与可复现边界

```text
ChatGPT Developer Mode App
    -> OpenAI-hosted Tunnel endpoint
    -> tunnel-client（本机，outbound HTTPS）
    -> python -m study_mcp.server（stdio）
    -> local permission + ownership + audit
    -> Study Manager services / SQLite
```

| 层 | 仓库是否提供 | 说明 |
|---|---|---|
| Study MCP | 是 | 14 个受控 Tool、固定 `user_id`、权限、audit、Active Context |
| stdio transport | 是 | 不监听公网端口 |
| JSON Bridge fallback | 是 | task ZIP / result JSON / Inbox，与 MCP 并存 |
| Tunnel profile | 否 | 每台机器独立生成，包含外部环境标识，不提交 |
| Platform Tunnel / runtime key | 否 | 属于目标 OpenAI Platform 组织 |
| ChatGPT App | 否 | 属于目标 ChatGPT workspace |

因此，`main` 分支只能保证本地 MCP 和可复现 Runbook 存在，不能编码某个账户当前是否已连接。**本地 MCP Server 可运行不等于 ChatGPT Web 已连接；Tool 能被发现也不等于 Tool 已实际调用。**

## 2. Agent 执行约定

Agent 开始前必须阅读 `AGENTS.md`、根 `README.md`、本文和 `study_manager_mcp.md`，并检查当前进程/profile，避免影响另一条 Tunnel。

Agent 可以在已授权范围内自动完成：

- 检查仓库、Python、依赖和本地测试；
- 从 Study Manager 页面读取当前用户对应的 stdio 配置；
- 使用操作者明确提供的 `user_id`、`tunnel_id` 和 profile 名生成本机 profile；
- 运行 `doctor`、前台 `run`、health/readiness 检查和只读 Tool 验证；
- 读取有界日志和 MCP audit，但不得输出正文、密钥或完整私有路径。

以下步骤若没有本次任务的明确授权，Agent 必须暂停并请操作者处理或确认：

- 登录 OpenAI Platform/ChatGPT；
- 选择或改变 Platform 组织、ChatGPT workspace 关联；
- 创建/修改/删除 Tunnel，授予角色或权限；
- 创建 runtime API key，或把 key 输入本机；
- 创建、替换或删除 ChatGPT App；
- 覆盖已有 profile、停止已有 Tunnel、执行任何写入 Tool。

永远不要把 runtime key、admin key、真实 `tunnel_id`、真实 `app_id`、个人 profile、数据库、日志或健康 URL 文件提交到 Git。Agent 不应要求操作者把 key 粘贴到聊天中。

## 3. 前置条件

1. 能安装 `requirements.txt` 的 Python 环境。
2. OpenAI 官方最新 `tunnel-client`。从 [Platform Tunnel 设置](https://platform.openai.com/settings/organization/tunnels)或官方文档指向的 latest release 获取，不在 Runbook 中硬编码版本下载地址。
3. 一个 Platform `tunnel_id` 和单独的 runtime API key。
4. runtime key 对应主体具备 `Tunnels Read + Use`。创建或编辑 Tunnel 的操作者另需 `Tunnels Read + Manage`。
5. 目标 ChatGPT workspace 已允许 Developer Mode，并被关联到该 Tunnel。Platform Tunnel 权限与 ChatGPT Developer Mode 是两套独立权限。
6. 本机允许访问 `api.openai.com:443`，并能在本机启动 Study MCP stdio 命令。

Tunnel 可以同时关联 Platform 组织和 ChatGPT workspace。增加关联不会创建第二条 Tunnel；应把目标 ChatGPT workspace 和需要调用它的 Platform 组织都关联到同一个 `tunnel_id`。

## 4. 克隆、安装和确认本地 MCP

Windows PowerShell：

```powershell
git clone https://github.com/yueqian777/xuexi-xiaoxiangmu.git
Set-Location .\xuexi-xiaoxiangmu\INTP_Study_Manager

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m study_mcp.server --help
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_study_mcp*.py"
```

然后启动应用：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

登录后进入“系统维护 → ChatGPT / MCP”：

1. 确认当前用户 ID；
2. 检查需要的读取/写入权限；
3. 点击“复制 MCP 配置”；
4. 保存其中的 Python 路径、项目目录和 `--user-id`，但不要把本地绝对路径提交到仓库。

`--user-id` 是 server 进程的固定业务边界，不能省略或猜测。对本地 MCP host，复制配置形如：

```json
{
  "mcpServers": {
    "intp-study-manager": {
      "command": "C:\\Path\\To\\python.exe",
      "args": [
        "-m",
        "study_mcp.server",
        "--transport",
        "stdio",
        "--user-id",
        "<CURRENT_USER_ID>"
      ],
      "cwd": "D:\\Path\\To\\INTP_Study_Manager"
    }
  }
}
```

## 5. 在 Platform 创建或复用 Tunnel

1. 打开目标组织的 [Platform Tunnel 设置](https://platform.openai.com/settings/organization/tunnels)。
2. 先确认页面右上角/组织选择器处于目标组织；不要凭名称猜组织。
3. 复用已有 Study Manager Tunnel，或在具有 `Read + Manage` 时创建新 Tunnel。
4. 在 Associations 中加入：
   - 拥有/管理 Tunnel 的 Platform 组织；
   - 要在其中创建 App 的 ChatGPT workspace；
   - 若 Codex/Responses API 从另一组织调用，再加入该 Platform 组织。
5. 记录 `tunnel_id` 到本机临时变量或安全配置，不写进仓库。
6. 为长期运行客户端创建独立 runtime API key；不要把 Platform admin key 用作 daemon key。

如果 Agent 只有 `Read + Use`，它可以运行客户端和选择 Tunnel，但不能擅自创建/编辑 Tunnel。

## 6. 生成独立 tunnel-client profile

规范命令顺序是 `tunnel-client init` → `tunnel-client doctor` → `tunnel-client run`；下面用 PowerShell 变量保存二进制路径，避免假设它已经加入 `PATH`。

先切回 `INTP_Study_Manager` 项目根目录。下面所有占位符都必须由操作者或当前环境确认后替换：

```powershell
$TunnelClient = "D:\Tools\tunnel-client\tunnel-client.exe"
$TunnelId = "<TUNNEL_ID>"
[int]$UserId = <CURRENT_USER_ID>
$Python = (Resolve-Path ".\.venv\Scripts\python.exe").Path
$Launcher = (Resolve-Path ".\scripts\run_study_mcp.py").Path
$McpCommand = "`"$Python`" -X utf8 `"$Launcher`" --transport stdio --user-id $UserId"

& $TunnelClient help quickstart
& $TunnelClient init `
  --sample sample_mcp_stdio_local `
  --profile intp-study-manager `
  --tunnel-id $TunnelId `
  --mcp-command $McpCommand `
  --health-listen-addr "127.0.0.1:0"
```

不要默认加 `--force`。如果 profile 已存在，先只读检查它是否属于本项目；覆盖必须得到明确批准。`127.0.0.1:0` 会分配独立的回环端口，避免与 Zotero 或其他 Tunnel 的管理端口冲突。

`scripts/run_study_mcp.py` 会先定位仓库根目录，再启动真正的 `study_mcp.server`。因此 Tunnel profile 可以从任意工作目录启动，不依赖 profile 不支持的 `cwd` 字段。不要把 launcher 复制到仓库外后修改；它必须留在项目的 `scripts` 目录中。

### macOS / Linux 等价配置

```bash
cd "/absolute/path/xuexi-xiaoxiangmu/INTP_Study_Manager"
python3 -m venv .venv
./.venv/bin/python -m pip install -U pip
./.venv/bin/python -m pip install -r requirements.txt

TUNNEL_CLIENT="/absolute/path/to/tunnel-client"
TUNNEL_ID="<TUNNEL_ID>"
USER_ID="<CURRENT_USER_ID>"
PYTHON="$(pwd)/.venv/bin/python"
LAUNCHER="$(pwd)/scripts/run_study_mcp.py"
MCP_COMMAND="\"$PYTHON\" -X utf8 \"$LAUNCHER\" --transport stdio --user-id $USER_ID"

"$TUNNEL_CLIENT" help quickstart
"$TUNNEL_CLIENT" init \
  --sample sample_mcp_stdio_local \
  --profile intp-study-manager \
  --tunnel-id "$TUNNEL_ID" \
  --mcp-command "$MCP_COMMAND" \
  --health-listen-addr "127.0.0.1:0"
```

runtime key 由操作者在本地终端使用 `read -rsp` 输入并 `export CONTROL_PLANE_API_KEY`；不要放入 shell rc、仓库 `.env` 或命令行参数。

## 7. 安全输入 runtime key

由操作者在准备运行 `tunnel-client` 的同一个 PowerShell 会话中输入。下面的写法不会把 key 明文放进命令历史；key 仍只存在于当前进程环境中：

```powershell
$RuntimeKey = Read-Host "OpenAI Tunnel runtime API key" -AsSecureString
$KeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($RuntimeKey)
try {
  $env:CONTROL_PLANE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($KeyPointer)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($KeyPointer)
  $RuntimeKey.Dispose()
}
Remove-Variable RuntimeKey,KeyPointer -ErrorAction SilentlyContinue
```

Agent 只能这样检查变量是否存在，禁止回显变量值：

```powershell
if ([string]::IsNullOrWhiteSpace($env:CONTROL_PLANE_API_KEY)) {
  throw "CONTROL_PLANE_API_KEY 尚未由操作者在当前终端设置。"
}
"CONTROL_PLANE_API_KEY is set (value hidden)"
```

客户端停止后可清理当前会话变量：

```powershell
Remove-Item Env:CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue
```

## 8. Doctor、启动和健康检查

为每条 Tunnel 使用独立 profile 和独立 health URL 文件：

```powershell
$HealthDirectory = Join-Path $env:LOCALAPPDATA "tunnel-client\health"
New-Item -ItemType Directory -Force -Path $HealthDirectory | Out-Null
$HealthUrlFile = Join-Path $HealthDirectory "intp-study-manager.url"
& $TunnelClient doctor --profile intp-study-manager --explain --json
& $TunnelClient run --profile intp-study-manager --health.url-file $HealthUrlFile
```

`run` 是长期前台进程，应保持该终端运行。另开一个 PowerShell 做只读检查：

```powershell
$HealthUrlFile = Join-Path $env:LOCALAPPDATA "tunnel-client\health\intp-study-manager.url"
$TunnelClient = "D:\Tools\tunnel-client\tunnel-client.exe"
& $TunnelClient health `
  --url-file $HealthUrlFile `
  --require-control-plane-poll `
  --json

$BaseUrl = (Get-Content -Raw -LiteralPath $HealthUrlFile -Encoding UTF8).Trim().TrimEnd("/")
Invoke-RestMethod "$BaseUrl/healthz"
Invoke-RestMethod "$BaseUrl/readyz"
Invoke-RestMethod "$BaseUrl/api/status" | ConvertTo-Json -Depth 8
```

只有 machine-readable health 返回 ready、至少一次 control-plane poll 成功、`healthz=live`、`readyz=ready` 且 `main` channel 的 probe 状态正常，才能继续创建 ChatGPT App。默认保持日志级别 `info`，不要启用会记录请求/响应正文的 raw HTTP logging。

如果由 Agent 长期托管，可把前台 `run` 替换为当前客户端提供的 `tunnel-client runtimes connect`，随后必须执行 `tunnel-client runtimes status intp-study-manager --json` 并确认进程、health 和 readiness；不要同时启动两套进程，也不要用 `nohup`、`disown` 或不可追踪的后台窗口。

## 9. 在 ChatGPT 创建 Developer Mode App

保持 `tunnel-client run` 正常运行：

1. 在目标 ChatGPT workspace 中打开 Settings → Security and login，启用 Developer Mode。Enterprise/Edu 环境可能需要 workspace 管理员先授权。可同时参考 OpenAI 官方的 [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt) 页面。
2. 打开 [ChatGPT Plugins](https://chatgpt.com/#settings/Connectors)，点击加号创建 Developer Mode App。
3. App 名称建议使用 `INTP Study Manager MCP`；Connection 选择 `Tunnel`。
4. 从列表选择目标 Tunnel，或填入已确认的 `tunnel_id`。
5. 保存后，在一个新对话的 Tool/插件菜单中附加该 App。

界面文案可能随产品更新变化；若 Tunnel 不出现，先排查 workspace association 和 `Tunnels Read + Use`，不要新建重复 Tunnel 来碰运气。

## 10. 端到端验收

### 10.1 先做只读真实调用

在附加 App 的 ChatGPT 对话中发送：

```text
只调用 INTP Study Manager 的 study_get_current_context，返回 active、deck_id、
slide_id 和 slide_number；不要调用任何写入 Tool。
```

随后同时核对：

1. ChatGPT 得到结构化 Tool 结果；
2. Tunnel 管理 UI `/ui` 或 `/api/logs` 中出现 `rpc_method=tools/call`，并且响应没有 error；
3. Study Manager“系统维护 → ChatGPT / MCP → 最近 MCP 操作”出现同一只读调用的 audit。

只看到 `tools/list`、Tool 菜单或本地 `doctor` 通过，都不能代替这次真实 `tools/call`。

### 10.2 再做受控权限验收

写入测试必须得到操作者确认，并优先使用专用测试 deck：

1. ChatGPT 应只看到 `study_manager_mcp.md` 中列出的 14 个 Tool，没有 delete Tool。
2. `study_get_current_context` 与 Streamlit 当前 deck/slide 一致。
3. 关闭 `read_reviews` 后调用今日复习应返回 `permission_denied`，并留下当前用户 audit。
4. 关闭 `write_slide_explanation` 时不应产生新记录；开启后只追加 `ChatGPT MCP` 版本，不覆盖旧讲解。
5. 过期 fingerprint、错误 `slide_number` 和跨用户资源必须被拒绝。
6. JSON Bridge 仍应能导入 `ChatGPT Web` 版本，并与 MCP 版本并存。

## 11. 多条 Tunnel 共存

不同项目的 Tunnel 不会天然互相覆盖，但必须各自使用：

- 不同 `tunnel_id`；
- 不同 profile 名；
- 不同 health URL 文件；
- 回环随机端口或不同固定端口；
- 独立的长期进程和 MCP command。

Agent 在停止、重启或覆盖前必须核对 PID、二进制路径、profile 和 channel command。不要因为 Study Manager 配置失败而停止 Zotero 或其他项目的 Tunnel。

## 12. 常见故障

### Tunnel 在 ChatGPT 中不可见

- 确认 Tunnel 关联了目标 ChatGPT workspace，而不只是 Platform 组织；
- 确认 App 创建者和 runtime key 主体具备 `Tunnels Read + Use`；
- 确认 Developer Mode 已启用；
- 权限刚修改时等待策略传播，然后刷新；
- 仍失败时运行 `doctor --explain`，不要创建同名重复 Tunnel。

### `doctor` 报找不到 `study_mcp`

- 回到 `INTP_Study_Manager` 根目录；
- 核对 `$Python` 指向已安装 `requirements.txt` 的环境；
- 运行 `$Python -m study_mcp.server --help`；
- 核对 profile 中的 `--user-id` 与当前用户一致。

### Tunnel healthy 但 Tool 调用失败

- 查看 `/api/status` 中 `main` channel 的 probe；
- 确认客户端仍在运行；
- 先调用只读 Tool；
- 检查本地权限和 MCP audit；
- 不要打开 raw HTTP logging 来换取正文日志。

### 返回 `permission_denied`

这是本地权限层的预期拒绝。进入“ChatGPT / MCP”按当前用户修改对应权限，保存后再试；不要绕过 permission service 或直接改数据库。

### 返回 stale fingerprint 或页码错误

重新读取当前页/范围，使用最新 `slide_id`、`slide_number` 和 fingerprint。不要猜资源 ID，也不要强制覆盖。

## 13. JSON Bridge fallback

没有 Tunnel 权限、Developer Mode 或 MCP write 能力时，继续使用“ChatGPT Web 逐页讲解”页面的 task ZIP / `explanation_result.json` / Inbox 工作流。JSON Bridge 和 MCP direct 最终都进入共享的 append-only 写入 service，来源分别记为 `ChatGPT Web` 和 `ChatGPT MCP`，不会互相覆盖。

## 14. Agent 完成时的回报格式

Agent 应只报告：

- 使用的仓库提交、Python 可执行文件是否可用、profile 名；
- 本地 MCP 测试结果；
- `doctor`、health、ready、main probe 状态；
- ChatGPT 是否产生真实 `tools/call` 和对应 audit；
- 14 个 Tool 是否完整、是否存在越权/写入拒绝；
- 仍需操作者完成的外部授权步骤。

不得在报告中包含 API key、token、完整个人 profile、真实 `tunnel_id/app_id`、业务正文或私有数据库内容。
