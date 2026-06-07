"""
AgentRegistry —— 自动扫描并注册所有子 Agent。

支持两种注册方式：
  1) 模块路径（Python 包内的 Agent）：("src.agent.orchestrator", "OrchestratorAgent")
  2) 文件路径（data/agents 下的 Agent）：(Path("data/agents/xxx/agent.py"), "ClassName")

使用：
    from src.agent.registry import registry
    agent = registry.get("toutiao", base_agent)       ← 懒加载
    all_names = registry.names()
    matched = registry.find_best("给我生成10篇头条", base_agent)
"""
import importlib.util
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import Agent
    from .base import BaseAgent

logger = logging.getLogger(__name__)

# 子 Agent 数据根目录（与 base.py 保持一致）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_AGENTS_ROOT = _PROJECT_ROOT / "data" / "agents"

# 已知的子 Agent：name → (路径, 类名)
#   路径可以是 str（模块路径，如 "src.agent.orchestrator"）
#   或 Path / str（文件路径，如 "data/agents/toutiao_agent/agent.py"）
_REGISTRY = {
    "toutiao": ("src.task.toutiao_agent", "ToutiaoAgent"),
    "main": ("src.agent.orchestrator", "OrchestratorAgent"),
}


class AgentRegistry:
    """懒加载的 Agent 注册表。"""
    
    def __init__(self):
        self._classes: Dict[str, type] = {}
        self._instances: Dict[str, "BaseAgent"] = {}
    
    def names(self) -> List[str]:
        return sorted(_REGISTRY.keys())
    
    def register(self, name: str, module_path: str, class_name: str) -> None:
        """动态注册一个新 Agent 类型（无需修改本文件也能加）。"""
        _REGISTRY[name] = (module_path, class_name)
    
    def _load_class(self, name: str) -> type:
        if name not in _REGISTRY:
            raise KeyError(f"未知的 Agent: {name}，可用: {self.names()}")
        if name in self._classes:
            return self._classes[name]
        import importlib
        module_path, class_name = _REGISTRY[name]

        # 路径分两种：模块路径（str，包含点号）或文件路径（Path / 含斜杠的 str，指向 .py 文件）
        is_file_path = isinstance(module_path, Path) or (
            isinstance(module_path, str)
            and ("/" in module_path or "\\" in module_path or module_path.endswith(".py"))
        )

        try:
            if is_file_path:
                # 从文件路径加载
                file_path = Path(module_path)
                if not file_path.is_absolute():
                    file_path = _PROJECT_ROOT / file_path
                spec = importlib.util.spec_from_file_location(
                    f"agent_{name}", str(file_path)
                )
                if spec is None or spec.loader is None:
                    raise RuntimeError(f"无法为 {file_path} 创建模块 spec")
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            else:
                # 从模块路径加载（传统方式）
                mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
        except (ImportError, AttributeError, Exception) as e:
            raise RuntimeError(f"加载 Agent {name} 失败: {e}")
        self._classes[name] = cls
        return cls
    
    def get(self, name: str, base_agent: "Agent", **kwargs) -> "BaseAgent":
        """获取一个 Agent 实例（每个 base_agent 不同 → 不同实例）。"""
        key = f"{name}:{id(base_agent)}"
        if key not in self._instances:
            cls = self._load_class(name)
            self._instances[key] = cls(base_agent, **kwargs)
        return self._instances[key]
    
    def describe_all(self, base_agent: "Agent") -> str:
        """给 Orchestrator / 用户看的总览。"""
        lines = ["# 可用 Agent 一览", ""]
        for name in self.names():
            try:
                a = self.get(name, base_agent)
                lines.append(f"\n{'-'*40}")
                lines.append(a.describe_capabilities())
            except Exception as e:
                lines.append(f"- **{name}**: (加载失败: {e})")
        return "\n".join(lines)
    
    def find_best(self, instruction: str, base_agent: "Agent") -> Optional["BaseAgent"]:
        """
        让每个子 Agent 自评匹配度，返回匹配度最高的那个（>0 才返回）。"""
        best = None
        best_score = 0.0
        for name in self.names():
            if name == "orchestrator":
                continue
            try:
                a = self.get(name, base_agent)
                score = a.can_handle(instruction)
                if score > best_score:
                    best_score = score
                    best = a
            except Exception as e:
                logger.warning(f"[{name}] can_handle 出错: {e}")
        return best


# 全局单例
registry = AgentRegistry()
