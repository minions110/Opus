"""技能加载与匹配核心模块。

提供以下核心能力：

1. **SkillRegistry**   - 技能注册表（按名称存储 Skill 对象）
2. **SkillMatcher**    - 基于简单 TF-IDF 风格的关键词/词频匹配器
3. **SkillManager**    - 统一管理器：负责扫描目录、自动解压 zip、
                         解析 SKILL.md、构建注册表与匹配器

本模块只依赖标准库 + PyYAML，确保可以独立运行。
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from .models import Skill

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_UNPACKED_DIRNAME = "__unpacked__"

_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for",
    "with", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "as", "at", "by",
    "from", "i", "you", "he", "she", "we", "they", "them", "our",
    "your", "my", "his", "her", "me", "do", "does", "did",
    "has", "have", "had", "will", "would", "should", "can", "could",
    "may", "might", "shall", "not", "no", "yes", "so", "if",
    "but", "what", "which", "who", "whom", "how", "when", "where",
    "why", "then", "than", "also", "just", "about", "into", "more", "most",
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "这", "那", "他", "她", "们", "一", "也", "都", "而",
    "要", "会", "对", "能", "可以", "什么", "怎么", "如何", "哪个",
    "哪些", "多少", "一下", "一个", "一些", "没有", "因为", "所以",
    "但是", "如果", "那么", "或者", "以及", "等等", "这个", "那个",
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """将文本拆分为 token 列表（支持中英文）。"""
    if not text:
        return []
    text = text.lower()
    tokens: List[str] = []

    for m in re.finditer(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", text):
        word = m.group(0)
        if word not in _STOPWORDS:
            tokens.append(word)

    # 中文：单字 + 2-grams
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            tokens.append(ch)

    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        for i in range(len(run) - 1):
            tokens.append(run[i : i + 2])

    return tokens


def _term_freq(tokens: List[str]) -> Dict[str, float]:
    if not tokens:
        return {}
    counts: Dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    max_count = float(max(counts.values()))
    return {k: v / max_count for k, v in counts.items()}


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# SKILL.md 解析
# ---------------------------------------------------------------------------

@dataclass
class _SkillFrontMatter:
    name: str = ""
    description: str = ""


def _parse_skill_md(md_path: Path) -> _SkillFrontMatter:
    result = _SkillFrontMatter()
    if not md_path.is_file():
        return result
    try:
        raw = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result
    if not raw.startswith("---"):
        return result
    end = raw.find("---", 3)
    if end == -1:
        return result
    fm_text = raw[3:end].strip()
    try:
        data = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        data = {}
    if isinstance(data, dict):
        result.name = str(data.get("name") or "").strip()
        result.description = str(data.get("description") or "").strip()
    return result


def _extract_md_body(md_path: Path) -> str:
    """返回 SKILL.md 去除 front matter 的正文。"""
    if not md_path.is_file():
        return ""
    try:
        raw = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if raw.startswith("---"):
        end = raw.find("---", 3)
        if end != -1:
            return raw[end + 3:].strip()
    return raw.strip()


def _list_files(directory: Path) -> List[str]:
    if not directory.is_dir():
        return []
    return sorted(
        p.name for p in directory.iterdir()
        if p.is_file() and not p.name.startswith(".")
    )


def _scan_skill_dir(skill_dir: Path, source_root: str, source: str) -> Optional[Skill]:
    md_path = skill_dir / "SKILL.md"
    fm = _parse_skill_md(md_path)
    name = fm.name or skill_dir.name
    description = fm.description or ""
    body = _extract_md_body(md_path)

    short_description = description or ""
    if body and not short_description:
        short_description = body[:120].strip()
    elif short_description:
        short_description = short_description[:120]

    scripts = _list_files(skill_dir / "scripts")
    references = _list_files(skill_dir / "references")
    assets = _list_files(skill_dir / "assets")

    meta: dict = {}
    meta_path = skill_dir / "_meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace")) or {}
        except (OSError, json.JSONDecodeError):
            meta = {}

    return Skill(
        name=name,
        source=source,
        source_root=source_root,
        path=skill_dir.resolve(),
        description=description,
        short_description=short_description,
        body=body,
        scripts=scripts,
        references=references,
        assets=assets,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

class SkillRegistry:
    """简单的技能注册表。"""

    def __init__(self) -> None:
        self._skills: Dict[str, Skill] = {}

    def add(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list(self, source: Optional[str] = None) -> List[Skill]:
        skills = list(self._skills.values())
        if source:
            skills = [s for s in skills
                      if s.source == source or s.source_root == source]
        return sorted(skills, key=lambda s: s.name)

    def __len__(self) -> int:
        return len(self._skills)

    def __iter__(self):
        return iter(self._skills.values())

    def __contains__(self, name: str) -> bool:
        return name in self._skills


# ---------------------------------------------------------------------------
# 匹配器
# ---------------------------------------------------------------------------

class SkillMatcher:
    """基于 token + TF 向量的匹配器。"""

    def __init__(self) -> None:
        self._vectors: Dict[str, Dict[str, float]] = {}

    def index(self, skills: List[Skill]) -> None:
        self._vectors = {}
        for s in skills:
            tokens = _tokenize(s.match_text)
            self._vectors[s.name] = _term_freq(tokens)

    def match(
        self,
        registry: SkillRegistry,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[Tuple[Skill, float]]:
        query = (query or "").strip()
        if not query or not self._vectors:
            return []

        q_vec = _term_freq(_tokenize(query))
        if not q_vec:
            return []

        scored: List[Tuple[str, float]] = []
        for name, vec in self._vectors.items():
            score = _cosine(q_vec, vec)
            score = max(0.0, min(1.0, score))

            # 名字命中给予额外加分
            skill = registry.get(name)
            if skill:
                q_low = query.lower()
                if q_low in skill.name.lower() or skill.name.lower() in q_low:
                    score = min(1.0, score + 0.1)

            if score >= min_score:
                scored.append((name, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        results: List[Tuple[Skill, float]] = []
        for name, score in scored[:top_k]:
            skill = registry.get(name)
            if skill is not None:
                results.append((skill, score))
        return results

    # 兼容旧 API
    def match_with_registry(
        self,
        registry: SkillRegistry,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[Tuple[Skill, float]]:
        return self.match(registry, query, top_k=top_k, min_score=min_score)


# ---------------------------------------------------------------------------
# Zip 统计
# ---------------------------------------------------------------------------

@dataclass
class _ZipStats:
    total: int = 0
    new: int = 0
    cached: int = 0
    failed: int = 0


# ---------------------------------------------------------------------------
# SkillManager
# ---------------------------------------------------------------------------

class SkillManager:
    """技能管理器：负责扫描配置、解压 zip、加载到注册表。"""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.config_root = self.config_path.parent
        self.registry = SkillRegistry()
        self.matcher = SkillMatcher()
        self._zip_stats: Dict[str, _ZipStats] = {}

    # --- 配置 ---

    def _load_config(self) -> dict:
        path = self.config_path
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (yaml.YAMLError, OSError) as exc:
                logger.warning("配置解析失败: %s", exc)
                data = {}
        else:
            logger.warning("配置文件不存在: %s", path)
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("skill_roots", [])
        return data

    def _resolve_roots(self) -> List[dict]:
        cfg = self._load_config()
        roots = cfg.get("skill_roots") or []
        results: List[dict] = []
        for r in roots:
            if not isinstance(r, dict):
                continue
            name = str(r.get("name") or "").strip()
            raw_path = str(r.get("path") or "").strip()
            if not name or not raw_path:
                continue
            p = Path(raw_path)
            if not p.is_absolute():
                p = (self.config_root / p).resolve()
            if not p.is_dir():
                logger.info("跳过不存在的目录: %s", p)
                continue
            results.append({
                "name": name,
                "path": p,
                "format": str(r.get("format") or "openclaw"),
            })
        return results

    # --- Zip 解压 ---

    def _extract_zips_in_root(self, root_path: Path) -> _ZipStats:
        stats = _ZipStats()
        unpacked_dir = root_path / _UNPACKED_DIRNAME
        unpacked_dir.mkdir(parents=True, exist_ok=True)

        for zip_path in sorted(root_path.glob("*.zip")):
            stats.total += 1
            target_name = zip_path.stem
            target_dir = unpacked_dir / target_name
            try:
                z_mtime = zip_path.stat().st_mtime
            except OSError:
                continue

            needs_extract = True
            if target_dir.is_dir():
                try:
                    d_mtime = target_dir.stat().st_mtime
                    if d_mtime >= z_mtime:
                        needs_extract = False
                        stats.cached += 1
                except OSError:
                    pass

            if needs_extract:
                if target_dir.exists():
                    shutil.rmtree(target_dir, ignore_errors=True)
                try:
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        zf.extractall(target_dir)
                    stats.new += 1
                except (zipfile.BadZipFile, OSError) as exc:
                    logger.error("解压 %s 失败: %s", zip_path, exc)
                    stats.failed += 1
                    if target_dir.exists():
                        shutil.rmtree(target_dir, ignore_errors=True)
                    continue

                # 若解压后目录里只有一层同名目录，往上合并
                inner = target_dir / target_name
                if inner.is_dir():
                    for item in list(inner.iterdir()):
                        dst = target_dir / item.name
                        if dst.exists():
                            if dst.is_dir():
                                shutil.rmtree(dst, ignore_errors=True)
                            else:
                                dst.unlink(missing_ok=True)
                        shutil.move(str(item), str(dst))
                    inner.rmdir()

            # 更新 mtime 用作缓存标识
            try:
                os.utime(target_dir, (z_mtime, z_mtime))
            except OSError:
                pass

        return stats

    # --- 收集技能目录 ---

    def _collect_skill_dirs(self, root_path: Path) -> List[Path]:
        dirs: List[Path] = []
        if not root_path.is_dir():
            return dirs

        unpacked = root_path / _UNPACKED_DIRNAME
        if unpacked.is_dir():
            for p in sorted(unpacked.iterdir()):
                if p.is_dir() and not p.name.startswith("."):
                    if (p / "SKILL.md").is_file() or (p / "scripts").is_dir():
                        dirs.append(p)

        for p in sorted(root_path.iterdir()):
            if not p.is_dir():
                continue
            if p.name == _UNPACKED_DIRNAME or p.name.startswith("."):
                continue
            if (p / "SKILL.md").is_file() or (p / "scripts").is_dir():
                dirs.append(p)

        return dirs

    # --- 主流程 ---

    def extract_and_load(self) -> dict:
        self.registry = SkillRegistry()
        self._zip_stats = {}

        roots = self._resolve_roots()
        by_source: Dict[str, int] = {}

        for root in roots:
            name = root["name"]
            path: Path = root["path"]
            fmt = root["format"]

            stats = self._extract_zips_in_root(path)
            self._zip_stats[name] = stats

            for sd in self._collect_skill_dirs(path):
                try:
                    skill = _scan_skill_dir(sd, source_root=name, source=fmt)
                    if skill is None:
                        continue
                    self.registry.add(skill)
                    by_source[name] = by_source.get(name, 0) + 1
                except Exception as exc:  # noqa: BLE001
                    logger.exception("加载技能失败 %s: %s", sd, exc)

        self.matcher.index(self.registry.list())

        total = len(self.registry)
        return {
            "total": total,
            "by_source": by_source,
            "zip_by_source": {
                k: {
                    "total": v.total,
                    "new": v.new,
                    "cached": v.cached,
                    "failed": v.failed,
                }
                for k, v in self._zip_stats.items()
            },
        }

    def reload_skills(self) -> dict:
        return self.extract_and_load()

    # --- 便捷 API ---

    def list_skills(self, source: Optional[str] = None) -> List[dict]:
        return [self._skill_to_dict(s) for s in self.registry.list(source)]

    @staticmethod
    def _skill_to_dict(skill: Skill) -> dict:
        return {
            "name": skill.name,
            "source": skill.source,
            "source_root": skill.source_root,
            "path": str(skill.path),
            "description": skill.description,
            "short_description": skill.short_description,
            "scripts": list(skill.scripts),
            "references": list(skill.references),
            "assets": list(skill.assets),
            "meta": skill.meta,
        }

    def execute_skill(
        self,
        skill_name: str,
        script_name: Optional[str] = None,
        args: Optional[List[str]] = None,
    ):
        """执行技能脚本，返回 ExecResult。"""
        from ..agent.executor import ExecResult, run_skill_script  # 延迟导入

        skill = self.registry.get(skill_name)
        if skill is None:
            return ExecResult(
                skill_name, "missing-skill", 1, "",
                f"找不到技能: {skill_name}",
            )
        return run_skill_script(skill, script_name=script_name, args=args)


# ---------------------------------------------------------------------------
# 顶级便捷函数
# ---------------------------------------------------------------------------

def create_skill_manager(config_path: str | Path) -> SkillManager:
    mgr = SkillManager(config_path)
    mgr.extract_and_load()
    return mgr


def match_skills(
    config_path: str | Path,
    query: str,
    top_k: int = 5,
    min_score: float = 0.0,
) -> List[dict]:
    mgr = create_skill_manager(config_path)
    matches = mgr.matcher.match(
        mgr.registry, query, top_k=top_k, min_score=min_score
    )
    return [
        {"skill": mgr._skill_to_dict(skill), "relevance": round(score, 4)}
        for skill, score in matches
    ]
