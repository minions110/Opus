"""agent 包 - 核心智能体逻辑 + 子 Agent 框架。"""

from .executor import ExecResult, describe_skill, run_skill_script, read_reference
from .agent import Agent
from .registry import registry

__all__ = ["Agent", "ExecResult", "describe_skill", "run_skill_script", "read_reference", "registry"]
