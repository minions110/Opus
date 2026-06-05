"""核心智能体 Agent。

负责：
1. 通过 skill.py 加载和管理技能
2. 根据用户输入匹配最相关的技能
3. 集成 LLM 能力，支持对话和文本生成
4. 根据匹配结果生成结构化的回复
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Any, Dict

import yaml

from ..llm import ModelManager, LLMResponse
from ..skill.skill import SkillManager, SkillRegistry
from ..skill.models import Skill
from ..workflow.workflow import WorkflowExecutor, discover_workflows
from .executor import ExecResult, describe_skill, read_reference, run_skill_script

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 对话消息
# ---------------------------------------------------------------------------

@dataclass
class Message:
    role: str        # "user" | "assistant"
    content: str

    def __str__(self) -> str:
        return f"[{self.role}]: {self.content}"


@dataclass
class AgentResponse:
    reply: str
    matched_skills: List[Tuple[Skill, float]] = field(default_factory=list)
    executed: Optional[ExecResult] = None
    zip_summary: dict = field(default_factory=dict)   # {root_name: zip_count}


# ---------------------------------------------------------------------------
# Agent 主体
# ---------------------------------------------------------------------------

class Agent:
    """统一使用 openclaw 技能的智能体，集成 LLM 能力。"""

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path).resolve()
        self.config = self._load_config(self.config_path)
        self.history: List[Message] = []
        self.workflows: dict = {}
        self.workflow_executor: Optional[WorkflowExecutor] = None
        
        # 通过 skill.py 管理技能
        self.skill_manager = SkillManager(str(self.config_path))
        self.skill_manager.extract_and_load()
        
        # 初始化 LLM 管理器
        self.llm_manager = ModelManager()
        
        self.reload_workflows()

    # ------------------------------------------------------------
    # 配置与加载
    # ------------------------------------------------------------

    @staticmethod
    def _load_config(path: Path) -> dict:
        if not path.exists():
            logger.warning("配置文件不存在: %s，使用默认配置", path)
            return {"skill_roots": [], "history_limit": 20, "min_relevance": 0.15}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            logger.error("配置解析失败: %s", exc)
            return {"skill_roots": [], "history_limit": 20, "min_relevance": 0.15}
        if not isinstance(data, dict):
            return {"skill_roots": [], "history_limit": 20, "min_relevance": 0.15}
        data.setdefault("skill_roots", [])
        data.setdefault("history_limit", 20)
        data.setdefault("min_relevance", 0.15)
        return data

    def reload_skills(self) -> dict:
        """重新扫描技能目录（自动解压 zip）。返回 {total, by_source, zip_by_source}。"""
        # 通过 skill.py 重新加载技能
        return self.skill_manager.reload_skills()

    # ------------------------------------------------------------
    # 工作流加载与执行
    # ------------------------------------------------------------

    def reload_workflows(self) -> dict:
        """扫描 workflow_roots，重新加载所有 workflow.yaml。"""
        roots = self.config.get("workflow_roots", []) or []
        self.workflows = discover_workflows(roots)
        self.workflow_executor = WorkflowExecutor(self, self.workflows)
        return {"total": len(self.workflows), "names": list(self.workflows)}

    # ------------------------------------------------------------
    # LLM 相关方法
    # ------------------------------------------------------------

    def llm_generate(
        self,
        prompt: str,
        provider: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """调用 LLM 生成文本。
        
        Args:
            prompt: 提示词
            provider: LLM 提供商（可选，默认使用配置中的 default_llm）
            **kwargs: 其他参数（max_tokens, temperature 等）
        
        Returns:
            LLMResponse 对象
        """
        return self.llm_manager.generate(prompt, provider=provider, **kwargs)

    def llm_chat(
        self,
        messages: List[Dict[str, str]],
        provider: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """调用 LLM 对话模式。
        
        Args:
            messages: 消息列表，格式为 [{"role": "...", "content": "..."}]
            provider: LLM 提供商（可选）
            **kwargs: 其他参数
        
        Returns:
            LLMResponse 对象
        """
        return self.llm_manager.chat(messages, provider=provider, **kwargs)

    def llm_embed(self, text: str, provider: Optional[str] = None, **kwargs) -> List[float]:
        """生成文本嵌入向量。
        
        Args:
            text: 输入文本
            provider: LLM 提供商（可选）
            **kwargs: 其他参数
        
        Returns:
            嵌入向量列表
        """
        return self.llm_manager.embed(text, provider=provider, **kwargs)

    def llm_list_models(self) -> List[Dict[str, Any]]:
        """列出所有可用的 LLM 模型。"""
        return self.llm_manager.list_available_models()

    def llm_switch_model(self, provider: str) -> bool:
        """切换当前默认 LLM 模型。
        
        Args:
            provider: 提供商名称（openai, anthropic, google, local, azure）
        
        Returns:
            是否切换成功
        """
        return self.llm_manager.switch_model(provider)

    def llm_health_check(self, provider: Optional[str] = None) -> bool:
        """检查 LLM 服务健康状态。"""
        return self.llm_manager.health_check(provider=provider)

    def llm_session(self, session_id: str = "default", provider: Optional[str] = None):
        """获取或创建 LLM 会话。
        
        Args:
            session_id: 会话 ID
            provider: LLM 提供商（可选）
        
        Returns:
            ChatSession 对象
        """
        return self.llm_manager.session(session_id=session_id, provider=provider)

    # ------------------------------------------------------------
    # 工作流加载与执行
    # ------------------------------------------------------------

    def list_workflows(self) -> list:
        if self.workflow_executor is None:
            self.reload_workflows()
        return self.workflow_executor.list_workflows()

    def get_workflow(self, name: str):
        if self.workflow_executor is None:
            self.reload_workflows()
        return self.workflow_executor.get_workflow(name)

    def run_workflow(self, name: str, inputs: Optional[dict] = None):
        if self.workflow_executor is None:
            self.reload_workflows()
        return self.workflow_executor.run(name, inputs=inputs)

    # ------------------------------------------------------------
    # 查询 API
    # ------------------------------------------------------------

    def list_skills(self, source: Optional[str] = None) -> List[Skill]:
        """列出所有技能"""
        return self.skill_manager.registry.list(source)

    def skills_by_source(self) -> dict:
        """按来源分组。"""
        groups: dict = {}
        for s in self.skill_manager.registry.list():
            groups.setdefault(s.source_root, []).append(s)
        return groups

    def find_skill(self, name: str) -> Optional[Skill]:
        """查找指定技能"""
        return self.skill_manager.registry.get(name)

    # ------------------------------------------------------------
    # 交互主循环
    # ------------------------------------------------------------

    def ask(self, user_input: str, *, top_k: int = 5,
            auto_execute: bool = False) -> AgentResponse:
        """处理用户输入，生成响应。"""
        user_input = (user_input or "").strip()
        if not user_input:
            return AgentResponse(reply="请输入一些内容。", matched_skills=[])

        # 特殊命令处理
        special = self._handle_special(user_input)
        if special is not None:
            self._record("user", user_input)
            self._record("assistant", special)
            return AgentResponse(reply=special)

        # 常规：匹配最相关的技能（通过 skill_manager）
        min_score = float(self.config.get("min_relevance", 0.15))
        matches = self.skill_manager.matcher.match(
            self.skill_manager.registry, user_input,
            top_k=top_k, min_score=min_score)

        if not matches:
            reply = (
                "没有匹配到相关技能。\n"
                "可以尝试：\n"
                "  - /list              列出所有技能\n"
                "  - /show <skill>      查看某个技能的详情\n"
                "  - /run <skill> [..]  运行某个技能的脚本\n"
                "  - /reload            重新加载技能"
            )
            self._record("user", user_input)
            self._record("assistant", reply)
            return AgentResponse(reply=reply, matched_skills=[])

        # 生成回复
        reply_lines = ["我为你找到这些相关技能：\n"]
        for i, (skill, score) in enumerate(matches, 1):
            reply_lines.append(
                f"{i}. [{skill.source}] {skill.name}  (相关度 {score:.2f})"
                f"\n   {skill.short_description}\n   路径: {skill.path}"
            )
            if skill.scripts:
                reply_lines.append(f"   可执行: {', '.join(skill.scripts)}")
            reply_lines.append("")

        best = matches[0][0]
        reply_lines.append(
            "\n建议的下一步：\n"
            "  - 输入 /show " + best.name + "   查看完整技能说明\n"
        )
        if best.scripts:
            reply_lines.append(
                "  - 输入 /run " + best.name + "    执行该技能的脚本"
            )
        if best.references:
            reply_lines.append(
                "  - 输入 /ref " + best.name + " <file>  读取参考文档"
            )

        reply = "\n".join(reply_lines)

        executed = None
        if auto_execute and best.scripts:
            executed = run_skill_script(best)
            reply += f"\n\n[已执行] {executed.action}\n返回码: {executed.returncode}\n"
            if executed.stdout:
                reply += f"stdout:\n{executed.stdout[:1000]}\n"
            if executed.stderr:
                reply += f"stderr:\n{executed.stderr[:1000]}\n"

        self._record("user", user_input)
        self._record("assistant", reply)
        return AgentResponse(reply=reply, matched_skills=matches, executed=executed)

    # ------------------------------------------------------------
    # 特殊命令
    # ------------------------------------------------------------

    def _handle_special(self, text: str) -> Optional[str]:
        """处理以 / 开头的特殊命令，返回响应文本；若不命中则返回 None。"""
        if not text.startswith("/"):
            return None
        parts = text[1:].strip().split(None, 2)
        if not parts:
            return None
        cmd = parts[0].lower()

        if cmd in {"help", "?"}:
            return (
                "可用命令：\n"
                "  /list [source]          列出技能\n"
                "  /show <skill>           显示某个技能的完整说明\n"
                "  /run <skill> [args...]  运行技能的脚本\n"
                "  /ref <skill> <file>     读取技能 references/ 中的文件\n"
                "  /install                扫描并解压所有 zip 技能包，然后重新加载\n"
                "  /reload                 重新扫描技能目录\n"
                "  /reload-workflows       重新扫描工作流目录\n"
                "  /workflows              列出所有工作流\n"
                "  /workflow <name>        执行某个工作流\n"
                "  /history                查看对话历史\n"
                "  /clear                  清空对话历史\n"
                "  /count                  查看技能计数\n"
                "  /bye | /quit            退出"
            )

        if cmd in {"list", "ls"}:
            source = parts[1].lower() if len(parts) > 1 else None
            skills = self.list_skills(source)
            if not skills:
                return f"没有找到技能（source={source}）。"
            # 按来源分组
            groups: dict = {}
            for s in skills:
                groups.setdefault(s.source_root, []).append(s)
            lines = [f"共 {len(skills)} 个技能\n"]
            for root, items in sorted(groups.items()):
                lines.append(f"## {root} ({len(items)})")
                for s in sorted(items, key=lambda x: x.name):
                    lines.append(f"  - [{s.source}] {s.name}  →  {s.short_description}")
                lines.append("")
            return "\n".join(lines)

        if cmd in {"show", "info"}:
            if len(parts) < 2:
                return "用法: /show <skill-name>"
            skill = self.find_skill(parts[1])
            if skill is None:
                return f"没有找到技能：{parts[1]}"
            lines = [describe_skill(skill), ""]
            if skill.body:
                lines.append("=" * 40)
                lines.append(skill.body[:3000])
                if len(skill.body) > 3000:
                    lines.append("... (已截断，完整内容见 SKILL.md)")
            return "\n".join(lines)

        if cmd == "run":
            if len(parts) < 2:
                return "用法: /run <skill-name> [args...]"
            skill = self.find_skill(parts[1])
            if skill is None:
                return f"没有找到技能：{parts[1]}"
            args = parts[2].split() if len(parts) > 2 else None
            result = run_skill_script(skill, args=args)
            out = [f"[执行] {result.action}", f"返回码: {result.returncode}"]
            if result.stdout:
                out.append("--- stdout ---")
                out.append(result.stdout[:4000])
            if result.stderr:
                out.append("--- stderr ---")
                out.append(result.stderr[:4000])
            return "\n".join(out)

        if cmd == "ref":
            if len(parts) < 3:
                return "用法: /ref <skill-name> <filename>"
            skill = self.find_skill(parts[1])
            if skill is None:
                return f"没有找到技能：{parts[1]}"
            content = read_reference(skill, parts[2])
            if content is None:
                return f"参考文件不存在或无法读取：{parts[2]}\n可用: {', '.join(skill.references)}"
            return f"[ref] {skill.name}/{parts[2]}\n\n{content[:5000]}"

        if cmd == "reload":
            info = self.reload_skills()
            lines = [f"已重新加载，当前技能总数：{info['total']}", ""]
            lines.append("按来源统计：")
            for root, n in sorted(info["by_source"].items()):
                z = info["zip_by_source"].get(root, {})
                parts = [f"  {root}: {n} 技能"]
                if z.get("total"):
                    zline = f"  (zip: {z.get('new', 0)}新 / {z.get('cached', 0)}缓存 / {z.get('failed', 0)}失败)"
                    parts.append(zline)
                lines.append("".join(parts))
            return "\n".join(lines)

        if cmd == "install":
            # 与 /reload 相同，但输出更强调 zip 解压
            info = self.reload_skills()
            lines = [
                "=" * 50,
                f"技能安装完成。总计 {info['total']} 个技能。",
                "=" * 50,
                "",
            ]
            for root, n in sorted(info["by_source"].items()):
                z = info["zip_by_source"].get(root, {})
                lines.append(f"[{root}]  {n} 技能")
                if z.get("total"):
                    lines.append(f"    zip包: {z['total']}  "
                                 f"(新解压: {z.get('new', 0)}, 已缓存: {z.get('cached', 0)}, 失败: {z.get('failed', 0)})")
                else:
                    lines.append("    zip包: 无")
                # 列出该来源的前 5 个技能
                for s in [x for x in self.skills if x.source_root == root][:5]:
                    extra = ""
                    if s.scripts:
                        extra += f" scripts={len(s.scripts)}"
                    if s.references:
                        extra += f" refs={len(s.references)}"
                    lines.append(f"    - {s.name}{extra}")
                if n > 5:
                    lines.append(f"    ... (+{n - 5} more)")
                lines.append("")
            lines.append("提示: 你可以把 .zip 技能包直接放到以下目录，再运行 /install：")
            for root_cfg in (self.config.get("skill_roots") or []):
                lines.append(f"  - {root_cfg.get('path')}")
            return "\n".join(lines)

        if cmd in {"history", "hist"}:
            if not self.history:
                return "(对话历史为空)"
            return "\n\n".join(str(m) for m in self.history[-20:])

        if cmd in {"clear", "cls"}:
            self.history.clear()
            return "对话历史已清空。"

        if cmd == "count":
            groups = self.skills_by_source()
            total = len(self.skills)
            lines = [f"总技能数: {total}", ""]
            for root, items in sorted(groups.items()):
                lines.append(f"  {root}: {len(items)}")
            return "\n".join(lines)

        if cmd in ("workflows", "list-workflows"):
            wfs = self.list_workflows()
            if not wfs:
                return "没有发现任何工作流。"
            lines = [f"共 {len(wfs)} 个工作流:", ""]
            for w in wfs:
                step_note = f"  ({w.get('step_count', 0)} 步)" if w.get("step_count") else ""
                desc = (w.get("description") or "").strip().replace("\n", " ")
                lines.append(f"  - {w.get('name')}{step_note}")
                if desc:
                    lines.append(f"      {desc[:160]}")
            return "\n".join(lines)

        if cmd == "workflow":
            if len(parts) < 2:
                return "用法: /workflow <name> [inputs_json]"
            name = parts[1]
            inputs: dict = {}
            if len(parts) > 2:
                try:
                    import json as _json
                    inputs = _json.loads(parts[2])
                except Exception:
                    return f"inputs 不是合法 JSON: {parts[2]}"
            r = self.run_workflow(name, inputs=inputs)
            lines = [f"[工作流] {r.name}  ok={r.ok}", ""]
            for s in r.steps:
                status = "OK" if s.ok else "FAIL"
                lines.append(f"  - [{status}] {s.step_id} ({s.action})")
                if s.error:
                    lines.append(f"      error: {s.error}")
                if s.output is not None:
                    out_text = str(s.output)
                    if len(out_text) > 300:
                        out_text = out_text[:300] + "..."
                    lines.append(f"      output: {out_text}")
            if r.error:
                lines.append("")
                lines.append(f"最终错误: {r.error}")
            return "\n".join(lines)

        if cmd in ("reload-workflows", "install-workflows"):
            info = self.reload_workflows()
            return f"已重新加载工作流。总计: {info['total']} 个\n名称: {', '.join(info['names']) or '(无)'}"

        if cmd in {"bye", "quit", "exit"}:
            return "__EXIT__"

        return f"未知命令：{cmd}。输入 /help 查看帮助。"

    # ------------------------------------------------------------
    # 历史管理
    # ------------------------------------------------------------

    def _record(self, role: str, content: str) -> None:
        self.history.append(Message(role=role, content=content[:2000]))
        limit = int(self.config.get("history_limit", 20))
        if len(self.history) > limit * 2:
            self.history = self.history[-limit * 2:]


# ---------------------------------------------------------------------------
# 模块内的简单包文件声明
# ---------------------------------------------------------------------------

AgentResponse.__doc__ = "Agent.ask 的返回结构"
