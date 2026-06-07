"""
BaseAgent —— 所有子 Agent 的公共基类。

约定：每个 Agent 在 src/agent/<name>/ 下有以下数据文件：
    src/agent/<name>/
        identity.json      身份设定（name, description, system_prompt, style...）
        config.json        配置参数（温度、provider、阈值...）
        memory.json        长期记忆（由 Memory 管理）
        tasks.json         该 Agent 的任务清单（可选）
        knowledge/         知识库目录（由 KnowledgeBase 管理）

BaseAgent 自动：
  - 从 src/agent/<name>/ 加载 identity / config
  - 连接 memory.json / knowledge/
  - 提供统一的 llm() / workflow() / remember() / recall() 接口
  - 提供统一的 can_handle() / describe_capabilities() 给调度器用
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .agent import Agent
from .memory import Memory
from .knowledge import KnowledgeBase
from .storage import Storage

logger = logging.getLogger(__name__)

# 数据根目录：项目根 / data / agents （每个子 Agent 一个子目录，代码 + 数据都在那里）
PROJECT_ROOT = Path(__file__).resolve().parents[2]       # src/agent/base.py → .../opus
DATA_AGENTS_ROOT = PROJECT_ROOT / "data" / "agents"
OUTPUTS_ROOT = PROJECT_ROOT / "outputs"


# ───────────────────────────────────────────────────────
class BaseAgent:
    """所有子 Agent 继承这个类。"""
    
    # 子类必须覆盖
    name: str = "base"
    description: str = "基础 Agent"
    supported_tasks: List[str] = []
    
    def __init__(self, agent: Agent, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            agent:    共享的主 Agent（提供 llm_chat / run_workflow / run_skill）
            config:   覆盖默认配置（可选）
        """
        self.base_agent = agent
        self.data_dir = DATA_AGENTS_ROOT / self.name
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 身份 + 配置：从 src/agent/<name>/identity.json 等文件读
        self.identity: Dict[str, Any] = self._load_json("identity.json", default=self._default_identity())
        self.config: Dict[str, Any] = self._load_json("config.json", default=self._default_config())
        if config:
            self.config.update(config)
        
        # 记忆 / 知识库 / 存储
        self.memory = Memory(self.data_dir / "memory.json")
        self.knowledge = KnowledgeBase(self.data_dir / "knowledge")
        self.storage = Storage(OUTPUTS_ROOT, agent_name=self.name)
        
        # 上下文：当前 session 的对话/中间状态（进程结束即丢）
        self.context: Dict[str, Any] = {}
        
        logger.info(f"[{self.name}] 初始化完成，数据目录: {self.data_dir}")
    
    # ─── 子类必须实现 ───────────────────────────────
    def run(self, **kwargs) -> Dict[str, Any]:
        """主入口：执行一次任务，返回结果 dict。"""
        raise NotImplementedError
    
    def can_handle(self, instruction: str) -> float:
        """返回 0~1 的匹配度，给 Orchestrator 路由用。"""
        return 0.0
    
    # ─── 对外描述 ─────────────────────────────────
    def describe_capabilities(self) -> str:
        parts = [f"## {self.identity.get('display_name', self.name)}"]
        if self.identity.get("role"):
            parts.append(f"- **角色**: {self.identity['role']}")
        if self.identity.get("system_prompt"):
            parts.append(f"- **任务说明**: {self.identity['system_prompt'][:200]}")
        if self.supported_tasks:
            parts.append(f"- **可执行任务**: {', '.join(self.supported_tasks)}")
        parts.append(f"- **记忆条目**: {self.memory.count()}")
        return "\n".join(parts)
    
    def __str__(self) -> str:
        return f"[{self.name}] {self.description}"
    
    # ─── 统一工具：LLM / 工作流 / 记忆 ─────────────
    def llm(self, messages: List[Dict[str, str]], **kwargs) -> Any:
        """统一调 LLM，自动读取本 Agent 的默认 provider/model/temperature。"""
        provider = kwargs.pop("provider", None) or self.config.get("llm_provider")
        model = kwargs.pop("model", None) or self.config.get("llm_model")
        temperature = kwargs.pop("temperature", None)
        if temperature is None:
            temperature = self.config.get("temperature", 0.7)
        # 如果 LLM 层本身没有 provider/model 参数名，就不传
        call_kwargs = {"messages": messages, "temperature": temperature}
        if provider:
            call_kwargs["provider"] = provider
        if model:
            call_kwargs["model"] = model
        call_kwargs.update(kwargs)
        return self.base_agent.llm_chat(**call_kwargs)
    
    def workflow(self, name: str, inputs: Optional[Dict[str, Any]] = None) -> Any:
        """统一跑工作流。"""
        return self.base_agent.run_workflow(name, inputs or {})
    
    def remember(self, key: str, value: Any) -> None:
        self.memory.remember(key, value)
    
    def recall(self, key: str, default: Any = None) -> Any:
        return self.memory.recall(key, default)
    
    def append_history(self, record: Dict[str, Any]) -> int:
        """追加一条长期记忆记录（写入 memory.json history 列表）。"""
        return self.memory.append(record)
    
    # ─── 去重 / 冷却工具 ──────────────────────────
    def is_query_recently_used(self, query: str, days: int = 7, 
                              history_field: str = "query") -> bool:
        """检查某个 query 在最近 n 天内是否已用过。"""
        if not query:
            return False
        cutoff = datetime.now() - timedelta(days=days)
        for rec in self.memory.all_history():
            q = rec.get(history_field)
            if q and q.strip() == query.strip():
                ts = rec.get("timestamp")
                if ts:
                    try:
                        t = datetime.fromisoformat(ts)
                        if t >= cutoff:
                            return True
                    except ValueError:
                        pass
        return False
    
    def is_title_duplicate(self, title: str, threshold: float = 0.75) -> bool:
        """检查标题是否与历史记录相似（默认相似度 0.75 判重）。"""
        return self.memory.title_exists_similar(title, threshold=threshold)
    
    # ─── 文件加载 ─────────────────────────────────
    def _load_json(self, filename: str, default: Dict[str, Any]) -> Dict[str, Any]:
        path = self.data_dir / filename
        if not path.exists():
            # 首次不存在就写一份默认值，方便你手动编辑
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 把 default 里没有但 default 有的字段补齐
            for k, v in default.items():
                data.setdefault(k, v)
            return data
        except Exception as e:
            logger.warning(f"[{self.name}] 加载 {filename} 失败，使用默认: {e}")
            return default
    
    # ─── 默认值（子类可覆盖） ─────────────────────
    def _default_identity(self) -> Dict[str, Any]:
        return {
            "display_name": self.name,
            "role": "AI Agent",
            "description": self.description,
            "system_prompt": self.description,
        }
    
    def _default_config(self) -> Dict[str, Any]:
        return {
            "llm_provider": "deepseek",
            "llm_model": "deepseek-chat",
            "temperature": 0.7,
            "title_dedup_threshold": 0.75,
            "query_cooldown_days": 7,
        }
