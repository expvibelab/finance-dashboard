"""Smoke tests for the skill registry."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from aether.skills import SkillRegistry, MAX_SKILL_BYTES


def test_create_and_list():
    with tempfile.TemporaryDirectory() as tmp:
        reg = SkillRegistry(Path(tmp))
        skill = reg.create(
            name="Foo Skill",
            description="Use when foo",
            body="# Foo\n\nDo the foo thing.",
        )
        assert skill.slug == "foo-skill"
        assert (Path(tmp) / "foo-skill" / "SKILL.md").exists()
        items = reg.list_skills()
        assert len(items) == 1
        assert items[0].name == "Foo Skill"


def test_update_bumps_version():
    with tempfile.TemporaryDirectory() as tmp:
        reg = SkillRegistry(Path(tmp))
        reg.create(name="A", description="d", body="x", version="0.1.0")
        s = reg.update("a", body="y")
        assert s.version == "0.1.1"


def test_size_limit():
    with tempfile.TemporaryDirectory() as tmp:
        reg = SkillRegistry(Path(tmp))
        with pytest.raises(ValueError):
            reg.create(
                name="Big",
                description="d",
                body="x" * (MAX_SKILL_BYTES + 1),
            )


def test_empty_description_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        reg = SkillRegistry(Path(tmp))
        with pytest.raises(ValueError):
            reg.create(name="A", description=" ", body="x")
