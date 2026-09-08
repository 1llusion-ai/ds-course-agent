from pathlib import Path

import pytest

from ds_course_agent.teaching.skill_system import Skill, SkillRegistry


def _write_skill(skill_dir: Path, *, name: str, description: str) -> Path:
    skill_dir.mkdir(parents=True)
    skill_doc = skill_dir / "SKILL.md"
    skill_doc.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return skill_doc


def test_skill_loader_discovers_claude_style_skills():
    loader = SkillRegistry()

    skills = {item.key for item in loader.list_skills()}

    assert "personalized-explanation" in skills
    assert "learning-path" in skills


def test_skill_loader_loads_executor_by_convention():
    loader = SkillRegistry()

    executor = loader.load_executor("learning-path")

    assert callable(executor)


def test_skill_loader_selects_candidates_from_frontmatter_keywords():
    loader = SkillRegistry()

    matches = loader.select_candidates("按我现在的情况，PCA先学什么、怎么复习比较好？")
    keys = [item.skill.key for item in matches]

    assert "learning-path" in keys
    assert keys[0] == "learning-path"


def test_skill_loader_blocks_conflicting_skill_with_avoid_keywords():
    loader = SkillRegistry()

    matches = loader.select_candidates("帮我做一个学习计划，先学什么比较合适？")
    keys = [item.skill.key for item in matches]

    assert "learning-path" in keys
    assert "personalized-explanation" not in keys


def test_skill_prompt_section_injects_inline_skill_bodies():
    loader = SkillRegistry()

    section = loader.build_skills_prompt_section()

    assert "# Available Teaching Skills" in section
    assert "## Skill catalog" in section
    assert "## Inline Skill Instructions" in section
    assert '<skill name="personalized-explanation"' in section
    assert "# Personalized Explanation Skill" in section
    assert '<skill name="learning-path"' in section
    assert "# Learning Path Skill" in section


def test_skill_registration_rejects_normalized_key_conflict(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path / "skills", user_dir=tmp_path / "user-skills")
    first = Skill(name="First Skill", key="data_science")
    second = Skill(name="Second Skill", key="data-science")

    registry.register_skill(first)

    with pytest.raises(ValueError, match="data-science"):
        registry.register_skill(second)

    assert registry.get_skill("DATA science") is first


def test_skill_discovery_rejects_normalized_key_conflict_without_partial_state(tmp_path):
    skills_dir = tmp_path / "skills"
    _write_skill(skills_dir / "first", name="data_science", description="first")
    _write_skill(skills_dir / "second", name="data-science", description="second")
    registry = SkillRegistry(base_dir=skills_dir, user_dir=tmp_path / "user-skills")

    with pytest.raises(ValueError, match="normalized key 'data-science'"):
        registry.list_skills()

    assert registry._skills == {}
    with pytest.raises(ValueError, match="normalized key 'data-science'"):
        registry.list_skills()


def test_skill_discovery_invalidates_after_manifest_and_directory_changes(tmp_path):
    skills_dir = tmp_path / "skills"
    first_doc = _write_skill(skills_dir / "first", name="first", description="old")
    registry = SkillRegistry(base_dir=skills_dir, user_dir=tmp_path / "user-skills")

    assert registry.get_skill("first").description == "old"

    first_doc.write_text(
        "---\nname: first\ndescription: new\n---\n\n# first\n",
        encoding="utf-8",
    )
    assert registry.get_skill("first").description == "new"

    _write_skill(skills_dir / "second", name="second", description="new")
    assert registry.get_skill("second").description == "new"

    first_doc.unlink()
    with pytest.raises(KeyError, match="first"):
        registry.get_skill("first")


def test_skill_discovery_invalidates_when_existing_directory_gains_manifest(tmp_path):
    skills_dir = tmp_path / "skills"
    dormant_dir = skills_dir / "dormant"
    dormant_dir.mkdir(parents=True)
    registry = SkillRegistry(base_dir=skills_dir, user_dir=tmp_path / "user-skills")

    assert registry.list_skills() == []

    skill_doc = dormant_dir / "SKILL.md"
    skill_doc.write_text(
        "---\nname: dormant\ndescription: newly active\n---\n\n# Dormant\n",
        encoding="utf-8",
    )

    assert registry.get_skill("dormant").description == "newly active"


def test_clear_source_invalidates_signature_and_rebuilds_discovery(tmp_path):
    skills_dir = tmp_path / "skills"
    _write_skill(skills_dir / "first", name="first", description="stable")
    registry = SkillRegistry(base_dir=skills_dir, user_dir=tmp_path / "user-skills")

    first = registry.get_skill("first")
    signature = registry._discovery_signature
    assert signature is not None

    registry.clear_skills(source="project")

    assert registry._discovery_roots == ()
    assert registry._tracked_paths == ()
    assert registry._manifest_paths == ()
    assert registry._discovery_signature is None

    rebuilt = registry.get_skill("first")
    assert rebuilt is not first
    assert registry._discovery_signature is not signature


def test_cached_skill_discovery_does_not_rescan_directories(monkeypatch, tmp_path):
    skills_dir = tmp_path / "skills"
    _write_skill(skills_dir / "first", name="first", description="stable")
    registry = SkillRegistry(base_dir=skills_dir, user_dir=tmp_path / "user-skills")
    assert registry.get_skill("first").description == "stable"

    original_iterdir = Path.iterdir
    scan_calls = 0

    def count_iterdir(path):
        nonlocal scan_calls
        scan_calls += 1
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", count_iterdir)
    assert registry.get_skill("first").description == "stable"
    assert scan_calls == 0
