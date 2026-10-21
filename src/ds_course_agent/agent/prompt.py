"""Render shared teaching instructions with explicit catalogue identity."""

from ds_course_agent.courses import CourseCatalog, CourseResourceManifest, ResolvedCourse
from ds_course_agent.courses.resources import DEFAULT_COURSE_ID
from ds_course_agent.shared.paths import PROJECT_ROOT
from ds_course_agent.teaching.skill_system import get_skill_registry

_PROMPT_DIR = PROJECT_ROOT / "docs" / "prompts"


def get_system_prompt(course: CourseResourceManifest | ResolvedCourse | None = None) -> str:
    """Render the shared template, then append only the selected course's resource.

    Omitted identity keeps the legacy default at service construction. A resolved
    failure stays neutral and cannot select default-course instructions.
    """
    if course is None:
        course = CourseCatalog.from_directory(PROJECT_ROOT / "data/courses").require(DEFAULT_COURSE_ID)
    manifest = course.manifest if isinstance(course, ResolvedCourse) else course
    name = manifest.display_name if manifest is not None else "当前课程"
    description = manifest.description if manifest is not None else "课程资源暂不可用，请勿推断其它课程内容。"
    path = _PROMPT_DIR / "base_system_prompt.txt"
    template = path.read_text(encoding="utf-8").strip() if path.exists() else _get_default_prompt()
    base = template.replace("{{course_name}}", name).replace("{{course_description}}", description)
    sections = [base]
    if manifest is not None and manifest.prompt_path:
        path = PROJECT_ROOT / manifest.prompt_path
        if path.is_file():
            sections.append(path.read_text(encoding="utf-8").strip())
    sections.append(get_skill_registry().build_skills_prompt_section().strip())
    return "\n\n".join(section for section in sections if section)


def _get_default_prompt() -> str:
    return (
        "你是“数字力”导学智能体，当前辅导《{{course_name}}》。\n"
        "课程说明：{{course_description}}\n"
        "帮助学生理解当前课程内容；资料不足时说明不确定性，遵守学术诚信和隐私边界。"
    )
