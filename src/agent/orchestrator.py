"""
OrchestratorAgent —— 总调度器。

给它一句指令（如"今天给我生成10篇头条文章"），它：
  1. 让各个子 Agent 自评 can_handle(instruction)
  2. 选匹配度最高的子 Agent 执行
  3. 汇总结果返回

它本身也是一个 BaseAgent，有自己的 memory/knowledge/storage（src/agent/main/）。
"""
import logging
from typing import Any, Dict, List, Optional

from .agent import Agent
from .base import BaseAgent
from .registry import registry

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """总调度 Agent。"""
    
    name = "main"
    description = "多智能体总调度器 —— 理解指令并路由给最合适的子 Agent"
    supported_tasks = ["route", "list_agents"]
    
    def run(self, instruction: str, **kwargs) -> Dict[str, Any]:
        """解析一句指令并派发给最合适的子 Agent。"""
        logger.info(f"[{self.name}] 收到指令: {instruction}")
        
        # 先看是不是特殊命令
        if instruction.strip().lower() in ("list", "ls", "help", "有哪些agent", "列出agent"):
            return {
                "task": "list_agents",
                "output": registry.describe_all(self.base_agent),
            }
        
        # 先让子 Agent 自评
        best = registry.find_best(instruction, self.base_agent)
        if best is None:
            return {
                "task": "route",
                "ok": False,
                "instruction": instruction,
                "reason": "没有合适的子 Agent 能处理",
                "available": registry.names(),
            }
        
        logger.info(f"[{self.name}] 路由到: {best.name}")
        # 解析一下想要的篇数（给 ToutiaoAgent 用）
        n = self._parse_n(instruction, default=10)
        
        # 执行
        try:
            if best.name == "toutiao":
                result = best.run(task="daily_batch", n=n)
            else:
                result = best.run()
        except Exception as e:
            logger.exception(f"[{self.name}] 子 Agent 执行失败: {e}")
            return {"task": "route", "ok": False, "error": str(e)}
        
        # 记录到自己的长期记忆
        self.append_history({
            "type": "route",
            "instruction": instruction,
            "dispatched_to": best.name,
            "result_ok": result.get("ok", False) if isinstance(result, dict) else True,
        })
        
        return {
            "task": "route",
            "ok": True,
            "instruction": instruction,
            "dispatched_to": best.name,
            "result": result,
        }
    
    def can_handle(self, instruction: str) -> float:
        # Orchestrator 不直接处理任务，只路由
        return 0.0
    
    # ─── 工具 ───────────────────────────────────
    @staticmethod
    def _parse_n(text: str, default: int = 10) -> int:
        """从文本里找"N 篇"、"N 条"之类的数字。"""
        import re
        m = re.search(r"(\d+)\s*(?:篇|条|个|篇文章|topics)", text)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        return default
    
    def _default_identity(self) -> Dict[str, Any]:
        return {
            "display_name": "智能体总调度",
            "role": "总调度 Agent",
            "description": self.description,
            "system_prompt": "理解用户指令，找到最合适的子 Agent 去执行，并汇报结果。",
        }
    
    def _default_config(self) -> Dict[str, Any]:
        return {
            "llm_provider": "deepseek",
            "llm_model": "deepseek-chat",
            "temperature": 0.5,
        }
