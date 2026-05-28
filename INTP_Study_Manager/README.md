# INTP Study Manager

本项目是一个本地运行的智能学习管理应用，服务于“INTP 问题驱动学习法”。它不是普通待办事项工具，而是围绕学习闭环设计：学习登记、主线讲解整理、中途插问、闭卷回忆、错因分析、1-3-7-14 间隔复习、每日复盘和长期知识追踪。

## 安装方法

建议在项目目录中创建虚拟环境后安装依赖：

```powershell
pip install -r requirements.txt
```

## 启动命令

```powershell
streamlit run app.py
```

启动后浏览器会打开 Streamlit 页面，所有数据保存在本地 SQLite 文件：

```text
data/study_manager.db
```

## 使用流程

1. 打开首页 Dashboard，先查看今天需要复习什么。
2. 进入“学习登记”，记录日期、科目、主题、核心问题、已掌握内容、卡点和掌握度。
3. 进入“知识点卡片”，把重要内容整理成三层模型：一句话解释、公式 / 逻辑推导、典型题 / 应用。
4. 创建知识点卡片时勾选“创建 1-3-7-14 复习任务”，系统会自动生成复习计划。
5. 进入“闭卷测试 Prompt”，选择学习记录或知识点卡片，复制 Prompt 给 ChatGPT。
6. 进入“复习计划”，完成复习后标记结果，系统会自动调整掌握度和后续复习。
7. 学习中暂时不处理的问题放进“探索停车场”，避免打断主线。

## 每日复盘提醒

进入“每日复盘提醒”页面后，可以设置每天的复盘提醒时间，默认是 21:00。点击“安装 / 更新计划任务”后，系统会在 Windows 计划任务中创建本地提醒；到点会弹窗并打开 INTP Study Manager。

注意：这个功能依赖电脑开机并登录 Windows，不是邮件提醒，也不依赖 OpenAI API。完成复盘后，可以在页面中点击“标记今天已完成复盘”，首页 Dashboard 会显示今日复盘状态。

## API 接入设置

项目支持多种 AI API 接入，不再固定依赖 OpenAI 官方接口。进入”API 接入设置”页面后，可以选择或新增 Provider。

当前内置模板包括：

### 国际主流

| Provider | API 类型 | 默认模型 | 环境变量 |
|---|---|---|---|
| OpenAI Responses | OpenAI Responses API | gpt-5.5 | `OPENAI_API_KEY` |
| OpenAI 兼容接口 | OpenAI Chat Completions | gpt-5.5 | `OPENAI_API_KEY` |
| Anthropic Messages | Anthropic Messages API | claude-sonnet-4-5 | `ANTHROPIC_API_KEY` |
| Google Gemini | Google Gemini generateContent | gemini-2.5-pro | `GEMINI_API_KEY` |
| Mistral AI | OpenAI Chat Completions | mistral-large | `MISTRAL_API_KEY` |
| Cohere | Cohere Chat API | command-r-plus | `COHERE_API_KEY` |
| Grok (xAI) | OpenAI Chat Completions | grok-3 | `XAI_API_KEY` |
| Groq | OpenAI Chat Completions | llama-4-scout | `GROQ_API_KEY` |
| Perplexity | OpenAI Chat Completions | sonar-pro | `PERPLEXITY_API_KEY` |

### 国内主流

| Provider | API 类型 | 默认模型 | 环境变量 |
|---|---|---|---|
| 智谱 AI (GLM) | OpenAI Chat Completions | glm-4-flash | `ZHIPU_API_KEY` |
| 阿里云通义千问 (Qwen) | OpenAI Chat Completions | qwen-max | `DASHSCOPE_API_KEY` |
| 腾讯混元 (Hunyuan) | OpenAI Chat Completions | hunyuan-pro | `HUNYUAN_API_KEY` |
| Kimi (Moonshot) | OpenAI Chat Completions | moonshot-v1-128k | `MOONSHOT_API_KEY` |
| 字节豆包 (Doubao) | OpenAI Chat Completions | doubao-pro-32k | `DOUBAO_API_KEY` |
| MiniMax | MiniMax Chat API | MiniMax-M2.7 | `MINIMAX_API_KEY` |
| MIMO Token Plan | OpenAI Chat Completions | mimo-v2.5-pro | `MIMO_TOKEN_PLAN_API_KEY` |
| 硅基流动 (SiliconFlow) | OpenAI Chat Completions | Qwen2.5-72B-Instruct | `SILICONFLOW_API_KEY` |
| DeepSeek V4 Pro | OpenAI Chat Completions | deepseek-v4-pro | `DEEPSEEK_API_KEY` |

### 其他

| Provider | API 类型 | 默认模型 | 环境变量 |
|---|---|---|---|
| 本地 CLIProxyAPI | OpenAI Chat Completions | gpt-5.5 | `CLIPROXY_API_KEY` |
| 幻城网安 API | OpenAI Chat Completions | auto | `IAMHC_API_KEY` |
| 自定义 HTTP JSON API | 自定义 HTTP JSON | - | - |

API Key 默认不会写入 SQLite，也不会保存到项目文件。你可以在页面中临时输入，也可以使用环境变量。

例如 OpenAI：

```powershell
setx OPENAI_API_KEY "你的 API Key"
```

例如本地 CLIProxyAPI：

```powershell
setx CLIPROXY_API_KEY "local-client-key"
```

例如幻城网安 API：

```powershell
setx IAMHC_API_KEY "你在 api.iamhc.cn 控制台创建的 sk- 令牌"
```

例如 DeepSeek：

```powershell
setx DEEPSEEK_API_KEY "你的 DeepSeek sk- 令牌"
```

重新打开终端后启动应用，或在页面中临时输入 API Key。

### 自定义 HTTP JSON API

如果某个平台不属于内置类型，可以新增“自定义 HTTP JSON”：

1. Base URL / Endpoint 填完整 POST 地址。
2. 选择鉴权方式，例如 Bearer、x-api-key、query key 或 none。
3. 填写额外请求头 JSON。
4. 填写请求体模板。
5. 填写响应文本路径。

请求体模板可用变量：

```text
{prompt}
{model}
{max_output_tokens}
```

响应路径示例：

```text
choices.0.message.content
candidates.0.content.parts.0.text
content.0.text
output_text
```

## PPT 逐页讲解

进入“PPT 逐页讲解”页面后：

1. 上传 `.pptx` 或 `.pdf` 文件。
2. 选择 PPT / PDF 资料。
3. 在“AI API 设置”里选择 Provider。
4. 点击“生成 / 修复原页面图片”，确保每页都有原页面预览。
5. 点击“生成整份资料逐页讲解”，AI 会按页依次分析整份资料。
6. 在同步阅读器左侧滚动原页面，右侧讲解会自动同步到当前可见页。
7. 点击“打开插问浮窗”，提问不会覆盖主线讲解，而是单独保存为对应页的插问记录。

当前版本优先保证本地可运行和学习流不中断。PPTX 会通过本机 PowerPoint 导出原始页面图片；PDF 会通过 PyMuPDF 渲染为页面图片并提取文字。如果 PDF 是扫描版图片，页面会保留原图，并可在“PDF 无法提取文字时，把当前页原图直接发给支持视觉的 API”开启后把页面图片传给支持视觉输入的 OpenAI 兼容模型。

## 每日学习流程示例

以“信号与系统”为例：

1. 在“学习登记”添加主题：Z 反变换、系统稳定性、极零图。
2. 核心问题填写：一个离散系统如何被表示、分析、判断稳定性，并最终画成结构或频率响应？
3. 卡点填写：Z 反变换为什么必须看 ROC；极点和频率响应曲线的关系不熟。
4. 掌握度设置为 60，并勾选需要复习。
5. 在“知识点卡片”创建“Z 反变换”卡片，补充一句话解释、逻辑推导和典型应用。
6. 在“闭卷测试 Prompt”生成测试问题，复制到 ChatGPT 进行闭卷回忆。

## 如何复制 Prompt 到 ChatGPT

进入“闭卷测试 Prompt”页面，选择学习记录或知识点卡片。页面会生成 Markdown Prompt，Streamlit 代码块右上角有复制按钮，也可以手动全选复制后粘贴到 ChatGPT。

## 如何备份 SQLite 数据库

关闭 Streamlit 后，复制下面这个文件即可完成备份：

```text
data/study_manager.db
```

建议按日期备份，例如：

```text
study_manager_2026-05-20.db
```

## 后续扩展方向

1. 增强主线与插问：支持会话级问题树、插问复习队列和主线恢复提示。
2. 增强错因本：把错因和知识点、复习任务深度关联。
3. 增加搜索：按科目、章节、知识点、错因、停车场问题搜索。
4. 增加图表：掌握度趋势、高频错因、复习完成率。
5. 增加导出：支持 CSV / Markdown 导出学习记录和知识卡片。
6. 增强 PPT 视觉渲染：支持把 PPT/PDF 转为逐页图片并保留原始版式。
7. 增强 OpenAI API：加入流式输出、模型配置和更细的提问历史管理。
