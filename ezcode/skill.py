"""Skill Loading：扫描 skills/*/SKILL.md，目录进 system prompt，全文按需加载。

skill 是叶子模块（不 import 其他 ezcode 模块），供 config 在组装 system prompt 时引用，
避免 config -> skill -> config 的循环导入。SKILLS_DIR 基于 cwd，与 config.WORKDIR 一致。
"""

import re
from pathlib import Path

import yaml

SKILLS_DIR = Path.cwd() / "skills"


class SkillLoader:
    """扫描技能目录，解析 YAML frontmatter，提供 catalog()（目录）与 load()（全文）。"""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills: dict[str, dict[str, str]] = {}
        self.scan()

    @staticmethod
    def parse_frontmatter(text: str) -> tuple[dict, str]:
        """解析 --- 分隔的 YAML frontmatter，返回 (metadata, body)。"""
        lines = text.splitlines(keepends=True)
        if not lines or lines[0].rstrip("\r\n") != "---":
            return {}, text

        closing_index = next(
            (i for i, line in enumerate(lines[1:], start=1)
             if line.rstrip("\r\n") == "---"),
            None,
        )
        if closing_index is None:
            return {}, text

        frontmatter = "".join(lines[1:closing_index])
        body = "".join(lines[closing_index + 1:]).strip()
        try:
            metadata = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        return metadata, body

    def scan(self):
        self.skills.clear()
        if not self.skills_dir.exists():
            return

        skills_root = self.skills_dir.resolve()
        for manifest in sorted(self.skills_dir.glob("*/SKILL.md")):
            if (not manifest.is_file()
                    or not manifest.resolve().is_relative_to(skills_root)):
                continue
            content = manifest.read_text(encoding="utf-8")
            metadata, body = self.parse_frontmatter(content)

            raw_name = metadata.get("name")
            name = raw_name.strip() if isinstance(raw_name, str) else ""
            name = name or manifest.parent.name

            raw_description = metadata.get("description")
            description = raw_description.strip() if isinstance(raw_description, str) else ""
            description = description or body.split("\n", 1)[0]
            description = " ".join(str(description).lstrip("# ").split()) or "(no description)"

            self.skills[name] = {
                "name": name,
                "description": description,
                "content": content,
            }

    def catalog(self) -> str:
        """Layer 1：只输出名称与描述，注入 system prompt。"""
        if not self.skills:
            return "(no skills found)"
        return "\n".join(
            f"- {skill['name']}: {skill['description']}"
            for skill in self.skills.values()
        )

    def load(self, name: str) -> str:
        """Layer 2：按名称返回完整 SKILL.md；name 只查内存注册表，不当路径用。"""
        skill = self.skills.get(name)
        if skill:
            return skill["content"]
        available = ", ".join(self.skills) or "none"
        return f"Error: Unknown skill '{name}'. Available: {available}"


SKILL_LOADER = SkillLoader(SKILLS_DIR)


def run_load_skill(name: str) -> str:
    return SKILL_LOADER.load(name)
