"""ToutiaoAgent —— 今日头条图文推广 Agent。

此文件只保留 Agent 身份/默认值，所有业务逻辑（话题生成、文章生产、批量处理）
都由通用的 TaskExecutor（src/task/task.py）处理。

调用方式：
  python main.py --agent toutiao --task daily_batch --n 10
  python main.py --agent toutiao --task batch_articles --topics "AI 大模型,人形机器人"
  python main.py --agent toutiao --task single_article --query "AI 大模型"
  python main.py --agent toutiao --task suggest_topics --n 5

新增任务时：
  1. 在 data/agents/toutiao_agent/tasks/ 下新建 xxx.yaml（声明 name、handler、inputs）
  2. 在 src/task/task.py 的 TaskExecutor 中新增 _handler_xxx() 方法
  3. 即可用 python main.py --agent toutiao --task xxx 调用
"""
import logging
from typing import Any, Dict, List, Optional

from src.agent.base import BaseAgent
from src.task import TaskExecutor

logger = logging.getLogger(__name__)


class ToutiaoAgent(BaseAgent):
    """头条图文推广 Agent。

    所有实际业务逻辑都委托给 TaskExecutor（见 src/task/task.py），
    本类只负责：
      - 声明 name/description/supported_tasks
      - 提供默认 identity/config（即"身份人设"和"默认参数"）
      - 在 can_handle() 里判断指令是否匹配"头条/软文/公众号"等关键词
      - run() 根据 task_name 路由到 self.task.run(task_name, ...)
    """

    name = "toutiao_agent"
    description = "每日批量生成图文推广文章（今日头条风格）—— 自动搜新闻 + 选头条 + 写文章"
    supported_tasks = ["daily_batch", "single_article", "suggest_topics", "batch_articles"]

    # ── 主入口 ──────────────────────────────────────
    def run(self, task: str = "daily_batch", n: int = 10,
            topic_pool: Optional[List[str]] = None, **kwargs) -> Dict[str, Any]:
        """主入口。所有任务都委托给 TaskExecutor。"""
        logger.info(f"[{self.name}] run(task={task}, n={n}, kwargs={list(kwargs.keys())})")

        # 懒加载 TaskExecutor（每个 Agent 实例只实例化一次）
        if not getattr(self, "task", None):
            self.task = TaskExecutor(self, self.data_dir)

        # 把 topic_pool（List[str]）转成逗号字符串，方便 TaskExecutor 统一处理
        topics_flat = (
            ",".join([str(t) for t in (topic_pool or [])]) if topic_pool else ""
        )

        # 合并 kwargs（可能含 query/workflow_name/topics 等）+ 显式参数
        inputs = dict(kwargs)
        inputs.setdefault("n", n)
        if topics_flat and "topics" not in inputs:
            inputs["topics"] = topics_flat

        return self.task.run(task, **inputs)

    # ── can_handle（给 Orchestrator 做路由用）────────
    def can_handle(self, instruction: str) -> float:
        text = (instruction or "").lower()
        score = 0.0
        for kw in ("头条", "图文推广", "写文章", "软文", "公众号", "每日文章", "批量生成"):
            if kw in text:
                score += 0.25
        if "toutiao" in text:
            score += 0.3
        return min(score, 1.0)

    # ── 默认身份（当 data/agents/toutiao_agent/identity.json 不存在时使用）────
    def _default_identity(self) -> Dict[str, Any]:
        return {
            "display_name": "头条推广 Agent",
            "role": "资深新媒体主编",
            "description": self.description,
            "system_prompt": "每天为用户生成高质量、有信息量、可直接用于公众号发布的图文推广文章。",
        }

    # ── 默认配置（当 data/agents/toutiao_agent/config.json 不存在时使用）────
    def _default_config(self) -> Dict[str, Any]:
        return {
            "llm_provider": "deepseek",
            "llm_model": "deepseek-chat",
            "temperature": 0.8,
            "title_dedup_threshold": 0.75,
            "query_cooldown_days": 7,
            "min_content_length": 100,
        }
