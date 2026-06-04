"""技能数据模型。

定义 openclaw 格式技能的核心数据结构，以及从 SKILL.md / 目录
解析后的对象模型。该模块仅负责数据承载，不涉及磁盘 IO。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Skill:
    """单个技能的完整描述。

    Attributes:
        name:         技能名称（唯一标识）
        source:       技能格式 ("openclaw")
        source_root:  所属技能根目录的名字（例如 "data-openclaw"）
        path:         技能所在目录的绝对路径
        description:  完整描述（用于匹配的主文本）
        short_description: 一句话摘要（用于列表展示）
        body:         SKILL.md 的正文内容（用于更丰富的展示）
        scripts:      scripts/ 目录下的可执行脚本文件名列表
        references:   references/ 目录下的参考文件名列表
        assets:       assets/ 目录下的资源文件名列表
        meta:         从 _meta.json 等来源得到的附加元数据
    """

    name: str
    source: str
    source_root: str
    path: Path
    description: str = ""
    short_description: str = ""
    body: str = ""
    scripts: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    assets: List[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # 工具属性
    # ------------------------------------------------------------------
    @property
    def match_text(self) -> str:
        """用于意图匹配的合并文本（名称 + 描述 + 短描述）。"""
        parts = [self.name, self.short_description, self.description]
        return "\n".join(p for p in parts if p)

    def to_dict(self) -> dict:
        """序列化为简单 dict（便于 JSON 化 / 打印）。"""
        return {
            "name": self.name,
            "source": self.source,
            "source_root": self.source_root,
            "path": str(self.path),
            "description": self.description,
            "short_description": self.short_description,
            "scripts": list(self.scripts),
            "references": list(self.references),
            "assets": list(self.assets),
            "meta": self.meta,
        }

    def __repr__(self) -> str:
        return (
            f"Skill(name={self.name!r}, source={self.source!r}, "
            f"path={str(self.path)!r})"
        )
