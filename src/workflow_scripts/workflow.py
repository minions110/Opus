"""工作流加载与执行引擎。

目录结构:
    data/workflows/<workflow-name>/workflow.yaml

workflow.yaml 的顶层字段 (最小可用定义):
    name: "工作流名"
    description: "描述"
    inputs:      # 可选
      - name: "x"
        type: "string"
        required: false
        default: "默认值"
    outputs:     # 可选 (仅文档用)
      - name: "result"
    steps:       # 必需
      - id: "step1"
        action: "ask"               # 必需: ask | list | show | run | ref | reload | workflow | log
        query: "你的问题"           # ask 专用
        skill: "skill-name"         # show/run/ref 专用
        args: "..."                 # run 专用 (字符串)
        file: "reference.md"        # ref 专用
        source: "openclaw"          # list 专用 (可选)
        workflow: "another-wf"      # 嵌套调用另一个工作流
        text: "任意文本"            # log 专用
        depends_on: ["step1"]       # 可选: 依赖的步骤 id
        on_error: "continue"        # 可选: fail | continue
        if: "表达式"                # 可选: 基于 inputs 的条件 (支持 `{{inputs.x}} == "值"` 等)

为了兼容用户自己写的 workflow.yaml，本引擎也支持以下宽松格式:
    - 在 step 内用 'skill' / 'prompt_template' 定义一个"提示式"步骤，
      引擎会把它退化为一条 log/文本记录，以便手工阅读。
    - 'depends_on' 字段用于排序步骤执行顺序 (拓扑排序)。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class WorkflowStep:
    id: str
    action: str
    raw: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    on_error: str = "fail"  # fail | continue


@dataclass
class Workflow:
    name: str
    description: str
    path: Path
    steps: List[WorkflowStep] = field(default_factory=list)
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    settings: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    step_id: str
    action: str
    ok: bool
    output: Optional[Any] = None
    error: Optional[str] = None


@dataclass
class WorkflowResult:
    name: str
    ok: bool
    steps: List[StepResult] = field(default_factory=list)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# 表达式求值 (极简 Jinja-lite: {{inputs.x}} 替换)
# ---------------------------------------------------------------------------

_VAR_RE = re.compile(r"\{\{\s*([\w\.]+)\s*\}\}")


def _render(value: Any, ctx: Dict[str, Any]) -> Any:
    """递归地把结构中的 {{inputs.x}} 替换为 ctx 里的值。"""
    if isinstance(value, str):
        def sub(m: re.Match) -> str:
            key = m.group(1)
            # 支持 inputs.xxx / steps.xxx.output 这种简单点语法
            parts = key.split(".")
            cur: Any = ctx
            for p in parts:
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    return m.group(0)  # 找不到，保持原样
            return str(cur)
        return _VAR_RE.sub(sub, value)
    if isinstance(value, list):
        return [_render(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: _render(v, ctx) for k, v in value.items()}
    return value


def _eval_condition(expr: str, ctx: Dict[str, Any]) -> bool:
    """简单条件求值。支持:
         {{inputs.x}} == "abc"
         {{inputs.x}}
         {{inputs.n}} > 5
       使用 ast.literal_eval + 受限制的安全白名单关键字。
    """
    rendered = _render(expr, ctx)
    try:
        import ast
        # 白名单: 仅允许比较 / 布尔运算 / 字面量
        tree = ast.parse(rendered, mode="eval")
        allowed = (ast.Expression, ast.BoolOp, ast.Compare, ast.BinOp,
                   ast.UnaryOp, ast.Not, ast.And, ast.Or,
                   ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
                   ast.Constant, ast.Name, ast.Str, ast.Num)
        for node in ast.walk(tree):
            if not isinstance(node, allowed):
                logger.warning("条件表达式受限: %s", rendered)
                return True
        # 在受限命名空间执行
        ns: Dict[str, Any] = {}
        result = eval(compile(tree, "<workflow-condition>", "eval"), {"__builtins__": {}}, ns)
        return bool(result)
    except Exception:
        logger.debug("条件表达式解析失败: %s", rendered)
        # 解析失败 -> 当作 "真" 来执行，避免意外跳过
        return True


# ---------------------------------------------------------------------------
# 工作流扫描与加载
# ---------------------------------------------------------------------------

def discover_workflows(roots: List[Dict[str, Any]]) -> Dict[str, Workflow]:
    """按配置扫描目录，建立 {name: Workflow} 的映射。"""
    result: Dict[str, Workflow] = {}
    for root_cfg in roots or []:
        raw_path = root_cfg.get("path") or ""
        if not raw_path:
            continue
        path = Path(_expand_path(raw_path))
        if not path.is_dir():
            logger.debug("工作流根目录不存在: %s", path)
            continue
        for sub in sorted(path.iterdir()):
            if not sub.is_dir():
                continue
            yml = sub / "workflow.yaml"
            if not yml.is_file():
                yml = sub / "workflow.yml"
            if not yml.is_file():
                continue
            wf = _load_workflow_file(yml)
            if wf is None:
                continue
            # 目录名作为可调用 key（比 yaml 内的 name 更稳定）
            key = sub.name
            wf.name = key
            wf.raw["display_name"] = wf.raw.get("name") or key
            result[key] = wf
            logger.info("发现工作流: %s (%s)", key, yml)
    return result


def _expand_path(p: str) -> str:
    import os
    expanded = os.path.expandvars(os.path.expanduser(p))
    # 相对路径相对于工作目录
    if not os.path.isabs(expanded) and not Path(expanded).is_absolute():
        try:
            expanded = str(Path.cwd() / expanded)
        except Exception:
            pass
    return expanded


def _load_workflow_file(path: Path) -> Optional[Workflow]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.error("无法加载工作流 %s: %s", path, exc)
        return None
    if not isinstance(raw, dict):
        logger.error("工作流 %s 顶层不是 dict", path)
        return None

    steps_raw = raw.get("steps") or []
    if not isinstance(steps_raw, list):
        logger.error("workflow.yaml 'steps' 不是列表: %s", path)
        steps_raw = []

    steps: List[WorkflowStep] = []
    for idx, s in enumerate(steps_raw):
        if not isinstance(s, dict):
            continue
        action = str(s.get("action") or "").strip().lower()
        # 兼容"LLM 式"工作流：步骤里只写 skill 字段
        # 这种步骤不是本引擎原生支持的 action，降级为 log 提示
        if not action and s.get("skill"):
            action = "log"
        sid = str(s.get("id") or f"step{idx + 1}")
        deps = s.get("depends_on") or []
        if not isinstance(deps, list):
            deps = [str(deps)]
        deps = [str(x) for x in deps]
        on_error = str(s.get("on_error", "fail")).lower()
        if on_error not in ("fail", "continue"):
            on_error = "fail"
        steps.append(WorkflowStep(
            id=sid,
            action=action,
            raw=s,
            depends_on=deps,
            on_error=on_error,
        ))

    return Workflow(
        name=str(raw.get("name") or path.parent.name),
        description=str(raw.get("description") or ""),
        path=path.parent,
        steps=_toposort(steps),
        inputs=raw.get("inputs") or [],
        outputs=raw.get("outputs") or [],
        settings=raw.get("settings") or {},
        raw=raw,
    )


def _toposort(steps: List[WorkflowStep]) -> List[WorkflowStep]:
    """按 depends_on 拓扑排序。若有环，按原顺序返回。"""
    if not steps:
        return steps
    by_id: Dict[str, WorkflowStep] = {s.id: s for s in steps}
    indeg: Dict[str, int] = {s.id: 0 for s in steps}
    adj: Dict[str, List[str]] = {s.id: [] for s in steps}
    for s in steps:
        for dep in s.depends_on:
            if dep in by_id and dep != s.id:
                indeg[s.id] = indeg.get(s.id, 0) + 1
                adj.setdefault(dep, []).append(s.id)
    ready = [sid for sid, d in indeg.items() if d == 0]
    order: List[WorkflowStep] = []
    while ready:
        sid = ready.pop(0)
        order.append(by_id[sid])
        for nxt in adj.get(sid, []):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
    if len(order) != len(steps):
        # 存在环 -> 回退到原顺序
        return steps
    return order


# ---------------------------------------------------------------------------
# 工作流执行
# ---------------------------------------------------------------------------

class WorkflowExecutor:
    """把 workflow.yaml 的步骤路由到 Agent 提供的能力。"""

    def __init__(self, agent: Any, workflows: Dict[str, Workflow]):
        self.agent = agent
        self.workflows = workflows

    # -------------- 顶层 API --------------

    def run(self, name: str, inputs: Optional[Dict[str, Any]] = None) -> WorkflowResult:
        wf = self.workflows.get(name)
        if wf is None:
            return WorkflowResult(name=name, ok=False,
                                  error=f"找不到工作流: {name}。可用: {list(self.workflows)}")
        return self._run_workflow(wf, inputs or {})

    def list_workflows(self) -> List[Dict[str, Any]]:
        return [
            {"name": wf.name,
             "description": wf.description,
             "step_count": len(wf.steps),
             "inputs": [{"name": i.get("name"), "required": i.get("required", False),
                         "default": i.get("default")}
                        for i in wf.inputs],
             "path": str(wf.path)}
            for wf in self.workflows.values()
        ]

    def get_workflow(self, name: str) -> Optional[Dict[str, Any]]:
        wf = self.workflows.get(name)
        if wf is None:
            return None
        return {
            "name": wf.name,
            "description": wf.description,
            "steps": [
                {"id": s.id, "action": s.action,
                 "depends_on": s.depends_on,
                 "on_error": s.on_error,
                 **{k: v for k, v in s.raw.items() if k not in ("id", "action", "depends_on", "on_error")}}
                for s in wf.steps
            ],
            "inputs": wf.inputs,
            "outputs": wf.outputs,
            "settings": wf.settings,
            "path": str(wf.path),
        }

    # -------------- 内部执行 --------------

    def _run_workflow(self, wf: Workflow, inputs: Dict[str, Any]) -> WorkflowResult:
        # 填充默认值
        ctx: Dict[str, Any] = {"inputs": self._defaults(wf.inputs, inputs), "steps": {}}
        result = WorkflowResult(name=wf.name, ok=True)

        for step in wf.steps:
            # 条件跳过
            if "if" in step.raw and step.raw["if"]:
                try:
                    if not _eval_condition(str(step.raw["if"]), ctx):
                        result.steps.append(StepResult(step.id, step.action,
                                                       ok=True, output="(skipped)"))
                        continue
                except Exception as exc:
                    result.steps.append(StepResult(step.id, step.action,
                                                   ok=False, error=f"if 解析失败: {exc}"))
                    if step.on_error == "fail":
                        result.ok = False
                        result.error = f"步骤 {step.id} 失败"
                        return result
                    continue

            # 依赖失败跳过
            failed_deps = [d for d in step.depends_on if not self._step_ok(result, d)]
            if failed_deps:
                result.steps.append(StepResult(step.id, step.action,
                                               ok=False,
                                               error=f"依赖失败: {', '.join(failed_deps)}"))
                if step.on_error == "fail":
                    result.ok = False
                    result.error = f"步骤 {step.id} 因依赖失败"
                    return result
                continue

            try:
                sr = self._dispatch_step(step, ctx)
            except Exception as exc:
                logger.exception("工作流步骤异常: %s", step.id)
                sr = StepResult(step.id, step.action, ok=False, error=str(exc))

            result.steps.append(sr)
            # 登记到 ctx["steps"] 以便后续步骤引用
            ctx["steps"][step.id] = {
                "ok": sr.ok,
                "output": sr.output,
                "error": sr.error,
            }

            if not sr.ok and step.on_error == "fail":
                result.ok = False
                result.error = f"步骤 {step.id} 失败: {sr.error}"
                return result

        result.ok = all(s.ok for s in result.steps)
        return result

    @staticmethod
    def _defaults(schema: List[Dict[str, Any]], provided: Dict[str, Any]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for item in schema or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            merged[name] = item.get("default")
        for k, v in (provided or {}).items():
            merged[k] = v
        return merged

    @staticmethod
    def _step_ok(result: WorkflowResult, step_id: str) -> bool:
        for s in result.steps:
            if s.step_id == step_id:
                return s.ok
        return True

    def _dispatch_step(self, step: WorkflowStep, ctx: Dict[str, Any]) -> StepResult:
        # 先渲染 raw 里的模板变量
        rendered_raw = _render(step.raw, ctx)
        action = step.action

        if action == "ask":
            query = rendered_raw.get("query") or rendered_raw.get("text") or ""
            if not query:
                return StepResult(step.id, action, False, error="ask 步骤缺少 'query'")
            top_k = int(rendered_raw.get("top_k") or 5)
            resp = self.agent.ask(query, top_k=top_k)
            return StepResult(step.id, action, True, output=resp.reply)

        if action == "list":
            source = rendered_raw.get("source") or None
            skills = self.agent.list_skills(source=source) if source else self.agent.list_skills()
            return StepResult(step.id, action, True,
                              output=[s.name for s in skills])

        if action == "show":
            sname = rendered_raw.get("skill") or rendered_raw.get("name")
            if not sname:
                return StepResult(step.id, action, False, error="show 缺少 'skill'")
            skill = self.agent.find_skill(sname)
            if skill is None:
                return StepResult(step.id, action, False, error=f"未找到技能: {sname}")
            from ..agent.executor import describe_skill
            return StepResult(step.id, action, True,
                              output={"name": skill.name, "description": skill.description,
                                      "summary": describe_skill(skill)})

        if action == "run":
            sname = rendered_raw.get("skill")
            if not sname:
                return StepResult(step.id, action, False, error="run 缺少 'skill'")
            skill = self.agent.find_skill(sname)
            if skill is None:
                return StepResult(step.id, action, False, error=f"未找到技能: {sname}")
            args = rendered_raw.get("args")
            from ..agent.executor import run_skill_script
            r = run_skill_script(skill, args=args.split() if isinstance(args, str) else None)
            return StepResult(step.id, action,
                              ok=r.returncode == 0,
                              output={"returncode": r.returncode,
                                      "stdout": r.stdout, "stderr": r.stderr,
                                      "action": r.action})

        if action == "ref":
            sname = rendered_raw.get("skill")
            fname = rendered_raw.get("file")
            if not sname or not fname:
                return StepResult(step.id, action, False, error="ref 需要 'skill' 和 'file'")
            skill = self.agent.find_skill(sname)
            if skill is None:
                return StepResult(step.id, action, False, error=f"未找到技能: {sname}")
            from ..agent.executor import read_reference
            content = read_reference(skill, fname)
            if content is None:
                return StepResult(step.id, action, False, error=f"参考文件不存在: {fname}")
            return StepResult(step.id, action, True, output={"file": fname, "content": content})

        if action in ("reload", "install"):
            info = self.agent.reload_skills()
            return StepResult(step.id, action, True, output=info)

        if action == "workflow":
            sub = rendered_raw.get("workflow")
            if not sub:
                return StepResult(step.id, action, False, error="缺少 'workflow' 字段")
            sub_inputs = rendered_raw.get("inputs") or {}
            if not isinstance(sub_inputs, dict):
                sub_inputs = {}
            r = self.run(sub, inputs=sub_inputs)
            return StepResult(step.id, action, ok=r.ok,
                              output={"workflow": sub,
                                      "steps": [{"id": s.step_id, "ok": s.ok, "error": s.error}
                                                for s in r.steps]},
                              error=r.error)

        if action == "log":
            text = rendered_raw.get("text") or rendered_raw.get("message") or rendered_raw.get("query") or ""
            # 兼容: 老版 workflow.yaml 里写的 'skill' 字段，这里作为提示打印
            if not text and rendered_raw.get("skill"):
                text = f"[提示] 该步骤引用技能: {rendered_raw['skill']}" \
                       f"  (本引擎当前将其作为日志，不自动调用 LLM)"
            logger.info("[workflow:%s] %s", step.id, text)
            return StepResult(step.id, action, True, output=str(text))

        # 未知动作 —— 作为 on_error=continue 处理
        return StepResult(step.id, action, False,
                          error=f"未知 action: {action} (支持: ask/list/show/run/ref/reload/workflow/log)")
