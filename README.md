# Opus 智能体框架

**Opus** 是自研的智能体框架，集 **OpenClaw**、**Hermes**、**Codex** 的所有优点，主要用于 **OPC 公司**工作。支持灵活切换**对话式 AI**、**任务式工作流**和 **API 服务**。

## 🌟 特性

- ✅ **多源技能支持**：自动发现 Codex、OpenClaw、Hermes 生态中的技能
- 🔎 **本地 TF-IDF 匹配**：无需远程 LLM，零 API Key，完全本地化运行
- 🖥️ **交互式 CLI**：支持 `/list`、`/show`、`/run`、`/ref`、`/reload` 等命令
- 🌐 **HTTP API 服务**：提供 RESTful API，便于集成到其他系统
- 📋 **工作流引擎**：支持 YAML 定义的自动化工作流
- 📦 **自动解压**：支持 `.zip` 技能包自动解压和增量更新
- ⚙️ **YAML 配置**：灵活的技能源和工作流配置
- 🔄 **多模式切换**：对话模式、工作流模式、API 模式

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
├── application/               # 部署入口
│   ├── cli/main.py            # 生产环境 CLI
│   ├── api/api_server.py      # 生产环境 HTTP API 服务
│   └── web/index.html         # Web 前端页面
├── src/                       # 核心源码
│   ├── agent/
│   │   ├── agent.py           # 智能体核心（对话管理、命令处理）
│   │   └── executor.py        # 脚本执行与资源读取
│   ├── skill_scripts/
│   │   ├── models.py          # Skill 数据模型
│   │   ├── loader.py          # 技能发现与 SKILL.md 解析
│   │   └── matcher.py         # TF-IDF 意图匹配器
│   ├── workflow_scripts/
│   │   └── workflow.py        # 工作流加载与执行引擎
│   ├── config.py              # 配置管理模块
│   └── ui/
│       └── cli.py             # 命令行界面
└── data/                      # 数据目录
    ├── Opus.json              # API Key 配置文件
    ├── skills/                # 技能包存放目录
    │   └── openclaw_skills/   # OpenClaw 技能（支持 zip 自动解压）
    └── workflows/             # 工作流定义目录
        └── demo/workflow.yaml # 示例工作流
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动方式

#### 开发阶段（使用万能接口）

```bash
# 交互式模式（对话模式）
python main.py

# 快速测试意图匹配
python main.py -q "帮我构建一个 web 应用"

# 列出所有技能
python main.py --list

# 运行指定技能
python main.py --run search

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
# 一次性查询
python application/cli/main.py -q "构建 web 应用"

# 列出技能（按来源过滤）
python application/cli/main.py --list openclaw

# 查看技能详情
python application/cli/main.py --show web-dev

# 运行技能脚本（带参数）
python application/cli/main.py --run search --args "python async"

# 读取参考文档
python application/cli/main.py --ref skill-name --file README.md

# 执行工作流
python application/cli/main.py --workflow demo
python application/cli/main.py --workflow demo --inputs '{"query":"测试"}'

# JSON 输出格式
python application/cli/main.py --list --json
```

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
  -d '{"skill": "search", "args": "test"}'

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

编辑 `data/Opus.json`：

```json
{
  "api_keys": {
    "skills": {
      "tavily": {
        "name": "Tavily Search API",
        "api_key": "your-api-key",
        "enabled": true
      }
    },
    "llm": {
      "openai": {
        "name": "OpenAI API",
        "api_key": "your-api-key",
        "enabled": true
      }
    }
  }
}
```

## 📦 技能格式

智能体自动递归扫描每个目录，查找包含 `SKILL.md`（大小写不敏感）的文件夹。

### SKILL.md 格式

```yaml
---
name: my-custom-skill
description: Describe what this skill does (用于意图匹配的主要依据)
metadata:
  author: your-name
  version: 1.0.0
---

# 技能说明

这里写 Markdown 正文，包含使用说明、API、示例等。

## 目录结构

scripts/     # 可执行脚本（Python/PowerShell/Bash）
references/  # 参考文档
assets/      # 资源文件
agents/      # 子智能体定义
```

### 技能包格式

支持直接放置 `.zip` 技能包到技能目录，智能体会自动解压：

```
data/skills/openclaw_skills/
├── search-2-0.1.0.zip          # 技能包（会自动解压）
└── __unpacked__/
    └── search-2-0.1.0/         # 解压后的技能目录
        ├── SKILL.md
        └── scripts/
            └── search.sh
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

## 🧩 作为库使用

```python
from src.agent.agent import Agent

# 初始化智能体
agent = Agent("config.yaml")
print(f"已加载 {len(agent.list_skills())} 个技能")

# 意图匹配
resp = agent.ask("帮我创建一个 Python 脚本")
print(resp.reply)

# 获取匹配到的技能
for skill, score in resp.matched_skills:
    print(f"  [{skill.source}] {skill.name} ({score:.2f})")

# 运行技能脚本
result = agent.ask("/run search")
print(result.reply)

# 执行工作流
wf_result = agent.run_workflow("demo", inputs={"query": "测试"})
print(f"工作流 {wf_result.name}: {'成功' if wf_result.ok else '失败'}")
```

## 📝 输出示例

```
已加载 317 个技能。输入 /help 查看帮助，输入 /bye 退出。

你> build a web project
Agent>
我为你找到这些相关技能：

1. [hermes] web-artisan  (相关度 1.00)
   Create distinctive, production-grade web interfaces...
   路径: /home/user/.trae-cn/builtin/trae/penelope/skills/web-artisan
   可执行: generate.sh

2. [hermes] web-dev  (相关度 0.85)
   Create production-grade web interfaces...
   路径: /home/user/.trae-cn/builtin/trae/penelope/skills/web-dev

建议的下一步：
  - 输入 /show web-artisan   查看完整技能说明
  - 输入 /run web-artisan    执行该技能的脚本
```

## 🔒 安全说明

- `/run` 会直接执行技能目录下 `scripts/` 中的脚本，请**只对你信任的技能目录使用**
- 默认智能体不会自动执行任何脚本（需要显式使用 `/run`）
- 脚本执行超时为 120 秒
- API 服务默认监听 localhost，生产环境请配置防火墙

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

**Opus - OPC 公司专属智能体框架**
