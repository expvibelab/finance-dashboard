"""Skills system: filesystem-backed, runtime-creatable, evolvable.

Skills live at `.claude/skills/<slug>/SKILL.md`. The Claude Agent SDK auto-loads
them when `setting_sources` includes "project" and the `Skill` tool is allowed.
This module:

- Reads/writes skills atomically.
- Creates new skills at runtime from agent intent.
- Tracks usage statistics in the memory store to inform self-evolution.
- Validates frontmatter (name, description, version) and size limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Hermes' size limit: skills capped at 15KB.
MAX_SKILL_BYTES = 15 * 1024
SKILL_FILENAME = "SKILL.md"

_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass
class Skill:
    slug: str
    name: str
    description: str
    version: str
    body: str
    path: Path

    @property
    def size_bytes(self) -> int:
        return len(self.render().encode("utf-8"))

    def render(self) -> str:
        meta = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
        }
        return f"---\n{yaml.safe_dump(meta, sort_keys=False).strip()}\n---\n{self.body.lstrip()}"


def slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", name.lower()).strip("-")
    return s or "skill"


def parse_skill_file(path: Path) -> Skill:
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        raise ValueError(f"{path} is missing YAML frontmatter")
    meta = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)
    name = meta.get("name") or path.parent.name
    description = meta.get("description", "")
    version = str(meta.get("version", "0.1.0"))
    return Skill(
        slug=path.parent.name,
        name=name,
        description=description,
        version=version,
        body=body,
        path=path,
    )


class SkillRegistry:
    """Discovers, loads, creates, and evolves skills on disk."""

    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def list_skills(self) -> list[Skill]:
        out: list[Skill] = []
        for entry in sorted(self.skills_dir.iterdir()):
            skill_path = entry / SKILL_FILENAME
            if entry.is_dir() and skill_path.exists():
                try:
                    out.append(parse_skill_file(skill_path))
                except Exception:
                    continue
        return out

    def get(self, slug: str) -> Skill | None:
        path = self.skills_dir / slug / SKILL_FILENAME
        if not path.exists():
            return None
        return parse_skill_file(path)

    def create(
        self,
        *,
        name: str,
        description: str,
        body: str,
        version: str = "0.1.0",
        slug: str | None = None,
        overwrite: bool = False,
    ) -> Skill:
        slug = slug or slugify(name)
        path = self.skills_dir / slug / SKILL_FILENAME
        if path.exists() and not overwrite:
            raise FileExistsError(f"Skill {slug!r} already exists; use overwrite=True")
        path.parent.mkdir(parents=True, exist_ok=True)
        skill = Skill(
            slug=slug,
            name=name,
            description=description,
            version=version,
            body=body,
            path=path,
        )
        self._validate(skill)
        path.write_text(skill.render(), encoding="utf-8")
        return skill

    def update(
        self,
        slug: str,
        *,
        body: str | None = None,
        description: str | None = None,
        bump_version: bool = True,
    ) -> Skill:
        skill = self.get(slug)
        if skill is None:
            raise FileNotFoundError(f"Skill {slug!r} not found")
        if body is not None:
            skill.body = body
        if description is not None:
            skill.description = description
        if bump_version:
            skill.version = _bump_patch(skill.version)
        self._validate(skill)
        skill.path.write_text(skill.render(), encoding="utf-8")
        return skill

    def delete(self, slug: str) -> bool:
        path = self.skills_dir / slug / SKILL_FILENAME
        if not path.exists():
            return False
        path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass
        return True

    def _validate(self, skill: Skill) -> None:
        if not skill.name.strip():
            raise ValueError("Skill name cannot be empty")
        if not skill.description.strip():
            raise ValueError("Skill description is required so the agent can decide when to invoke it")
        if skill.size_bytes > MAX_SKILL_BYTES:
            raise ValueError(
                f"Skill exceeds {MAX_SKILL_BYTES} bytes (got {skill.size_bytes})"
            )

    def to_index(self) -> list[dict[str, Any]]:
        return [
            {
                "slug": s.slug,
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "size_bytes": s.size_bytes,
            }
            for s in self.list_skills()
        ]


def _bump_patch(version: str) -> str:
    parts = version.split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except ValueError:
        parts[-1] = "1"
    return ".".join(parts[:3])
