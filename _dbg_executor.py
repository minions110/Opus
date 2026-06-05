"""临时脚本：诊断 skill 的 script_path 被 executor 如何解析。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.skill_scripts.skill import create_skill_manager
from src.agent.executor import _pick_executable, _run_script

cfg = r"g:\agent\Opus\config.yaml"
mgr = create_skill_manager(cfg)
skill = mgr.registry.get("search")
print("skill.name:", skill.name)
print("skill.path:", skill.path)
print("skill.scripts:", skill.scripts)

script = _pick_executable(skill)
print("script:", script)
print("script.name:", script.name if script else None)
print("script.suffix:", script.suffix if script else None)
print("script.is_file:", script.is_file() if script else None)

print("\n--- 直接跑 ---\n")
result = _run_script(skill, script, args=['{"query":"test"}'])
print("action:", result.action)
print("returncode:", result.returncode)
print("stdout:", result.stdout)
print("stderr:", result.stderr)
