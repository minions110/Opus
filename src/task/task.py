"""TaskExecutor —— 扫描 tasks/*.yaml 并按任务名分派执行。

每个 Agent 实例化一个 TaskExecutor（传入 self 和 data_dir），让它负责：
  1. 扫描 data_dir/tasks/*.yaml 加载任务定义
  2. 根据 yaml 的 handler 字段分派到对应 _handler_xxx 方法
  3. 内置通用工具：话题生成/去重、workflow 结果解析、文章保存 等

任何 Agent（ToutiaoAgent、XhsAgent、WechatAgent...）只要继承 BaseAgent 并把
TaskExecutor(self, self.data_dir) 挂在 self.task 上，就可以用同一个引擎跑
 suggest_topics / single_article / daily_batch / batch_articles 等任务。
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskExecutor:
    """通用任务执行器。

    base_agent 需要提供（即 BaseAgent 已实现的接口）：
      - workflow(name, inputs)       -> dict/object   # 跑一个工作流
      - llm(messages)                -> response      # 调 LLM
      - knowledge.topic_pool         -> List[str]
      - knowledge.contains_sensitive(text) -> str|None
      - memory.recent(n)             -> List[dict]
      - is_query_recently_used(query, days) -> bool
      - is_title_duplicate(title, threshold) -> bool
      - append_history(record)       -> None
      - storage.save_pair(data, md)  -> dict(json_path, md_path)
      - storage.save_daily_report(list) -> str(path)
      - config.get(key, default)     -> value
      - identity.get(key, default)   -> value
      - name                         -> str
      - data_dir                     -> Path
    """

    def __init__(self, base_agent, data_dir: Path):
        self.base = base_agent
        self.data_dir = Path(data_dir)
        self.tasks_dir = self.data_dir / "tasks"
        self._tasks = self._discover()

    # ── 任务发现（扫描 tasks/*.yaml）───────────────────
    def _discover(self) -> Dict[str, Dict[str, Any]]:
        """扫描 yaml 并注册任务。支持两种格式：

        格式 A —— 一个 yaml = 一个任务（兼容旧格式）：
            name: batch_articles
            handler: batch_articles
            inputs: [...]

        格式 B —— 一个 yaml = 多个任务（推荐，用 tasks: 列表）：
            tasks:
              - name: batch_articles
                handler: batch_articles
                inputs: [...]
              - name: daily_batch
                handler: daily_batch
                ...
        """
        tasks: Dict[str, Dict[str, Any]] = {}
        if not self.tasks_dir.exists():
            logger.debug(f"[TaskExecutor] {self.tasks_dir} 不存在，跳过")
            return tasks
        import yaml
        for f in sorted(self.tasks_dir.glob("*.yaml")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}

                # 格式 B：根级有 tasks: 列表 → 遍历注册
                if isinstance(data, dict) and isinstance(data.get("tasks"), list):
                    for item in data["tasks"]:
                        if not isinstance(item, dict) or "name" not in item:
                            logger.warning(
                                f"[TaskExecutor] {f.name} 里一个任务缺少 name，跳过"
                            )
                            continue
                        tasks[item["name"]] = item
                        logger.info(
                            f"[TaskExecutor] 发现任务: {item['name']} ({f.name})"
                        )
                    continue

                # 格式 A：根级就是一个任务（有 name 字段）
                if isinstance(data, dict) and "name" in data:
                    tasks[data["name"]] = data
                    logger.info(f"[TaskExecutor] 发现任务: {data['name']} ({f.name})")
                    continue

                logger.warning(f"[TaskExecutor] 忽略无效任务文件 {f.name}")
            except Exception as e:
                logger.warning(f"[TaskExecutor] 解析 {f.name} 失败: {e}")
        return tasks

    def list(self) -> List[str]:
        return list(self._tasks.keys())

    def describe(self, name: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(name)

    # ── 主入口 ───────────────────────────────────────
    def run(self, task_name: str, **inputs) -> Dict[str, Any]:
        task = self._tasks.get(task_name)
        if not task:
            msg = (
                f"未找到任务 '{task_name}'。"
                f"可用任务: {list(self._tasks.keys()) or '(空)'}"
            )
            logger.error(msg)
            return {"ok": False, "task": task_name, "error": msg}

        merged = self._merge_defaults(task, inputs)
        handler = task.get("handler", task_name)

        logger.info(
            f"[TaskExecutor] [{self.base.name}] "
            f"运行 task={task_name}, handler={handler}, inputs={merged}"
        )

        method = getattr(self, f"_handler_{handler}", None)
        if method is None:
            return {
                "ok": False,
                "task": task_name,
                "error": f"未实现 handler _handler_{handler}",
            }
        try:
            result = method(task, merged)
            result.setdefault("ok", True)
            result.setdefault("task", task_name)
            return result
        except Exception as e:
            logger.exception(f"[TaskExecutor] 任务 {task_name} 执行异常: {e}")
            return {"ok": False, "task": task_name, "error": str(e)}

    # ── 参数合并 ───────────────────────────────────────
    @staticmethod
    def _merge_defaults(task: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        """把 yaml 的 inputs[*].default 合并到实际参数里。

        规则：如果实际传入的值是 None 或空字符串，视为"用户没传"，用 yaml.default；
        否则保留用户实际传入的值。
        """
        result = dict(inputs)
        for item in task.get("inputs", []) or []:
            if not isinstance(item, dict):
                continue
            key = item.get("name")
            if not key:
                continue
            existing = result.get(key, None)
            if existing is None or (isinstance(existing, str) and existing == ""):
                result[key] = item.get("default")
        return result

    # ══════════════════════════════════════════════════
    # 通用工具：话题处理
    # ══════════════════════════════════════════════════

    def _resolve_topics(self, task: Dict[str, Any], inputs: Dict[str, Any]) -> List[str]:
        """解析 --topics 字符串（逗号分隔）或从 knowledge.topic_pool 取。"""
        raw_topics = inputs.get("topics") or ""
        if raw_topics:
            topics = [t.strip() for t in str(raw_topics).split(",") if t.strip()]
            n = int(inputs.get("n") or len(topics) or 10)
            return topics[:n]
        pool = getattr(getattr(self.base, "knowledge", None), "topic_pool", None) or []
        n = int(inputs.get("n") or len(pool) or 10)
        return list(pool)[:n]

    def pick_topics(self, n: int, topic_pool: Optional[List[str]] = None) -> List[str]:
        """生成 n 个不重复话题（通用：LLM 生成 + 三层过滤 + 最多补 3 轮）。"""
        candidates: List[str] = []

        if topic_pool:
            candidates = list(topic_pool)
        else:
            kb_topics = getattr(getattr(self.base, "knowledge", None), "topic_pool", None) or []
            if kb_topics:
                candidates = list(kb_topics)
            extra = self.ask_llm_for_topics(max(n * 2, 10))
            candidates += extra

        filtered: List[str] = []
        seen = set()
        cooldown = self.base.config.get("query_cooldown_days", 7)
        title_thresh = self.base.config.get("title_dedup_threshold", 0.75)
        knowledge = getattr(self.base, "knowledge", None)

        for t in candidates:
            t = (t or "").strip().strip("'\"")
            if not t or len(t) < 2:
                continue
            if t in seen:
                continue
            if self.base.is_query_recently_used(t, days=cooldown):
                logger.debug(f"[{self.base.name}] 跳过(近期用过): {t}")
                continue
            if self.base.is_title_duplicate(t, threshold=title_thresh):
                logger.debug(f"[{self.base.name}] 跳过(标题相似): {t}")
                continue
            if knowledge and knowledge.contains_sensitive(t):
                logger.debug(f"[{self.base.name}] 跳过(含敏感词): {t}")
                continue
            seen.add(t)
            filtered.append(t)
            if len(filtered) >= n:
                break

        tries = 0
        while len(filtered) < n and tries < 3:
            extra = self.ask_llm_for_topics(n - len(filtered) + 5)
            added = 0
            for t in extra:
                t = (t or "").strip().strip("'\"")
                if t and t not in seen and len(t) >= 2:
                    if not self.base.is_query_recently_used(t, days=cooldown) and \
                       not self.base.is_title_duplicate(t, threshold=title_thresh) and \
                       not (knowledge and knowledge.contains_sensitive(t)):
                        seen.add(t)
                        filtered.append(t)
                        added += 1
                        if len(filtered) >= n:
                            break
            if added == 0:
                break
            tries += 1

        logger.info(f"[{self.base.name}] 选出 {len(filtered)} 个话题 / 候选 {len(candidates)} 个")
        return filtered[:n]

    def ask_llm_for_topics(self, n: int, exclude: Optional[List[str]] = None) -> List[str]:
        """调 LLM 生成话题。使用 base.identity 的 role 和 system_prompt 定制风格。"""
        memory = getattr(self.base, "memory", None)
        recent_titles: List[str] = []
        if memory:
            recent = memory.recent(20)
            recent_titles = [
                r.get("title") or r.get("query")
                for r in recent
                if r.get("title") or r.get("query")
            ]

        role = self.base.identity.get("role", "内容创作者")
        sys_prompt = self.base.identity.get("system_prompt", "") or self.base.description

        system_msg = (
            f"你是一位{role}。{sys_prompt}\n\n"
            f"请生成 {n} 个适合做内容创作的中文话题。要求：\n"
            f"1. 每个话题 4~20 字，是一个有搜索量的关键词或短句；\n"
            f"2. 互不重复，覆盖不同行业和角度；\n"
            f"3. 话题要有时效性，能在近期搜到新闻；\n"
            f"4. 不要与以下最近用过的主题重复：\n"
            + ("\n".join(f"   - {t}" for t in recent_titles[:15]) if recent_titles else "   (无历史)")
            + (("\n5. 不要生成以下话题: " + ", ".join(exclude) + "\n") if exclude else "\n")
            + "\n输出格式：严格的 JSON 数组，例如 [\"AI 大模型最新进展\", \"固态电池量产消息\"]。不要额外文字。"
        )

        response = self.base.llm([
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"给我 {n} 个话题。"},
        ])

        topics = self.parse_json_array(str(getattr(response, "content", response)))
        logger.debug(f"[{self.base.name}] LLM 给了 {len(topics)} 个话题: {topics[:5]}...")
        return topics

    @staticmethod
    def parse_json_array(text: str) -> List[str]:
        """容错解析 LLM 返回的 JSON 数组（支持代码块、无括号列表等）。"""
        if not text:
            return []
        t = text.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", t)
        if fence:
            t = fence.group(1).strip()
        start = t.find("[")
        end = t.rfind("]")
        if start >= 0 and end > start:
            t = t[start:end + 1]
        try:
            data = json.loads(t)
            if isinstance(data, list):
                return [str(x) for x in data if str(x).strip()]
        except Exception:
            pass
        items = [ln.strip().strip("'\",") for ln in t.replace(",", "\n").splitlines()]
        return [x for x in items if x and len(x) >= 2]

    # ══════════════════════════════════════════════════
    # 通用工具：workflow 结果解析
    # ══════════════════════════════════════════════════

    @staticmethod
    def _get_steps(wf_result: Any) -> list:
        steps = []
        if hasattr(wf_result, "steps"):
            steps = wf_result.steps or []
        elif isinstance(wf_result, dict):
            steps = wf_result.get("steps") or wf_result.get("results") or []
        return steps

    @staticmethod
    def _get_step_output(step: Any) -> Any:
        if hasattr(step, "output"):
            return step.output
        if isinstance(step, dict):
            return step.get("output")
        return None

    @staticmethod
    def _get_step_id(step: Any) -> str:
        if hasattr(step, "step_id"):
            return str(step.step_id)
        if isinstance(step, dict):
            return str(step.get("step_id") or step.get("id") or "")
        return ""

    def extract_title(self, wf_result) -> str:
        """从 workflow 结果里提取 title。优先 step3/article，兜底 step2/pick，再兜底任何 step。"""
        steps = self._get_steps(wf_result)
        # 优先级 1: step3 或 article 里的 json.title
        for step in steps:
            sid = self._get_step_id(step)
            out = self._get_step_output(step)
            if isinstance(out, dict) and isinstance(out.get("json"), dict):
                if out["json"].get("title") and ("step3" in sid or "article" in sid):
                    return str(out["json"]["title"])
        # 优先级 2: step2 或 pick 里的 json.title
        for step in steps:
            sid = self._get_step_id(step)
            out = self._get_step_output(step)
            if isinstance(out, dict) and isinstance(out.get("json"), dict):
                if out["json"].get("title") and ("step2" in sid or "pick" in sid):
                    return str(out["json"]["title"])
        # 兜底: 任何 step 里的 json.title
        for step in steps:
            out = self._get_step_output(step)
            if isinstance(out, dict) and isinstance(out.get("json"), dict):
                if out["json"].get("title"):
                    return str(out["json"]["title"])
        return ""

    def extract_content(self, wf_result) -> str:
        """从 workflow 结果里提取 content。"""
        steps = self._get_steps(wf_result)
        # 优先级 1: step3/article/write 里的 json.content
        for step in steps:
            sid = self._get_step_id(step)
            out = self._get_step_output(step)
            if isinstance(out, dict) and isinstance(out.get("json"), dict):
                content = out["json"].get("content")
                if isinstance(content, str) and content.strip() and \
                   ("step3" in sid or "article" in sid or "write" in sid):
                    return content.strip()
        # 优先级 2: 倒序找第一个有 json.content 的 step
        for step in reversed(steps):
            out = self._get_step_output(step)
            if isinstance(out, dict) and isinstance(out.get("json"), dict):
                content = out["json"].get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
        # 优先级 3: 正序找任何 step 里的 json.{content,article,text,body}
        for step in steps:
            out = self._get_step_output(step)
            if isinstance(out, dict) and isinstance(out.get("json"), dict):
                for key in ("content", "article", "text", "body"):
                    if isinstance(out["json"].get(key), str) and out["json"][key].strip():
                        return out["json"][key].strip()
        # 优先级 4: 最后一个 step 的任何字符串字段
        if steps:
            last = steps[-1]
            out = self._get_step_output(last)
            if isinstance(out, dict):
                for v in ("content", "article", "text", "stdout"):
                    if isinstance(out.get(v), str) and out[v].strip():
                        return out[v].strip()
            if isinstance(out, str):
                return out.strip()
        return ""

    def simplify_workflow_result(self, obj: Any) -> Any:
        """把 workflow 结果简化成可 JSON 序列化的结构。"""
        try:
            json.dumps(obj, ensure_ascii=False)
            return obj
        except Exception:
            pass
        if hasattr(obj, "steps"):
            return {
                "name": getattr(obj, "name", ""),
                "ok": getattr(obj, "ok", False),
                "steps": [
                    {
                        "step_id": self._get_step_id(s),
                        "action": getattr(s, "action", ""),
                        "ok": getattr(s, "ok", False),
                        "output_preview": str(self._get_step_output(s))[:300],
                    }
                    for s in (getattr(obj, "steps") or [])
                ],
            }
        return str(obj)[:1000]

    @staticmethod
    def render_markdown(data: dict) -> str:
        """把文章 dict 渲染成 Markdown。"""
        title = data.get("title") or data.get("query") or "未命名"
        content = data.get("content") or ""
        lines = [
            f"# {title}",
            "",
            f"> Query: {data.get('query')}",
            f"> Agent: {data.get('agent')} · {data.get('generated_at')}",
            "",
            content,
        ]
        return "\n".join(lines)

    # ══════════════════════════════════════════════════
    # 通用工具：单篇文章生产
    # ══════════════════════════════════════════════════

    def produce_one_article(
        self,
        workflow_name: str,
        query: str,
        index: int = 0,
        title_dedup_threshold: Optional[float] = None,
        min_content_length: int = 50,
    ) -> Optional[Dict[str, Any]]:
        """跑一次指定 workflow，把结果提取为 title+content，去重+敏感词检查后保存。

        返回 dict 含 ok/query/title/summary/path_json/path_md，失败返回含 reason 的 dict。
        """
        logger.info(
            f"[{self.base.name}] #{index} → run workflow '{workflow_name}' with query={query}"
        )

        # 先做 query 级别去重（完全相同的 query 近3天内跑过就跳过）
        cooldown_days = self.base.config.get("query_cooldown_days", 3)
        if self.base.is_query_recently_used(query, days=cooldown_days):
            logger.warning(f"[{self.base.name}] #{index} query 近{cooldown_days}天内已使用: {query}，跳过")
            return {"ok": False, "query": query, "reason": "query_recent"}

        wf_result = self.base.workflow(workflow_name, {"query": query, "count": 10})

        title = self.extract_title(wf_result) or ""
        content = self.extract_content(wf_result) or ""

        # 如果 title 与 query 完全相同，可能是 LLM 没生成好标题 → 在 query 基础上加前缀作为标题
        if not title or title.strip() == query:
            title = f"{query}（{datetime.now().strftime('%m月%d日')}）"

        if not content or len(content) < min_content_length:
            logger.warning(f"[{self.base.name}] #{index} 内容过短或为空，跳过")
            return {"ok": False, "query": query, "reason": "empty_content"}

        thresh = title_dedup_threshold if title_dedup_threshold is not None \
            else self.base.config.get("title_dedup_threshold", 0.75)
        if self.base.is_title_duplicate(title, threshold=thresh):
            logger.warning(f"[{self.base.name}] #{index} 标题疑似重复: {title}，跳过")
            return {"ok": False, "query": query, "title": title, "reason": "duplicate_title"}

        knowledge = getattr(self.base, "knowledge", None)
        if knowledge:
            sensitive = knowledge.contains_sensitive(content)
            if sensitive:
                logger.warning(f"[{self.base.name}] #{index} 正文含敏感词: {sensitive}，跳过")
                return {"ok": False, "query": query, "title": title, "reason": "sensitive_content"}

        data = {
            "query": query,
            "title": title,
            "content": content,
            "workflow_result": self.simplify_workflow_result(wf_result),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "agent": self.base.name,
        }
        md = self.render_markdown(data)
        paths = self.base.storage.save_pair(data, md)

        try:
            self.base.append_history({
                "type": "article",
                "query": query,
                "title": title,
                "summary": content[:200].replace("\n", " "),
                "path_json": str(paths["json"]),
                "path_md": str(paths["md"]),
            })
        except Exception as e:
            logger.debug(f"[{self.base.name}] 写记忆失败 (非致命): {e}")

        return {
            "ok": True,
            "query": query,
            "title": title,
            "summary": content[:80].replace("\n", " "),
            "tags": [],
            "path_json": str(paths["json"]),
            "path_md": str(paths["md"]),
        }

    # ══════════════════════════════════════════════════
    # 任务 Handler —— 每个任务一个方法
    # ══════════════════════════════════════════════════

    def _handler_suggest_topics(self, task: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        """只生成话题列表，不跑 workflow。"""
        n = int(inputs.get("n", 10) or 10)
        raw_topics = inputs.get("topics") or ""
        if raw_topics:
            topics = [t.strip() for t in str(raw_topics).split(",") if t.strip()]
        else:
            topics = self.pick_topics(n)
        return {
            "task": task.get("name"),
            "n": len(topics),
            "topics": topics,
        }

    def _handler_single_article(self, task: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        """给定 query，跑一篇文章。

        注意：用户显式给了 query，说明他就是要这个主题的内容，所以放宽标题去重阈值
        （默认 0.75 会把"相似主题"的文章都拦掉，不符合用户意图）。
        """
        workflow_name = task.get("workflow_name") or inputs.get("workflow_name") or "search-toutiao"
        query = inputs.get("query") or ""
        if not query:
            return {
                "ok": False,
                "task": task.get("name"),
                "error": "缺少 query 参数（--query 'xxx' 或在 yaml 设 default）",
            }
        result = self.produce_one_article(
            workflow_name, query, index=1,
            title_dedup_threshold=0.95,  # 放宽：几乎完全相同才算重复
        )
        return {
            "task": task.get("name"),
            "requested": 1,
            "success": 1 if (result and result.get("ok")) else 0,
            "failure": 0 if (result and result.get("ok")) else 1,
            "article": result,
        }

    def _handler_daily_batch(self, task: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        """LLM 生成话题 + 循环跑 workflow 批量生成文章。"""
        workflow_name = task.get("workflow_name") or inputs.get("workflow_name") or "search-toutiao"

        raw_topics = inputs.get("topics") or ""
        n_raw = int(inputs.get("n", 10) or 10)

        if raw_topics:
            topics = [t.strip() for t in str(raw_topics).split(",") if t.strip()]
            # 用户明确给了 topics，用实际话题数量
            n = min(n_raw, len(topics))
            topics = topics[:n]
        else:
            topics = self.pick_topics(n_raw)
            n = len(topics)

        if not topics:
            return {
                "ok": False,
                "task": task.get("name"),
                "requested": 0,
                "success": 0,
                "failure": 0,
                "skipped": 0,
                "articles": [],
                "error": "没有可用话题（LLM 生成失败且 topic_pool 为空）",
            }

        summaries: List[Dict[str, Any]] = []
        successes = 0
        failures = 0
        skipped = 0
        logger.info(f"[{self.base.name}] [daily_batch] 话题列表: {topics}")

        for i, query in enumerate(topics, 1):
            logger.info(f"[{self.base.name}] [daily_batch] 第 {i}/{len(topics)} 篇: query={query}")
            try:
                result = self.produce_one_article(workflow_name, query, index=i)
                if result and result.get("ok"):
                    summaries.append(result)
                    successes += 1
                else:
                    # 区分"被跳过"与"真正失败"
                    if result and result.get("reason"):
                        logger.info(f"  跳过: {result['reason']}")
                        skipped += 1
                    else:
                        failures += 1
            except Exception as e:
                logger.warning(f"[{self.base.name}] [daily_batch] 第 {i} 篇失败: {e}")
                failures += 1

        if summaries:
            try:
                report_path = self.base.storage.save_daily_report(
                    [
                        {
                            "title": s["title"],
                            "summary": s["summary"],
                            "path_json": s["path_json"],
                            "path_md": s["path_md"],
                        }
                        for s in summaries
                    ]
                )
                logger.info(f"[{self.base.name}] [daily_batch] 报告: {report_path}")
            except Exception as e:
                logger.debug(f"[{self.base.name}] [daily_batch] 报告保存失败 (非致命): {e}")

        return {
            "task": task.get("name"),
            "requested": n,
            "success": successes,
            "failure": failures,
            "skipped": skipped,
            "articles": summaries,
        }

    def _handler_batch_articles(self, task: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        """从 --topics 或 knowledge.topic_pool 取话题，批量跑 workflow（不做 LLM 话题生成）。"""
        workflow_name = task.get("workflow_name") or inputs.get("workflow_name") or "search-toutiao"
        topics = self._resolve_topics(task, inputs)

        if not topics:
            return {
                "ok": False,
                "task": task.get("name"),
                "requested": 0,
                "success": 0,
                "failure": 0,
                "articles": [],
                "error": "没有可用话题（既没给 --topics，knowledge/topic_pool.txt 也为空）",
            }

        # 当用户明确提供 --topics 时，用实际话题数量作为 requested，而不是 n 默认值
        n = int(inputs.get("n", len(topics)) or len(topics))
        n = min(n, len(topics))

        summaries: List[Dict[str, Any]] = []
        successes = 0
        failures = 0
        skipped = 0
        logger.info(f"[{self.base.name}] [batch_articles] 话题列表: {topics}")

        for i, query in enumerate(topics, 1):
            logger.info(f"[{self.base.name}] [batch_articles] 第 {i}/{len(topics)} 篇: query={query}")
            try:
                result = self.produce_one_article(workflow_name, query, index=i)
                if result and result.get("ok"):
                    summaries.append(result)
                    successes += 1
                else:
                    # 区分"被跳过"（如重复标题）与"真正失败"
                    if result and result.get("reason"):
                        logger.info(f"  跳过: {result['reason']}")
                        skipped += 1
                    else:
                        failures += 1
            except Exception as e:
                logger.warning(f"[{self.base.name}] [batch_articles] 第 {i} 篇失败: {e}")
                failures += 1

        if summaries:
            try:
                report_path = self.base.storage.save_daily_report(
                    [
                        {
                            "title": s["title"],
                            "summary": s["summary"],
                            "path_json": s["path_json"],
                            "path_md": s["path_md"],
                        }
                        for s in summaries
                    ]
                )
                logger.info(f"[{self.base.name}] [batch_articles] 报告: {report_path}")
            except Exception as e:
                logger.debug(f"[{self.base.name}] [batch_articles] 报告保存失败 (非致命): {e}")

        return {
            "task": task.get("name"),
            "requested": n,
            "success": successes,
            "failure": failures,
            "skipped": skipped,
            "articles": summaries,
        }
