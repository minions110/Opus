"""执行技能中的脚本与命令。

出于安全考虑，默认不自动执行任何脚本，而是：
- 返回 skill 的 scripts / references / assets 清单
- 让用户显式选择是否执行某个脚本
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from ..skill.models import Skill

logger = logging.getLogger(__name__)


@dataclass
class ExecResult:
    skill_name: str
    action: str             # e.g. "run script x"
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _pick_executable(skill: Skill) -> Optional[Path]:
    """从 skill 的 scripts/ 中挑一个主要脚本（优先同名的 .py 文件）。"""
    if not skill.scripts:
        return None
    scripts_dir = skill.path / "scripts"
    
    py_scripts = [s for s in skill.scripts if s.endswith(".py")]
    other_scripts = [s for s in skill.scripts if not s.endswith(".py")]
    
    # 优先同名的 .py 脚本
    for name in py_scripts:
        stem = Path(name).stem
        if stem == skill.name or stem.replace("_", "-") == skill.name:
            p = scripts_dir / name
            if p.is_file():
                return p
    
    # 如果有 .py 脚本，优先选择第一个 .py 脚本
    if py_scripts:
        p = scripts_dir / py_scripts[0]
        if p.is_file():
            return p
    
    # 最后选择同名的其他脚本
    for name in other_scripts:
        stem = Path(name).stem
        if stem == skill.name or stem.replace("_", "-") == skill.name:
            p = scripts_dir / name
            if p.is_file():
                return p
    
    return scripts_dir / skill.scripts[0]


def _find_bash_on_windows() -> Optional[str]:
    """在 Windows 上查找可用的 bash 解释器。
    
    返回 bash 可执行文件路径，如果找不到返回 None。
    """
    # 优先查找 git bash
    git_bash_paths = [
        os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Git", "bin", "bash.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Git", "bin", "bash.exe"),
        os.path.join(os.environ.get("USERPROFILE", "C:\\Users"), "AppData", "Local", "Programs", "Git", "bin", "bash.exe"),
        "C:\\Git\\bin\\bash.exe",
    ]
    
    for path in git_bash_paths:
        if os.path.exists(path):
            return path
    
    # 查找 WSL bash
    wsl_bash = "bash.exe"
    try:
        result = subprocess.run([wsl_bash, "--version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            return wsl_bash
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    return None


def _parse_shell_script(script_path: Path) -> list:
    """简单解析 shell 脚本，提取 curl 命令。
    
    这是一个简化的解析器，用于在没有 bash 的环境中尝试执行简单脚本。
    支持多行命令（反斜杠续行），只提取 curl 命令。
    """
    commands = []
    try:
        with open(script_path, 'r', encoding='utf-8') as f:
            current_command = ''
            in_curl = False
            
            for line in f:
                line = line.rstrip('\n')
                
                # 处理反斜杠续行（curl 命令常用）
                if in_curl and line.endswith('\\'):
                    current_command += line[:-1].strip() + ' '
                    continue
                
                # 如果有累积的命令，添加到当前行
                if current_command:
                    line = current_command + line.strip()
                    current_command = ''
                    in_curl = False
                
                line = line.strip()
                
                # 跳过注释和空行
                if not line or line.startswith('#'):
                    continue
                
                # 检查是否是 curl 命令开始
                if line.startswith('curl '):
                    # 检查是否续行
                    if line.endswith('\\'):
                        current_command = line[:-1].strip() + ' '
                        in_curl = True
                    else:
                        commands.append(line)
                elif in_curl:
                    # 继续累积 curl 命令
                    if line.endswith('\\'):
                        current_command += line[:-1].strip() + ' '
                    else:
                        current_command += line.strip()
                        commands.append(current_command)
                        current_command = ''
                        in_curl = False
                    
    except Exception as e:
        logger.error(f"解析脚本失败: {e}")
    return commands


def _simple_shell_split(cmd: str) -> list:
    """简单的 shell 命令参数解析器，处理反斜杠转义和引号。"""
    parts = []
    current = ''
    in_double_quotes = False
    in_single_quotes = False
    escape = False
    
    for char in cmd:
        if escape:
            current += char
            escape = False
        elif char == '\\':
            escape = True
        elif char == '"' and not in_single_quotes:
            in_double_quotes = not in_double_quotes
        elif char == "'" and not in_double_quotes:
            in_single_quotes = not in_single_quotes
        elif char == ' ' and not in_double_quotes and not in_single_quotes:
            if current:
                parts.append(current)
                current = ''
        else:
            current += char
    
    if current:
        parts.append(current)
    
    return parts


def _convert_curl_to_powershell(curl_cmd: str) -> str:
    """将 curl 命令转换为 PowerShell 的 Invoke-RestMethod 命令。"""
    # 移除 curl -s
    ps_cmd = curl_cmd.replace('curl -s', '').strip()
    
    # 解析参数（使用自定义解析器处理反斜杠）
    parts = _simple_shell_split(ps_cmd)
    
    method = "POST"
    url = ""
    headers = {}
    data = ""
    
    i = 0
    while i < len(parts):
        part = parts[i]
        if part == '--request':
            i += 1
            method = parts[i]
        elif part == '--url':
            i += 1
            url = parts[i]
        elif part == '--header':
            i += 1
            header = parts[i]
            if ':' in header:
                key, value = header.split(':', 1)
                # 正确处理引号
                key = key.strip()
                value = value.strip()
                # 移除引号（支持单引号和双引号）
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                headers[key] = value
        elif part == '--data':
            i += 1
            data = parts[i]
            # 移除引号
            if (data.startswith('"') and data.endswith('"')) or (data.startswith("'") and data.endswith("'")):
                data = data[1:-1]
        i += 1
    
    # 构建 PowerShell 命令
    ps_parts = []
    ps_parts.append(f'$uri = "{url}"')
    ps_parts.append(f'$method = "{method}"')
    
    # 处理 headers（使用 PowerShell 哈希表语法）
    if headers:
        header_lines = []
        for k, v in headers.items():
            # 安全转义特殊字符
            k_escaped = k.replace('"', '`"').replace('`', '``')
            v_escaped = v.replace('"', '`"').replace('`', '``')
            header_lines.append(f'"{k_escaped}" = "{v_escaped}"')
        ps_parts.append(f'$headers = @{{ {"; ".join(header_lines)} }}')
    
    # 处理 body
    if data:
        # 如果数据是变量引用（以 $ 开头），直接使用变量
        if data.startswith('$') and data[1:].isidentifier():
            ps_parts.append(f'$body = {data}')
        else:
            # 否则作为字符串处理，转义特殊字符
            data_escaped = data.replace('"', '`"').replace('`', '``')
            ps_parts.append(f'$body = "{data_escaped}"')
    
    # 构建 Invoke-RestMethod 调用
    invoke_parts = ['Invoke-RestMethod']
    invoke_parts.append('-Uri $uri')
    invoke_parts.append('-Method $method')
    if headers:
        invoke_parts.append('-Headers $headers')
    if data:
        invoke_parts.append('-Body $body')
        invoke_parts.append('-ContentType "application/json"')
    invoke_parts.append('-TimeoutSec 30')
    
    ps_parts.append(f'$response = {" ".join(invoke_parts)}')
    ps_parts.append('$response | ConvertTo-Json -Depth 10')
    
    return "\n".join(ps_parts)


def _load_api_keys_from_opus_json() -> dict:
    """从 Opus.json 配置文件中加载 API Key。"""
    opus_json_path = Path(__file__).resolve().parent.parent.parent / "data" / "Opus.json"
    if opus_json_path.exists():
        try:
            with open(opus_json_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get("api_keys", {})
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _run_with_powershell_emulation(script_path: Path, args: Optional[List[str]] = None) -> ExecResult:
    """使用 PowerShell 模拟执行简单的 shell 脚本。
    
    Smart Shell Emulator 特性：
    1. 自动识别并转换 curl 命令为 PowerShell 的 Invoke-RestMethod
    2. 支持环境变量替换
    3. 支持基本的 bash 命令转换
    
    这是一个回退方案，当系统没有 bash 时使用。
    """
    commands = _parse_shell_script(script_path)
    if not commands:
        return ExecResult("unknown", "parse-error", 1, "", "无法解析 shell 脚本")
    
    ps_commands = []
    
    # 设置环境变量参数
    if args and len(args) > 0:
        # 转义 PowerShell 字符串中的双引号
        escaped_args0 = args[0].replace('"', '`"')
        ps_commands.append(f'$JSON_INPUT = "{escaped_args0}"')
    
    # 从 Opus.json 加载 API Key 并设置环境变量
    api_keys = _load_api_keys_from_opus_json()
    skills_keys = api_keys.get("skills", {})
    for key_name, key_info in skills_keys.items():
        if key_info.get("enabled", False) and key_info.get("api_key"):
            env_var_name = f"{key_name.upper()}_API_KEY"
            api_key = key_info["api_key"]
            ps_commands.append(f'$env:{env_var_name} = "{api_key}"')
    
    # 只执行 curl 命令，跳过其他命令（如 echo 等）
    has_curl = False
    for cmd in commands:
        # 处理 curl 命令
        if cmd.startswith('curl '):
            ps_cmd = _convert_curl_to_powershell(cmd)
            ps_commands.append(ps_cmd)
            has_curl = True
    
    if not has_curl:
        return ExecResult("powershell-emulation", "no-curl", 1, "", "脚本中没有找到 curl 命令")
    
    full_command = "\n".join(ps_commands)
    
    cmd = ["powershell", "-Command", full_command]
    
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return ExecResult(
            "powershell-emulation",
            f"run: powershell -Command (emulated)",
            proc.returncode,
            proc.stdout or "",
            proc.stderr or "",
        )
    except subprocess.TimeoutExpired:
        return ExecResult("powershell-emulation", "timeout", 124, "", "执行超时 (120s)")
    except OSError as exc:
        return ExecResult("powershell-emulation", "error", 2, "", f"无法执行: {exc}")


def _run_script(skill: Skill, script_path: Path, args: Optional[List[str]] = None) -> ExecResult:
    """智能脚本执行器 - 支持跨平台脚本执行。
    
    Smart Shell Executor 特性：
    1. 自动检测系统上的 shell 环境
    2. 优先使用原生 bash（Linux/macOS）或 Git Bash/WSL（Windows）
    3. 回退到 PowerShell 模拟执行简单脚本
    4. 支持多种脚本格式：.sh, .py, .ps1, .bat, .cmd
    """
    if not script_path.is_file():
        return ExecResult(skill.name, f"missing: {script_path}", 1, "", "脚本不存在")

    if sys.platform.startswith("win"):
        if script_path.suffix == ".ps1":
            cmd = ["powershell", "-File", str(script_path), *(args or [])]
        elif script_path.suffix == ".py":
            cmd = [sys.executable, str(script_path), *(args or [])]
        elif script_path.suffix == ".bat" or script_path.suffix == ".cmd":
            cmd = [str(script_path), *(args or [])]
        elif script_path.suffix == ".sh":
            # Smart Shell: 优先尝试原生 bash
            bash_path = _find_bash_on_windows()
            if bash_path:
                cmd = [bash_path, str(script_path), *(args or [])]
            else:
                # 回退到 PowerShell 模拟执行
                logger.warning(f"未找到 bash，尝试使用 PowerShell 模拟执行: {script_path}")
                return _run_with_powershell_emulation(script_path, args)
        else:
            cmd = [sys.executable, str(script_path), *(args or [])]
    else:
        if script_path.suffix == ".py":
            cmd = [sys.executable, str(script_path), *(args or [])]
        else:
            cmd = [str(script_path), *(args or [])]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(skill.path),
            timeout=120,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return ExecResult(
            skill.name,
            f"run: {shlex.join(str(c) for c in cmd)}",
            proc.returncode,
            proc.stdout or "",
            proc.stderr or "",
        )
    except subprocess.TimeoutExpired:
        return ExecResult(skill.name, "timeout", 124, "", "执行超时 (120s)")
    except OSError as exc:
        return ExecResult(skill.name, "error", 2, "", f"无法执行: {exc}")


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------

def describe_skill(skill: Skill) -> str:
    """返回一个技能的可执行资源描述。"""
    lines = [
        f"技能: {skill.name} ({skill.source})",
        f"  路径: {skill.path}",
        f"  描述: {skill.short_description}",
    ]
    if skill.scripts:
        lines.append(f"  脚本: {', '.join(skill.scripts)}")
    if skill.references:
        lines.append(f"  参考: {', '.join(skill.references)}")
    if skill.assets:
        lines.append(f"  资源: {', '.join(skill.assets[:5])}")
        if len(skill.assets) > 5:
            lines[-1] += f" ... (+{len(skill.assets) - 5})"
    return "\n".join(lines)


def run_skill_script(skill: Skill, script_name: Optional[str] = None,
                     args: Optional[List[str]] = None) -> ExecResult:
    """执行技能的某个脚本（需要显式指定，默认第一个）。"""
    if not skill.scripts:
        return ExecResult(skill.name, "no-script", 1, "", "该技能没有 scripts/ 目录")
    if script_name:
        path = skill.path / "scripts" / script_name
    else:
        path = _pick_executable(skill)
        if path is None:
            return ExecResult(skill.name, "no-script", 1, "", "无法定位脚本")
    return _run_script(skill, path, args)


def read_reference(skill: Skill, ref_name: str) -> Optional[str]:
    """读取技能 references/ 中的一个文件内容。"""
    fp = skill.path / "references" / ref_name
    if not fp.is_file():
        return None
    try:
        return fp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def has_command(cmd: str) -> bool:
    """检查系统中是否存在某条命令（用于判断技能的前置依赖）。"""
    return shutil.which(cmd) is not None
