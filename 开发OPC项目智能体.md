# OPC 项目智能体开发笔记

> Workspace: `g:\agent\Opus`

---

## 项目架构

```
Opus/
├── main.py                           # CLI 万能入口（--list / --workflow / -e / -q / --api / --cli）
├── config.yaml                       # 技能/工作流根目录配置
├── application/
│   ├── api/api_server.py             # 部署用 API 服务
│   └── cli/main.py                   # 部署用 CLI
├── src/
│   ├── agent/
│   │   ├── agent.py                  # Agent 类（llm_chat / find_skill / workflow）
│   │   └── executor.py               # 技能脚本执行器（核心）
│   ├── skill/
│   │   ├── skill.py                  # SkillManager + 匹配器 + 注册器
│   │   └── models.py                 # 技能数据模型
│   ├── workflow/
│   │   └── workflow.py               # 工作流引擎（YAML 解析 / 变量渲染 / chat / run action）
│   └── llm/
│       ├── manager.py                # ModelManager：统一入口
│       ├── adapters/openai.py        # DeepSeek / OpenAI 兼容适配器
│       └── ...                       # 其他 LLM 适配器
└── data/
    ├── Opus.json                     # ★ 集中式 API key 管理
    ├── skills/openclaw_skills/__unpacked__/
    │   ├── bocha-web-search-1.0.2/scripts/bocha-web-search.py
    │   └── deepseek-1.0.0/scripts/deepseek.py
    └── workflows/
        └── search-toutiao/workflow.yaml    # ★ 3 步工作流
```

---

## 核心设计点

### 1. API key 统一走 `data/Opus.json`

- `src/llm/manager.py` 读 `api_keys.llm.deepseek.api_key`，LLM 调用不需要额外设置环境变量。
- `src/agent/executor.py` 的 `_load_opus_keys` / `_merged_env` 会把 API keys 注入为环境变量（`BOCHA_API_KEY`、`DEEPSEEK_API_KEY`、`TAVILY_API_KEY` 等），供子进程里的技能脚本直接读取。
- **无需手动设置环境变量**。

### 2. `src/agent/executor.py` 的脚本执行策略

- **`.py` 脚本永远优先**（`sys.executable` 子进程跑，跨平台最稳）。
- **`.sh` 脚本**：优先 Python 原生解析 `curl` 请求 → fallback 到 bash → 再 fallback 到 PowerShell。
- **`subprocess.run` 一律传 `encoding='utf-8', errors='replace'`**，避免 Windows 默认 GBK 编码把中文 stdout 吃掉导致"返回空字符串"。
- **`cwd=skill_dir`**：脚本以自身目录做工作目录。

### 3. 工作流引擎里 DeepSeek"直接调用"，不需要包成 skill

工作流支持两种 action：

| action | 路径 | 用途 |
|---|---|---|
| `run` | `Agent.find_skill → executor.run_skill_script` | 跑技能脚本（bocha-web-search、搜索等需要外部 IO 的） |
| `chat` | `Agent.llm_chat → ModelManager → DeepSeek API` | **纯 LLM 推理，不经过技能层**（选新闻、写文章、改写、润色） |

所以 `search-toutiao` 工作流里 step2/step3 是纯 LLM，只有 step1 走技能脚本（bocha 搜互联网）。

### 4. 工作流 `{{...}}` 变量渲染

- `{{inputs.X}}` → 从 `inputs` dict 取。
- `{{steps.step_id.output.stdout}}` / `{{steps.step_id.output.json}}` → 取上一步的 stdout 或解析后的 JSON 字段。
- `wf.inputs[*].default` 声明默认值，调用方缺传时自动填入。
- step 之间按 YAML 书写顺序拓扑排序（`_toposort`），确保 `step2` 里写的 `{{steps.step1...}}` 一定能取到值。

---

## search-toutiao 工作流（核心流程）

```yaml
inputs:
  query:         "今日头条 最新科技新闻"
  count:         10
  llm_provider:  "deepseek"
  llm_model:     "deepseek-chat"

steps:
  - id: step1_fetch_news
    action: run
    skill:  bocha-web-search
    args:   ['{"query":"{{inputs.query}}","count":{{inputs.count}}}']

  - id: step2_pick_best
    action: chat
    provider: "{{inputs.llm_provider}}"
    model:    "{{inputs.llm_model}}"
    system:   "你是一位资深新媒体编辑。以下新闻中选出最适合做图文推广的一条..."
    user:     "以下是搜索返回的新闻列表：\n{{steps.step1_fetch_news.output.stdout}}"
    json_mode: true

  - id: step3_write_article
    action: chat
    provider: "{{inputs.llm_provider}}"
    model:    "{{inputs.llm_model}}"
    system:   "你是一位微信公众号作者。请基于下列新闻素材按规则重写成图文推广文章..."
    user:     "{{steps.step2_pick_best.output.content}}"
    json_mode: true
```

**调用链：**

```
main.py --workflow search-toutiao --wf-query "新能源汽车 最新趋势"
  └─> src/workflow/workflow.py  WorkflowExecutor.run()
        ├─ step1 run → bocha-web-search.py（注入 BOCHA_API_KEY）
        ├─ step2 chat → DeepSeek Chat Completions（直接 HTTP）
        └─ step3 chat → DeepSeek Chat Completions（直接 HTTP）
```

---

## 常用验证命令

```powershell
# 列出已加载的技能
python main.py --list

# 列出已发现的工作流
python main.py --workflows

# 跑 search-toutiao 工作流（传自定义 query）
python main.py --workflow search-toutiao --wf-query "AI 大模型 最新进展"

# 直接跑某个技能脚本（传 JSON 参数）
python main.py -e search -a '{"query":"最新AI新闻"}'

# 意图匹配（tf-idf 相似度）
python main.py -q "帮我搜索 web 应用"
```

---

## 每日话题管理（不改工作流的去重方案）

核心思想：**去重逻辑在工作流"外面"写 Python 脚本，工作流本身只负责单次"给一个 query → 产出一篇文章"。**

### 建议的外层脚本做的事

1. **生成/维护话题池**：让 DeepSeek 先给一批近期热门话题（JSON 数组），或你手动提供。
2. **每日 `outputs/search-toutiao/YYYY-MM-DD/`**：每跑一次保存一个 `run-NN.json`（含 query / bocha 原始 / step2 选中的新闻 / step3 最终文章 / 时间戳）和一个 `run-NN.md`（排版好直接发）。
3. **跨天 `outputs/search-toutiao/history.json`**：记录所有已产出的标题 + query + 新闻片段签名，下次跑时读出来传给"选新闻"步骤做排除。
4. **两层去重**：
   - **query 层**：每次抽一个当天尚未使用过的话题 → bocha 搜索素材自然不同。
   - **新闻片段层**：调用 `step2_pick_best` 时，在 messages 里塞一段"以下标题已选过，不要再选：..."，利用 DeepSeek 的推理能力做排除。

### 保存结构示例

```
outputs/
  search-toutiao/
    history.json              # 全局：已产出标题 + query + 签名
    2026-06-07/
      run-01.json             # 单次全量原始数据
      run-01.md               # 渲染成文章（可直接复制发文）
      ...
      run-10.json
      run-10.md
```

---

## 涉及的关键文件速查

| 文件 | 作用 |
|---|---|
| `main.py` | CLI 入口，解析 `--workflow / --wf-query / --inputs`，调用工作流引擎并打印结果 |
| `config.yaml` | 配置工作流根目录 `workflow_roots`、技能根目录 `skill_roots` |
| `data/Opus.json` | ★ 集中式 API key 管理：`api_keys.llm.deepseek`、`api_keys.skills.bocha` 等 |
| `data/workflows/search-toutiao/workflow.yaml` | 工作流定义（3 步 + 4 个 inputs + 默认值） |
| `src/workflow/workflow.py` | 工作流引擎：YAML 解析、`{{...}}` 渲染、`chat` / `run` action |
| `src/agent/agent.py` | `Agent.llm_chat(messages, provider=..., model=...)` — 原生 LLM 统一入口 |
| `src/agent/executor.py` | 技能脚本执行器：注入 API key、UTF-8 读取 stdout、三层脚本回退 |
| `src/llm/manager.py` | `ModelManager.chat(provider, model, messages, ...)` |
| `src/llm/adapters/openai.py` | DeepSeek / OpenAI 兼容协议适配器（支持 `openai` 包与标准库回退） |
| `data/skills/openclaw_skills/__unpacked__/bocha-web-search-1.0.2/scripts/bocha-web-search.py` | step1 实际执行的脚本：JSON 参数 → 调 bocha web-search → stdout JSON |
