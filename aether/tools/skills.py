"""Skill tools: agent creates, edits, lists, and deletes its own skills."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from aether.skills import SkillRegistry


def build_skill_tools(registry: SkillRegistry):
    @tool(
        "create_skill",
        "Create a new persistent skill on disk. Use when you've solved a class of "
        "problems and want to capture the procedure so you can apply it next time. "
        "The body is a markdown instruction set written for your future self. "
        "`description` must say WHEN to use the skill so it auto-loads at the right moment.",
        {
            "name": str,
            "description": str,
            "body": str,
            "slug": str,
            "overwrite": bool,
        },
    )
    async def create_skill(args: dict[str, Any]) -> dict[str, Any]:
        try:
            skill = registry.create(
                name=args["name"],
                description=args["description"],
                body=args["body"],
                slug=(args.get("slug") or None),
                overwrite=bool(args.get("overwrite", False)),
            )
        except (FileExistsError, ValueError) as e:
            return _err(str(e))
        return _ok(
            f"Created skill `{skill.slug}` v{skill.version} ({skill.size_bytes} bytes)."
        )

    @tool(
        "edit_skill",
        "Edit an existing skill. Use when you discover a better approach or want to fix "
        "a problem you encountered while applying a skill. Bumps the patch version.",
        {"slug": str, "body": str, "description": str},
    )
    async def edit_skill(args: dict[str, Any]) -> dict[str, Any]:
        try:
            skill = registry.update(
                args["slug"],
                body=args.get("body"),
                description=args.get("description"),
            )
        except (FileNotFoundError, ValueError) as e:
            return _err(str(e))
        return _ok(f"Updated skill `{skill.slug}` → v{skill.version}.")

    @tool(
        "list_skills",
        "List every skill currently installed, with descriptions and versions.",
        {},
    )
    async def list_skills(_: dict[str, Any]) -> dict[str, Any]:
        skills = registry.list_skills()
        if not skills:
            return _ok("(no skills installed)")
        lines = [
            f"- **{s.slug}** v{s.version} — {s.description}" for s in skills
        ]
        return _ok("\n".join(lines))

    @tool(
        "delete_skill",
        "Permanently remove a skill. Use sparingly — prefer editing.",
        {"slug": str},
    )
    async def delete_skill(args: dict[str, Any]) -> dict[str, Any]:
        ok = registry.delete(args["slug"])
        return _ok(f"Removed `{args['slug']}`.") if ok else _err("Not found.")

    return [create_skill, edit_skill, list_skills, delete_skill]


def _ok(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}]}


def _err(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}
