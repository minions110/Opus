"""Smart Shell Executor —— 跨平台脚本执行器。

设计目标:
  1. 技能包里的脚本 (.sh / .py / .ps1 / .bat) 在 Windows / Linux / macOS 上都能跑
  2. 自动从 Opus.json（api_keys.{skills,llm,other}.<name>.api_key）为子进程注入环境变量
     映射规则:  skill 名或 provider 名大写，附加 "_API_KEY"
       - bocha         -> BOCHA_API_KEY
       - search        -> SEARCH_API_KEY  (以及 TAVILY_API_KEY 兼容)
       - deepseek      -> DEEPSEEK_API_KEY
       - openai        -> OPENAI_API_KEY
       - doubao        -> DOUBAO_API_KEY
       - anthropic     -> ANTHROPIC_API_KEY
       - google        -> GOOGLE_API_KEY
       - azure         -> AZURE_API_KEY
       - local         -> LOCAL_API_KEY
  3. 执行优先级（对同一个技能的多个脚本）: .py > .sh > .ps1 > .bat
  4. .py 永远用 sys.executable 子进程跑；.sh 优先 bash，无 bash 时用系统默认
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..skill.models import Skill

logger = logging.getLogger(__name__)


@dataclass
class ExecResult:
    skill_name: str
    action: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


# ---------------------------------------------------------------------------
# Opus.json 解析 & API key 注入
# ---------------------------------------------------------------------------

_CACHED_OPUS: Optional[Tuple[Path, dict]] = None


def _find_opus_json(cwd: Optional[Path] = None) -> Optional[Path]:
    """在常见位置查找 Opus.json。"""
    roots = [
        Path(cwd or Path.cwd()),
        Path(__file__).resolve().parent.parent.parent,
        Path(__file__).resolve().parent.parent,
        Path.cwd(),
    ]
    seen = set()
    for root in roots:
        if not root:
            continue
        for candidate in [root / "data" / "Opus.json",
                          root / "Opus.json"]:
            try:
                rp = candidate.resolve()
            except OSError:
                continue
            key = str(rp)
            if key in seen:
                continue
            seen.add(key)
            if rp.is_file():
                return rp
    return None


def _load_opus_keys(cwd: Optional[Path] = None) -> Dict[str, str]:
    """读取 Opus.json 里的 api_keys，返回 {ENV_VAR_NAME: api_key}。"""
    global _CACHED_OPUS
    opus_path = _find_opus_json(cwd)
    if opus_path is None:
        return {}
    try:
        mtime = opus_path.stat().st_mtime
        if _CACHED_OPUS is not None and _CACHED_OPUS[0] == opus_path and _CACHED_OPUS[1]["__mtime__"] == mtime:
            cached_copy = dict(_CACHED_OPUS[1])
            cached_copy.pop("__mtime__", None)
            return cached_copy
    except OSError:
        pass

    try:
        raw = opus_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    result: Dict[str, str] = {}
    api_keys = data.get("api_keys") or {}
    if not isinstance(api_keys, dict):
        return {}

    for category in ("skills", "llm", "other"):
        items = api_keys.get(category) or {}
        if not isinstance(items, dict):
            continue
        for name, info in items.items():
            if not isinstance(info, dict):
                continue
            key = info.get("api_key")
            if not key:
                continue
            env_name = str(name).upper().replace("-", "_").replace(" ", "_") + "_API_KEY"
            result[env_name] = str(key)
            # 兼容：search -> TAVILY_API_KEY （因为 search 技能内部用的是 TAVILY_API_KEY）
            if name == "search" and "TAVILY_API_KEY" not in os.environ:
                result["TAVILY_API_KEY"] = str(key)

    _CACHED_OPUS = (opus_path, {"__mtime__": mtime, **result})
    return result


def _merged_env(extra: Optional[Dict[str, str]] = None,
                cwd: Optional[Path] = None) -> Dict[str, str]:
    """合并当前进程 env + Opus.json 里的 api key + 调用方额外注入。"""
    merged: Dict[str, str] = dict(os.environ)
    for k, v in _load_opus_keys(cwd).items():
        merged.setdefault(k, v)
    if extra:
        for k, v in extra.items():
            merged[k] = v
    # Python 子进程编码
    merged.setdefault("PYTHONIOENCODING", "utf-8")
    return merged


# ---------------------------------------------------------------------------
# 脚本选择
# ---------------------------------------------------------------------------

def _pick_executable(skill: Skill) -> Optional[Path]:
    """为技能选择一个主要脚本：优先同名 .py；否则按 .py > .sh > .ps1 > .bat 顺序。"""
    if not skill.scripts:
        return None
    scripts_dir = skill.path / "scripts"
    py_scripts = [s for s in skill.scripts if s.endswith(".py")]
    sh_scripts = [s for s in skill.scripts if s.endswith(".sh")]
    ps1_scripts = [s for s in skill.scripts if s.endswith(".ps1")]
    bat_scripts = [s for s in skill.scripts if s.endswith(".bat") or s.endswith(".cmd")]

    # 优先：同名
    for bucket in (py_scripts, sh_scripts, ps1_scripts, bat_scripts):
        for name in bucket:
            stem = Path(name).stem
            if stem == skill.name or stem.replace("_", "-") == skill.name or stem.replace("-", "_") == skill.name:
                p = scripts_dir / name
                if p.is_file():
                    return p

    # 再按扩展名优先级返回第一个存在的
    for bucket in (py_scripts, sh_scripts, ps1_scripts, bat_scripts):
        if bucket:
            p = scripts_dir / bucket[0]
            if p.is_file():
                return p
    return None


# ---------------------------------------------------------------------------
# 执行逻辑
# ---------------------------------------------------------------------------

def _run_python_script(skill: Skill, script: Path, args: Optional[List[str]] = None) -> ExecResult:
    cmd: List[str] = [sys.executable, str(script)] + list(args or [])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=str(skill.path),
            timeout=180,
            env=_merged_env(),
        )
        return ExecResult(skill.name,
                           f"run: {os.path.basename(cmd[0])} {script.name}{' ...' if args else ''}",
                           proc.returncode,
                           proc.stdout or "",
                           proc.stderr or "")
    except subprocess.TimeoutExpired:
        return ExecResult(skill.name, "timeout", 124, "", "执行超时 (180s)")
    except OSError as exc:
        return ExecResult(skill.name, "os-error", 2, "", f"无法执行: {exc}")


def _run_shell_script(skill: Skill, script: Path, args: Optional[List[str]] = None) -> ExecResult:
    """在类 Unix 系统上用 bash/sh 执行 .sh；在 Windows 上若有 Git Bash 也走 bash，否则回退到 PowerShell。"""
    # Windows: 找 bash.exe（Git Bash / WSL）
    if sys.platform.startswith("win"):
        bash_candidates = [
            shutil.which("bash.exe") or "",
            shutil.which("bash") or "",
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
            r"C:\Windows\System32\bash.exe",
        ]
        for c in bash_candidates:
            if c and os.path.exists(c):
                cmd = [c, str(script)] + list(args or [])
                try:
                    proc = subprocess.run(
                        cmd, capture_output=True, text=True,
                        encoding='utf-8', errors='replace',
                        cwd=str(skill.path), timeout=180,
                        env=_merged_env(),
                    )
                    return ExecResult(skill.name, f"bash: {script.name}", proc.returncode,
                                      proc.stdout or "", proc.stderr or "")
                except (subprocess.TimeoutExpired, OSError) as exc:
                    return ExecResult(skill.name, "bash-error", 2, "", str(exc))

        # 无 bash：用 PowerShell
        pwsh = shutil.which("pwsh") or shutil.which("powershell.exe") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        # PowerShell 执行 .sh 通常无意义，但可以尝试直接执行；这里提示用户装 bash
        try:
            escaped_args = " ".join(shlex.quote(a) for a in (args or []))
            script_text = f"& '{script}' {escaped_args}"
            proc = subprocess.run(
                [pwsh, "-NoProfile", "-NonInteractive", "-Command", script_text],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                cwd=str(skill.path), timeout=180,
                env=_merged_env(),
            )
            return ExecResult(skill.name, f"powershell: {script.name}",
                              proc.returncode, proc.stdout or "", proc.stderr or "")
        except (subprocess.TimeoutExpired, OSError) as exc:
            return ExecResult(skill.name, "powershell-error", 2, "", str(exc))

    # Linux / macOS：bash
    shell = shutil.which("bash") or shutil.which("sh") or "/bin/sh"
    cmd = [shell, str(script)] + list(args or [])
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            cwd=str(skill.path), timeout=180,
            env=_merged_env(),
        )
        return ExecResult(skill.name, f"{os.path.basename(shell)}: {script.name}",
                          proc.returncode, proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired:
        return ExecResult(skill.name, "timeout", 124, "", "执行超时 (180s)")
    except OSError as exc:
        return ExecResult(skill.name, "shell-error", 2, "", f"无法执行: {exc}")


def _run_ps1_script(skill: Skill, script: Path, args: Optional[List[str]] = None) -> ExecResult:
    pwsh = shutil.which("pwsh") or shutil.which("powershell.exe") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    try:
        escaped_args = " ".join(shlex.quote(a) for a in (args or []))
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(script)] + list(args or []),
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            cwd=str(skill.path), timeout=180,
            env=_merged_env(),
        )
        return ExecResult(skill.name, f"powershell: {script.name}",
                          proc.returncode, proc.stdout or "", proc.stderr or "")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return ExecResult(skill.name, "powershell-error", 2, "", str(exc))


def _run_bat_script(skill: Skill, script: Path, args: Optional[List[str]] = None) -> ExecResult:
    try:
        cmd = ["cmd.exe", "/C", str(script)] + list(args or [])
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            cwd=str(skill.path), timeout=180,
            env=_merged_env(),
        )
        return ExecResult(skill.name, f"cmd: {script.name}",
                          proc.returncode, proc.stdout or "", proc.stderr or "")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return ExecResult(skill.name, "cmd-error", 2, "", str(exc))


def run_skill_script(skill: Skill, script_name: Optional[str] = None,
                     args: Optional[List[str]] = None) -> ExecResult:
    """执行技能脚本。"""
    if not skill.scripts:
        return ExecResult(skill.name, "no-scripts", 1, "", "该技能没有 scripts/ 目录")

    if script_name:
        script = skill.path / "scripts" / script_name
        if not script.is_file():
            return ExecResult(skill.name, "missing-script", 1, "", f"脚本不存在: {script}")
    else:
        picked = _pick_executable(skill)
        if picked is None:
            return ExecResult(skill.name, "no-script", 1, "", "无法定位脚本")
        script = picked

    ext = script.suffix.lower()
    if ext == ".py":
        return _run_python_script(skill, script, args)
    if ext == ".sh":
        return _run_shell_script(skill, script, args)
    if ext == ".ps1":
        return _run_ps1_script(skill, script, args)
    if ext in (".bat", ".cmd"):
        return _run_bat_script(skill, script, args)

    # 未知扩展名：当成可执行文件直接跑
    try:
        cmd = [str(script)] + list(args or [])
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding='utf-8', errors='replace',
                              cwd=str(skill.path), timeout=180, env=_merged_env())
        return ExecResult(skill.name, f"exec: {script.name}", proc.returncode,
                          proc.stdout or "", proc.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ExecResult(skill.name, "exec-error", 2, "", str(exc))


# ---------------------------------------------------------------------------
# 辅助：列出脚本、读取参考文件
# ---------------------------------------------------------------------------

def describe_skill(skill: Skill) -> str:
    lines = [f"技能: {skill.name} ({skill.source})",
             f"  路径: {skill.path}",
             f"  描述: {skill.short_description}"]
    if skill.scripts:
        lines.append(f"  脚本: {', '.join(skill.scripts)}")
    if skill.references:
        lines.append(f"  参考: {', '.join(skill.references)}")
    if skill.assets:
        lines.append(f"  资源: {', '.join(skill.assets[:5])}"
                     + (f" ... (+{len(skill.assets) - 5})" if len(skill.assets) > 5 else ""))
    return "\n".join(lines)


def read_reference(skill: Skill, ref_name: str) -> Optional[str]:
    fp = skill.path / "references" / ref_name
    if not fp.is_file():
        return None
    try:
        return fp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def has_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None
