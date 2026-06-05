# Opus 智能体框架

**Opus** 是自研的智能体框架，集 **OpenClaw**、**Hermes**、**Codex** 的所有优点，主要用于 **OPC 公司**工作。支持灵活切换**对话式 AI**、**任务式工作流**和 **API 服务**。

## 🌟 特性

- ✅ **多源技能支持**：自动发现 Codex、OpenClaw、Hermes 生态中的技能
- 🔎 **本地 TF-IDF 匹配**：无需远程 LLM，零 API Key，完全本地化运行
- 🖥️ **交互式 CLI**：支持 `/list`、`/show`、`/run`、`/ref`、`/reload` 等命令
- 🌐 **HTTP API 服务**：提供 RESTful API，便于集成到其他系统
- 📋 **工作流引擎**：支持 YAML 定义的自动化工作流（含 LLM 步骤）
- 📦 **自动解压**：支持 `.zip` 技能包自动解压和增量更新
- ⚙️ **YAML 配置**：灵活的技能源和工作流配置
- 🔄 **多模式切换**：对话模式、工作流模式、API 模式
- 🪟 **跨平台支持**：Windows PowerShell 模拟执行 Shell 脚本
- 🤖 **多模型支持**：OpenAI、Anthropic、DeepSeek、豆包、本地模型等
- 🔑 **统一密钥管理**：所有 API Key 集中存储在 `data/Opus.json`

## 🏢 OPC 公司专属

Opus 框架专为 OPC 公司设计，提供以下企业级特性：

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **对话模式** | 自然语言交互 | 客服、咨询、日常问答 |
| **工作流模式** | 任务自动化编排 | 业务流程、批量处理 |
| **API 模式** | 标准化接口服务 | 系统集成、第三方调用 |

## 📁 项目结构

```
Opus/
├── main.py                    # 开发验证入口（万能接口）
├── config.yaml                # 技能源与工作流配置
├── requirements.txt           # Python 依赖
├── README.md                  # 项目说明文档
├── 开发OPC项目智能体.md        # 开发文档
├── application/               # 部署入口
│   ├── cli/main.py            # 生产环境 CLI
│   ├── api/api_server.py      # 生产环境 HTTP API 服务
│   └── web/index.html         # Web 前端页面
├── src/                       # 核心源码
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── agent.py           # 智能体核心（对话管理、命令处理、LLM集成）
│   │   └── executor.py        # 脚本执行与资源读取（含 PowerShell 模拟）
│   ├── skill/
│   │   ├── __init__.py
│   │   ├── models.py          # Skill 数据模型
│   │   └── skill.py           # 技能加载、匹配与执行
│   ├── workflow/
│   │   ├── __init__.py
│   │   └── workflow.py        # 工作流加载与执行引擎（支持 LLM 步骤）
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py            # LLM 抽象基类和数据结构
│   │   ├── manager.py         # 模型管理器（多提供商支持、故障转移）
│   │   ├── session.py         # 会话管理器（对话历史管理）
│   │   └── adapters/          # 各模型提供商适配器
│   │       ├── __init__.py
│   │       ├── openai.py      # OpenAI/Azure/DeepSeek/豆包适配器
│   │       ├── anthropic.py   # Anthropic Claude 适配器
│   │       ├── gemini.py      # Google Gemini 适配器
│   │       └── local.py       # 本地模型适配器（Ollama/VLLM）
│   ├── ui/
│   │   ├── __init__.py
│   │   └── cli.py             # 命令行界面
│   ├── __init__.py
│   └── config.py              # 配置管理模块（从 Opus.json 加载）
└── data/                      # 数据目录
    ├── Opus.json              # API Key 配置文件（技能密钥、LLM 密钥）
    ├── skills/                # 技能包存放目录
    │   └── openclaw_skills/   # OpenClaw 技能（支持 zip 自动解压）
    │       ├── __unpacked__/   # 自动解压目录
    │       ├── search-2-0.1.0.zip
    │       └── bocha-web-search-1.0.2.zip
    └── workflows/             # 工作流定义目录
        ├── demo/workflow.yaml
        ├── test/workflow.yaml
        └── test1/workflow.yaml
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

编辑 `data/Opus.json`，配置所需的 API Key：

```json
{
  "api_keys": {
    "skills": {
      "tavily": {
        "name": "Tavily Search API",
        "api_key": "your-key",
        "enabled": true
      },
      "bocha": {
        "name": "Bocha Web Search API",
        "api_key": "your-key",
        "enabled": true
      }
    }
  }
}
```

### 3. 启动方式

#### 开发阶段（使用万能接口）

```bash
# 交互式模式（对话模式）
python main.py

# 快速测试意图匹配
python main.py -q "帮我构建一个 web 应用"

# 列出所有技能
python main.py --list skills

# 列出所有工作流
python main.py --list workflows

# 运行指定技能（关键字参数方式）
python main.py -e search -k query="AI news" -k max_results=5

# 运行技能（位置参数方式）
python main.py -e search -a '{"query": "AI news"}'

# 启动 API 服务（端口 8765）
python main.py --api

# 查看项目信息
python main.py --info
```

#### 部署阶段（使用 application 入口）

```bash
# CLI 模式
python application/cli/main.py

# API 服务模式
python application/api/api_server.py --host 0.0.0.0 --port 8080
```

## 📖 使用说明

### 交互模式命令

在交互式模式下输入以下命令：

| 命令 | 说明 |
| ---- | ---- |
| `/help` | 查看所有可用命令 |
| `/list [source]` | 列出所有技能；可指定来源过滤 |
| `/show <skill-name>` | 查看某个技能的完整说明与资源 |
| `/run <skill-name> [args...]` | 运行技能 `scripts/` 目录下的脚本 |
| `/ref <skill-name> <filename>` | 读取技能 `references/` 中的文件 |
| `/reload` | 重新扫描所有技能目录 |
| `/install` | 解压 zip 技能包并重新加载 |
| `/count` | 查看各来源的技能计数 |
| `/workflows` | 列出所有工作流 |
| `/workflow <name>` | 执行指定工作流 |
| `/history` | 查看最近对话历史 |
| `/clear` | 清空对话历史 |
| `/bye` / `/quit` | 退出 |

### CLI 命令行参数

```bash
# 快速操作
python main.py -q "构建 web 应用"     # 意图匹配查询
python main.py --list skills         # 列出技能
python main.py --list workflows      # 列出工作流

# 技能执行
python main.py -e search                      # 执行技能
python main.py -e search -k query="AI news"   # 带关键字参数
python main.py -e search -a '{"query": "AI"}' # 带位置参数(JSON)
python main.py -e search -s script.sh        # 指定脚本名

# 工作流
python main.py --workflow demo                # 执行工作流
python main.py --workflow demo --inputs '{"query":"测试"}'

# API 服务
python main.py --api --host 0.0.0.0 --port 8765

# 显示信息
python main.py --info    # 项目信息
python main.py --help    # 帮助信息
```

### 参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `-q/--query TEXT` | 意图匹配查询 | `-q "搜索 AI 新闻"` |
| `-l/--list [TYPE]` | 列出资源：skills/workflows | `--list skills` |
| `-e/--execute SKILL` | 执行指定技能 | `-e search` |
| `-s/--script SCRIPT` | 指定脚本名 | `-s search.sh` |
| `-a/--arg VAL` | 添加位置参数（可多次） | `-a "arg1" -a "arg2"` |
| `-k/--kwarg KEY=VAL` | 添加关键字参数（可多次） | `-k query=test` |
| `-w/--workflow NAME` | 执行工作流 | `-w demo` |
| `--inputs JSON` | 工作流输入参数 | `--inputs '{"query":"test"}'` |
| `--api` | 启动 API 服务 | `--api` |
| `--host HOST` | API 监听地址 | `--host 0.0.0.0` |
| `--port PORT` | API 监听端口 | `--port 8080` |

### API 接口

启动 API 服务后访问：

| 接口 | 方法 | 说明 |
| ---- | ---- | ---- |
| `/health` | GET | 健康检查 |
| `/api/skills` | GET | 列出所有技能 |
| `/api/skills/{name}` | GET | 技能详情 |
| `/api/ask` | POST | 智能问答 |
| `/api/run` | POST | 运行技能脚本 |
| `/api/ref` | POST | 读取参考文档 |
| `/api/reload` | POST | 重新加载技能 |
| `/api/install` | POST | 安装/解压技能 |
| `/api/workflows` | GET | 列出工作流 |
| `/api/workflows/{name}` | GET | 工作流定义 |
| `/api/workflows/run` | POST | 运行工作流 |

#### API 使用示例

```bash
# 健康检查
curl http://localhost:8765/health

# 智能问答
curl -X POST http://localhost:8765/api/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "帮我写一个 Python 脚本", "top_k": 5}'

# 运行技能
curl -X POST http://localhost:8765/api/run \
  -H "Content-Type: application/json" \
  -d '{"skill": "search", "args": [{"query": "AI news"}]}'

# 运行工作流
curl -X POST http://localhost:8765/api/workflows/run \
  -H "Content-Type: application/json" \
  -d '{"name": "demo", "inputs": {"query": "测试"}}'
```

## ⚙️ 配置说明

### 技能源配置

编辑 `config.yaml` 中的 `skill_roots`：

```yaml
skill_roots:
  # 项目本地技能目录（推荐）
  - name: "data-openclaw"
    path: "./data/skills/openclaw_skills"
    format: "openclaw"

  - name: "data-hermes"
    path: "./data/skills/hermes_skills"
    format: "hermes"

  - name: "data-codex"
    path: "./data/skills/codex_skills"
    format: "codex"

  # 系统已安装的技能（可选）
  - name: "codex-system"
    path: "${HOME}/.codex/skills/.system"
    format: "codex"

  - name: "hermes-penelope"
    path: "${HOME}/.trae-cn/builtin/trae/penelope/skills"
    format: "hermes"
```

### 工作流配置

```yaml
workflow_roots:
  - name: "local-workflows"
    path: "./data/workflows"
```

### 运行时配置

```yaml
# 对话历史长度（保留最新 N 轮）
history_limit: 20

# 匹配技能的最低相关度（0-1）
min_relevance: 0.15
```

### API Key 配置

编辑 `data/Opus.json`，集中管理所有 API Key：

```json
{
  "version": "1.0",
  "name": "Opus",
  "api_keys": {
    "skills": {
      "tavily": {
        "name": "Tavily Search API",
        "api_key": "your-api-key",
        "enabled": true,
        "endpoint": "https://api.tavily.com/search"
      },
      "bocha": {
        "name": "Bocha Web Search API",
        "api_key": "your-api-key",
        "enabled": true,
        "endpoint": "https://api.bocha.cn/v1/web-search"
      }
    },
    "llm": {
      "openai": {
        "name": "OpenAI API",
        "api_key": "your-api-key",
        "enabled": false,
        "endpoint": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
        "default_model": "gpt-4o"
      },
      "deepseek": {
        "name": "DeepSeek API",
        "api_key": "your-api-key",
        "enabled": true,
        "endpoint": "https://api.deepseek.com/v1",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "default_model": "deepseek-v4-flash"
      },
      "doubao": {
        "name": "豆包 API",
        "api_key": "your-api-key",
        "enabled": false,
        "endpoint": "https://api.doubao.com/v1",
        "models": ["Doubao-3.5", "Doubao-4"],
        "default_model": "Doubao-3.5"
      },
      "local": {
        "name": "本地模型",
        "api_key": "",
        "enabled": false,
        "endpoint": "http://localhost:8080/v1",
        "models": ["qwen2-7b-chat", "llama3"],
        "default_model": "qwen2-7b-chat"
      }
    }
  },
  "settings": {
    "default_llm": "deepseek",
    "default_search": "bocha",
    "auto_reload": true,
    "log_level": "INFO",
    "mode": "conversation"
  }
}
```

### LLM 支持的提供商

| 提供商 | 模型示例 | 说明 |
|--------|----------|------|
| `openai` | gpt-4o, gpt-4-turbo | OpenAI 官方 API |
| `anthropic` | claude-3-opus, claude-3-sonnet | Anthropic Claude |
| `deepseek` | deepseek-v4-flash, deepseek-v4-pro | DeepSeek |
| `doubao` | Doubao-3.5, Doubao-4 | 字节跳动豆包 |
| `google` | gemini-pro | Google Gemini |
| `azure` | - | Azure OpenAI |
| `local` | qwen2-7b-chat, llama3 | 本地模型（Ollama/VLLM） |

## 📦 技能格式

智能体自动递归扫描每个目录，查找包含 `SKILL.md`（大小写不敏感）的文件夹。

### SKILL.md 格式

```yaml
---
name: my-custom-skill
description: Describe what this skill does (用于意图匹配的主要依据)
license: MIT-0
homepage: https://example.com
metadata:
  openclaw:
    emoji: "🔧"
    requires:
      env:
        - API_KEY
    primaryEnv: API_KEY
---

# 技能说明

这里写 Markdown 正文，包含使用说明、API、示例等。

## 目录结构

scripts/     # 可执行脚本（Python/PowerShell/Bash）
references/  # 参考文档  
assets/      # 资源文件
```

### 技能包格式

支持直接放置 `.zip` 技能包到技能目录，智能体会自动解压：

```
data/skills/openclaw_skills/
├── search-2-0.1.0.zip          # 技能包（会自动解压）
├── bocha-web-search-1.0.2.zip  # 技能包
└── __unpacked__/
    ├── search-2-0.1.0/         # 解压后的技能目录
    │   ├── SKILL.md
    │   ├── _meta.json
    │   └── scripts/
    │       └── search.sh
    └── bocha-web-search-1.0.2/
        ├── SKILL.md
        ├── _meta.json
        ├── skill-card.md
        └── scripts/
            └── bocha-web-search.py
```

## 📋 工作流定义

工作流文件位于 `data/workflows/<name>/workflow.yaml`：

```yaml
name: "demo"
description: "示例工作流"
inputs:
  - name: query
    type: string
    default: "构建前端 web 应用"

steps:
  - id: list_skills
    action: list
    source: ""

  - id: ask_step
    action: ask
    query: "{{inputs.query}}"
    depends_on:
      - list_skills

  - id: show_best
    action: show
    skill: search
    depends_on:
      - ask_step

  - id: final_log
    action: log
    text: "工作流完成。"
    depends_on:
      - show_best
```

### 支持的工作流动作

| action | 说明 | 参数 |
| ------ | ---- | ---- |
| `ask` | 意图匹配查询 | `query`, `top_k` |
| `list` | 列出技能 | `source`（可选） |
| `show` | 显示技能详情 | `skill` |
| `run` | 运行技能脚本 | `skill`, `args` |
| `ref` | 读取参考文档 | `skill`, `file` |
| `reload` | 重新加载技能 | - |
| `workflow` | 嵌套调用工作流 | `workflow`, `inputs` |
| `log` | 日志记录 | `text` |
| `llm` | 调用大模型生成文本 | `prompt`, `provider`, `model`, `max_tokens`, `temperature` |

## 🧩 作为库使用

### 基础用法

```python
from src.agent.agent import Agent
from src.skill.skill import create_skill_manager

# 初始化智能体
agent = Agent("config.yaml")
print(f"已加载 {len(agent.list_skills())} 个技能")

# 意图匹配
resp = agent.ask("帮我创建一个 Python 脚本")
print(resp.reply)

# 获取匹配到的技能
for skill, score in resp.matched_skills:
    print(f"  [{skill.source}] {skill.name} ({score:.2f})")

# 运行技能脚本（方式1：通过 Agent）
result = agent.ask("/run search")
print(result.reply)

# 运行技能脚本（方式2：直接调用）
mgr = create_skill_manager("config.yaml")
json_args = '{"query": "AI news", "max_results": 5}'
result = mgr.execute_skill("search", args=[json_args])
print(result.stdout)

# 执行工作流
wf_result = agent.run_workflow("demo", inputs={"query": "测试"})
print(f"工作流 {wf_result.name}: {'成功' if wf_result.ok else '失败'}")
```

### LLM 调用

```python
from src.llm import ModelManager

# 创建模型管理器
manager = ModelManager("data/Opus.json")

# 获取默认模型
llm = manager.get_default_model()
print(f"当前模型: {llm.provider}")

# 文本生成
result = llm.generate("写一首关于春天的诗", max_tokens=300)
if result.ok:
    print(result.content)

# 对话模式
with manager.session("my_session") as session:
    response = session.chat("你好")
    print(response.content)
    
    response = session.chat("请介绍一下你自己")
    print(response.content)

# 通过 Agent 调用 LLM
agent = Agent("config.yaml")
result = agent.llm_generate("写一个 Python 函数示例", max_tokens=200)
print(result.content)

# 列出可用模型
models = agent.llm_list_models()
for m in models:
    print(f"- {m['provider']}: {m['name']}")
```

## 🔧 技能执行方式

### 关键字参数（推荐）

```bash
python main.py -e search -k query="AI news" -k max_results=5
```

### 位置参数（JSON格式）

```bash
# PowerShell 中使用
python main.py -e search -a '{"query": "AI news"}'

# 或使用变量
$json = '{"query": "AI news", "max_results": 5}'
python main.py -e search -a $json
```

### 从大模型获取参数

```python
import json
from src.skill.skill import create_skill_manager

# 大模型生成的参数
llm_output = {
    "query": "AI news",
    "max_results": 5,
    "search_depth": "advanced"
}

# 执行技能
mgr = create_skill_manager("config.yaml")
json_args = json.dumps(llm_output)
result = mgr.execute_skill("search", args=[json_args])
```

## 📝 输出示例

```
已加载 2 个技能。输入 /help 查看帮助，输入 /bye 退出。

你> AI news
Agent>
我为你找到这些相关技能：

1. [openclaw] search  (相关度 0.95)
   Search the web using Tavily's LLM-optimized search API.
   路径: data/skills/openclaw_skills/__unpacked__/search-2-0.1.0
   脚本: search.sh

2. [openclaw] bocha-web-search  (相关度 0.88)
   博查 Web 搜索工具，使用 Bocha Web Search API。
   路径: data/skills/openclaw_skills/__unpacked__/bocha-web-search-1.0.2
   脚本: bocha-web-search.py

建议的下一步：
  - 输入 /show search   查看完整技能说明
  - 输入 /run search    执行该技能的脚本
```

## 🔒 安全说明

- `/run` 会直接执行技能目录下 `scripts/` 中的脚本，请**只对你信任的技能目录使用**
- 默认智能体不会自动执行任何脚本（需要显式使用 `/run`）
- 脚本执行超时为 120 秒
- API 服务默认监听 localhost，生产环境请配置防火墙
- API Key 存储在 `data/Opus.json`，请妥善保管

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

**Opus - OPC 公司专属智能体框架**