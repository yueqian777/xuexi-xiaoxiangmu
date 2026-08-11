# INTP Study Manager 本地 MCP

## 定位

Study MCP 是 INTP Study Manager 的本机受控读写适配层。它使用标准 MCP Python SDK，与 Streamlit 页面解耦，可以作为独立 stdio 进程启动。

```text
MCP client
    -> Study MCP Server (thin adapter)
    -> local permission check + audit metadata
    -> domain/services
    -> repository/db
    -> SQLite

ChatGPT Web file workflow
    -> JSON Bridge
    -> shared slide_explanation_write_service
    -> SQLite
```

MCP Tool 不包含业务 SQL。MCP 直接写和 JSON Bridge 都经过同一个逐页讲解写入 service，共享 user/deck/slide ownership、`slide_id` + `slide_number`、fingerprint、Unicode/长度、事务与 append-only 校验。

## 依赖与启动

`requirements.txt` 固定了官方 Python SDK 依赖：

```text
mcp==2.0.0
```

在项目根目录安装依赖后，用当前本地用户 ID 启动：

```powershell
python -m pip install -r requirements.txt
python -m study_mcp.server --transport stdio --user-id <CURRENT_USER_ID>
```

`--user-id` 是必填参数，也是这个 server 进程的固定业务边界；不要猜测或省略它。Tool 参数不接受临时 `user_id` 来切换用户。当前只实现 `stdio`，不启动 HTTP listener。stdio 的 stdout 用于 MCP 协议，运行日志不应混入 stdout。

系统维护中的“ChatGPT / MCP”页可复制与当前 Python、项目目录和 `user_id` 匹配的 stdio 配置。该配置不包含 token 或 API Key。

## 14 个 Tool

| Tool | 类型 | 本地权限 | 行为 |
|---|---|---|---|
| `study_get_current_context` | READ | `read_current_context` | 返回 Active Learning Context；无上下文时明确返回 `active: false` |
| `study_get_current_slide` | READ | `read_current_context` + `read_ppt` | 读当前页、section、最新讲解与受限上下页 |
| `study_read_slide_range` | READ | `read_ppt` | 读指定 deck 页码范围，每次最多 25 页 |
| `study_get_question_tree` | READ | `read_question_tree` | 读真实 root/child/grandchild 插问树 |
| `study_get_knowledge_card` | READ | `read_knowledge_cards` | 读单个当前用户知识卡 |
| `study_search_knowledge` | READ | `read_knowledge_cards` | 受限条数搜索知识卡 |
| `study_get_today_reviews` | READ | `read_reviews` | 读今日到期/逾期待复习任务 |
| `study_save_slide_explanation` | WRITE | `write_slide_explanation` | 追加一个 `ChatGPT MCP` 讲解版本，不覆盖旧版 |
| `study_save_slide_explanations` | WRITE | `write_slide_explanation` | 同 deck 批量追加，最多 25 页，整批事务 |
| `study_add_slide_question` | WRITE | `write_slide_question` | 通过现有 question repository 新建 root/child 插问 |
| `study_convert_question_to_knowledge` | WRITE | `write_knowledge_card` + `write_review` | 复用 question-to-knowledge 及原有复习任务逻辑 |
| `study_mark_question_understood` | WRITE | `write_slide_question` | 通过 domain service 标记插问已理解 |
| `study_create_review_for_question` | WRITE | `write_knowledge_card` + `write_review` | 复用原有转卡/复习任务 service |
| `study_submit_review_result` | WRITE | `write_review` | 通过 review domain service 提交复习结果 |

第一版没有 DELETE Tool。Tool 返回结构化 JSON；权限拒绝使用 `permission_denied`，业务错误不向 client 返回 traceback。

## Active Learning Context

Active Context 使用独立的 user-scoped `app_settings` key，记录当前 subject/deck/slide/question/selection 及更新时间。PPT reader 进入 deck、恢复当前页或收到现有 `reader_position` 页变化时同步它。

Active Context 不替代 reader position：

- reader position 继续负责 Streamlit/session/localStorage 的 UI 位置恢复；
- Active Context 只是对本地 MCP/domain 的统一查询面；
- 同内容写入幂等，不产生无意义的 `updated_at` 抖动；
- 跨用户、跨 deck 的 slide/question 会被拒绝。

## 本地权限

权限按 `user_id` 保存在 `app_settings`，Tool 执行前每次查询。默认值是：

| 权限 | 默认 |
|---|---|
| `read_current_context` | ON |
| `read_ppt` | ON |
| `read_question_tree` | ON |
| `read_knowledge_cards` | ON |
| `read_reviews` | OFF |
| `write_slide_explanation` | ON |
| `write_slide_question` | ON |
| `write_knowledge_card` | OFF |
| `write_review` | OFF |

管理页只更新这 9 个已知布尔值；不接受未知权限 key。

## Audit

`mcp_audit_logs` 记录：

```text
id, user_id, request_id, tool_name, operation_type,
target_type, target_id, success, permission_result, summary, created_at
```

客户端 request ID 先转换为 SHA-256 不透明标识再落库，不原样保存客户端可控文本。权限通过后，adapter 必须先创建 audit attempt 才执行 action；attempt 无法创建时操作 fail closed。action 完成后原位 finalize；极端情况下 finalize 失败，开始记录仍保留，Tool 返回 `audit_finalize_failed` warning，避免用户盲目重试追加写入。

读成功、写成功、业务失败和权限拒绝都会留下有界的元数据。Audit 不接受或保存完整 prompt、逐页讲解正文、长 PPT 内容、API Key 或 secret。管理页只按当前 `user_id` 查询最近记录。

## JSON Bridge fallback

文件桥接仍保留完整的 task ZIP、`manifest.json`、`slides.json`、`instructions.md`、`explanation_result.json`、fingerprint、Inbox 及完整/部分校验流程。

- 方式 A：MCP direct，可在权限开启时直接读取与追加。
- 方式 B：JSON Bridge，不依赖 MCP，作为 fallback。

两条路径最终追加不同 `model` 来源的 explanation 版本，不相互覆盖。

## 安全边界

- server 启动时绑定单一 `user_id`，所有 domain 查询再做 ownership 校验；
- stdio 不打开网络端口；
- 本项目不实现公网 HTTP，不默认监听 `0.0.0.0`；
- 不使用 Selenium/Playwright/DOM 抓取、Cookie 或私有 ChatGPT API；
- runtime status 只保存 PID、不可读业务内容的进程创建身份、`stdio`、启停时间和版本，用创建身份防止 PID 复用误报；不保存命令行、token 或 secret；
- 不能把“本地 MCP Server 可运行”解释为“ChatGPT Web 已连接”。

ChatGPT Web 仍需独立的 Secure MCP Tunnel / Developer MCP connection 层，见 [chatgpt_mcp_connection.md](chatgpt_mcp_connection.md)。
