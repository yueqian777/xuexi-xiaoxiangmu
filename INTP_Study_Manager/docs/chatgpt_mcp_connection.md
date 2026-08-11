# ChatGPT 与 Study Manager MCP 的连接边界

## 当前真实状态

| 层 | 状态 | 说明 |
|---|---|---|
| Study Manager 本地业务 MCP | 已实现 | 14 个受控 Tool、user scope、权限、audit、Active Context |
| 本地 transport | 已实现 | 标准 stdio，不打开网络端口 |
| JSON Bridge fallback | 已实现并保留 | task ZIP / result JSON / Inbox |
| ChatGPT Web Secure Connection | 未在本仓库配置 | 需要独立连接层与对应 OpenAI 组织/工作区权限 |

**本地 MCP Server 已实现不等于网页版 ChatGPT 已经连接。** 本文档不声称任何 ChatGPT Plus、Enterprise 或其他网页工作区已完成实际连接验收。

## 本地 stdio 使用

先在项目根目录确认进程可启动：

```powershell
python -m study_mcp.server --transport stdio --user-id <CURRENT_USER_ID>
```

对能在本机直接拉起 stdio server 的 MCP host，配置形式为：

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

系统维护“ChatGPT / MCP”页会按当前环境生成可复制版本。这个配置不含 token，也不会产生可从公网访问的 URL。

## ChatGPT Web 还缺什么

缺的是 **Secure MCP Tunnel / Developer MCP connection 独立连接层**，不是 Study Manager 的业务 Tool。

OpenAI 官方的 [Secure MCP Tunnel 文档](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) 说明：tunnel client 在能访问私有 MCP server 的网络内发起 outbound HTTPS，将排队的 MCP 请求转发到本地，无需打开入站防火墙端口或把 server 暴露到公网。官方文档也将 Platform tunnel 权限与 ChatGPT developer-mode 权限明确区分。

因此下一步应是：

1. 在目标 OpenAI Platform 组织中申请/确认 Tunnels Read + Use；创建或编辑 tunnel 还需 Tunnels Read + Manage。
2. 在目标 ChatGPT workspace 中申请并启用 developer mode；具体可用性以当前账户、plan 和 workspace 策略为准。
3. 在本机启动官方 `tunnel-client`，使它可以拉起或到达 Study Manager 的 stdio server。
4. tunnel 身份和 runtime API key 只交给 tunnel client 的安全配置/环境；不写入 Study Manager SQLite、`app_settings`、页面或 stdio 配置文本。
5. 在目标 ChatGPT 环境选择该 tunnel endpoint，再做端到端 Tool 验收。

这些是独立连接步骤；它们不应修改或绕过 Study Manager 的本地 permission、user scope 和 audit。实际配置时应以当时的 OpenAI 官方文档和 workspace 管理策略为准。

## 不采用的连接方式

本仓库当前不实现公网 HTTP，不做下列处理：

- 不启动无鉴权 Flask/FastAPI endpoint；
- 不默认监听 `0.0.0.0`；
- 不把 SQLite 或 Streamlit 直接暴露到公网；
- 不把 CORS 设为 `*`；
- 不在 SQLite 明文保存 tunnel token；
- 不使用 ChatGPT DOM/Cookie 抓取或私有 API。

## 建议的端到端验收

完成独立连接层后，至少验证：

1. ChatGPT 只看到文档列出的 14 个 Tool，没有 delete Tool。
2. `study_get_current_context` 与 Streamlit 当前 deck/slide 一致。
3. 关闭 `read_reviews` 后调用今日复习返回 `permission_denied`，并产生当前用户 audit。
4. 关闭 `write_slide_explanation` 后不产生 DB 新记录；开启后只追加 `ChatGPT MCP` 版本。
5. 过期 fingerprint、错误 `slide_number`、跨用户资源都被拒绝。
6. JSON Bridge 仍可导入 `ChatGPT Web` 版本，与 MCP 版本并存且不覆盖。

在这组验收完成前，应始终将状态表述为“本地 MCP 可用，ChatGPT Web 连接待配置/待验证”。
