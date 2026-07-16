from ds_course_agent.rag.skill_system import SkillRegistry


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
