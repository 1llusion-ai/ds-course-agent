"""Single-file skill system for SKILL.md-based project skills.

This module keeps the current project simple:

- one `Skill` data model
- one `SkillRegistry`
- project/user discovery
- lightweight catalog for the system prompt
- executor-first execution with prompt fallback
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any, Callable, Optional

import yaml


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _normalize_skill_key(value: str) -> str:
    return re.sub(r"[-_\s]+", "-", (value or "").strip().lower())


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value).strip()]


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "on"}:
            return True
        if lowered in {"false", "no", "0", "off"}:
            return False
    return bool(value)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw = match.group(1)
    body = text[match.end():]
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        return {}, body
    return data, body


@dataclass
class Skill:
    """A single discovered skill manifest plus optional prompt body."""

    name: str
    key: str = ""
    description: str = ""
    when_to_use: str = ""
    user_invocable: bool = True
    disable_model_invocation: bool = False
    allowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    context: str = "inline"
    argument_hint: str = ""
    paths: list[str] = field(default_factory=list)
    source: str = "project"
    skill_root: str | None = None
    skill_doc: str | None = None
    executor_path: str = "scripts/executor.py"
    trigger_keywords: list[str] = field(default_factory=list)
    avoid_keywords: list[str] = field(default_factory=list)
    priority: int = 0
    _prompt_text: str = ""
    _prompt_fn: Callable[[str], str] | None = None

    def __post_init__(self) -> None:
        self.key = _normalize_skill_key(self.key or self.name)

    def get_prompt(self, args: str = "") -> str:
        """Return the prompt body with simple variable substitution."""
        if self._prompt_fn is not None:
            return self._prompt_fn(args)

        text = self._prompt_text
        text = text.replace("$ARGUMENTS", args)
        if self.skill_root:
            text = text.replace("${CLAUDE_SKILL_DIR}", self.skill_root)
        if args and self.argument_hint:
            text = text.replace(f"${{{self.argument_hint}}}", args)
        return text


@dataclass(frozen=True)
class SkillMatch:
    skill: Skill
    score: int
    matched_keywords: list[str]
    blocked_keywords: list[str]


def _skill_from_frontmatter(
    meta: dict[str, Any],
    body: str,
    name: str,
    source: str,
    skill_root: str | None = None,
    skill_doc: str | None = None,
) -> Skill:
    raw_priority = meta.get("priority", 0)
    try:
        priority = int(raw_priority)
    except Exception:
        priority = 0

    return Skill(
        name=str(meta.get("name") or name),
        description=str(meta.get("description") or ""),
        when_to_use=str(meta.get("when_to_use") or ""),
        user_invocable=_coerce_bool(meta.get("user_invocable"), default=True),
        disable_model_invocation=_coerce_bool(meta.get("disable_model_invocation"), default=False),
        allowed_tools=_coerce_list(meta.get("allowed_tools")),
        model=str(meta.get("model")) if meta.get("model") else None,
        context=str(meta.get("context") or "inline"),
        argument_hint=str(meta.get("arguments") or meta.get("argument_hint") or ""),
        paths=_coerce_list(meta.get("paths")),
        source=source,
        skill_root=skill_root,
        skill_doc=skill_doc,
        executor_path=str(meta.get("executor_path") or "scripts/executor.py"),
        trigger_keywords=_coerce_list(meta.get("trigger_keywords")),
        avoid_keywords=_coerce_list(meta.get("avoid_keywords")),
        priority=priority,
        _prompt_text=body.strip(),
    )


class SkillRegistry:
    """Discover, register, list, select, and execute skills."""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        user_dir: Optional[Path] = None,
    ) -> None:
        root = Path(__file__).resolve().parent.parent
        self.base_dir = Path(base_dir or (root / "skills"))
        self.project_cc_dir = root / ".cc-mini" / "skills"
        self.user_dir = Path(user_dir or (Path.home() / ".cc-mini" / "skills"))
        self._skills: dict[str, Skill] = {}
        self._module_cache: dict[tuple[str, str], ModuleType] = {}
        self._discovered = False

    def register_skill(self, skill: Skill) -> None:
        self._skills[skill.key] = skill

    def get_skill(self, name: str) -> Skill:
        self._ensure_discovered()
        key = _normalize_skill_key(name)
        if key not in self._skills:
            raise KeyError(f"Unknown skill: {name}")
        return self._skills[key]

    def list_skills(self, user_invocable_only: bool = False) -> list[Skill]:
        self._ensure_discovered()
        skills = list(self._skills.values())
        if user_invocable_only:
            skills = [skill for skill in skills if skill.user_invocable]
        return sorted(skills, key=lambda skill: (skill.source != "bundled", skill.name))

    def clear_skills(self, source: str | None = None) -> None:
        if source is None:
            self._skills.clear()
            self._module_cache.clear()
            self._discovered = False
            return

        keys = [key for key, skill in self._skills.items() if skill.source == source]
        for key in keys:
            self._skills.pop(key, None)

        stale_cache = [
            cache_key
            for cache_key in self._module_cache
            if cache_key[0] not in self._skills
        ]
        for cache_key in stale_cache:
            self._module_cache.pop(cache_key, None)

    def load_skills_from_dir(self, skills_dir: Path, source: str = "project") -> list[Skill]:
        loaded: list[Skill] = []
        if not skills_dir.is_dir():
            return loaded

        for entry in sorted(skills_dir.iterdir()):
            skill: Skill | None = None

            if entry.is_dir():
                skill_md = entry / "SKILL.md"
                if not skill_md.exists():
                    continue
                try:
                    text = skill_md.read_text(encoding="utf-8")
                except Exception:
                    continue
                meta, body = _parse_frontmatter(text)
                skill = _skill_from_frontmatter(
                    meta,
                    body,
                    name=entry.name,
                    source=source,
                    skill_root=str(entry),
                    skill_doc=str(skill_md),
                )
            elif entry.suffix == ".md" and entry.is_file():
                try:
                    text = entry.read_text(encoding="utf-8")
                except Exception:
                    continue
                meta, body = _parse_frontmatter(text)
                skill = _skill_from_frontmatter(
                    meta,
                    body,
                    name=entry.stem,
                    source=source,
                    skill_root=str(entry.parent),
                    skill_doc=str(entry),
                )

            if skill is None:
                continue

            self.register_skill(skill)
            loaded.append(skill)

        return loaded

    def discover_skills(self, cwd: str | None = None) -> list[Skill]:
        if self._discovered:
            return []

        loaded: list[Skill] = []
        if cwd:
            cwd_path = Path(cwd)
            project_skills_dir = cwd_path / "skills"
            project_cc_dir = cwd_path / ".cc-mini" / "skills"
        else:
            project_skills_dir = self.base_dir
            project_cc_dir = self.project_cc_dir

        loaded.extend(self.load_skills_from_dir(project_skills_dir, source="project"))
        loaded.extend(self.load_skills_from_dir(project_cc_dir, source="project"))
        loaded.extend(self.load_skills_from_dir(self.user_dir, source="user"))
        self._discovered = True
        return loaded

    def build_skills_prompt_section(self) -> str:
        skills = self.list_skills(user_invocable_only=False)
        if not skills:
            return ""

        lines = ["# Available Skills", ""]
        for skill in skills:
            line = f"- /{skill.name}: {skill.description or '(no description)'}"
            if skill.when_to_use:
                line += f" - {skill.when_to_use}"
            lines.append(line)
        return "\n".join(lines)

    def select_candidates(self, question: str, limit: int | None = None) -> list[SkillMatch]:
        self._ensure_discovered()
        normalized_question = _normalize_text(question)
        matches: list[SkillMatch] = []

        for skill in self._skills.values():
            matched_keywords = [
                keyword
                for keyword in skill.trigger_keywords
                if _normalize_text(keyword) and _normalize_text(keyword) in normalized_question
            ]
            blocked_keywords = [
                keyword
                for keyword in skill.avoid_keywords
                if _normalize_text(keyword) and _normalize_text(keyword) in normalized_question
            ]

            score = skill.priority
            score += len(matched_keywords) * 10
            score -= len(blocked_keywords) * 12

            if skill.description:
                desc_terms = [
                    term
                    for term in re.split(r"[,，、/\s]+", _normalize_text(skill.description))
                    if len(term) >= 2
                ]
                score += min(sum(1 for term in desc_terms[:8] if term in normalized_question), 2)

            if skill.when_to_use:
                usage_terms = [
                    term
                    for term in re.split(r"[,，、/\s]+", _normalize_text(skill.when_to_use))
                    if len(term) >= 2
                ]
                score += min(sum(1 for term in usage_terms[:8] if term in normalized_question), 2)

            if matched_keywords and score > 0:
                matches.append(
                    SkillMatch(
                        skill=skill,
                        score=score,
                        matched_keywords=matched_keywords,
                        blocked_keywords=blocked_keywords,
                    )
                )

        matches.sort(key=lambda item: (item.score, item.skill.priority), reverse=True)
        return matches[:limit] if limit is not None else matches

    def load_full_text(self, name: str, args: str = "") -> str:
        skill = self.get_skill(name)
        return f"<skill name=\"{skill.name}\">\n{skill.get_prompt(args)}\n</skill>"

    def load_module(self, name: str, script_relative_path: str | None = None) -> ModuleType:
        skill = self.get_skill(name)
        relative_path = script_relative_path or skill.executor_path
        cache_key = (skill.key, relative_path)
        if cache_key in self._module_cache:
            return self._module_cache[cache_key]

        if not skill.skill_root:
            raise FileNotFoundError(f"Skill '{name}' does not have a valid root directory")

        script_path = Path(skill.skill_root) / relative_path
        if not script_path.exists():
            raise FileNotFoundError(f"Skill script not found: {script_path}")

        module_name = f"rag_skill_{skill.key.replace('-', '_')}_{script_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load skill script: {script_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        self._module_cache[cache_key] = module
        return module

    def load_executor(self, name: str, attr: str = "execute") -> Callable:
        module = self.load_module(name)
        executor = getattr(module, attr, None)
        if not callable(executor):
            raise AttributeError(f"Skill '{name}' does not expose callable '{attr}'")
        return executor

    def execute_skill(self, name: str, *args, **kwargs):
        try:
            executor = self.load_executor(name)
        except FileNotFoundError:
            if args and isinstance(args[0], str):
                prompt_args = args[0]
            else:
                prompt_args = str(kwargs.get("arguments", ""))
            return self.load_full_text(name, prompt_args)
        return executor(*args, **kwargs)

    def _ensure_discovered(self) -> None:
        if not self._discovered:
            self.discover_skills()


_skill_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    global _skill_registry
    if _skill_registry is None:
        _skill_registry = SkillRegistry()
    return _skill_registry


def get_skill_loader() -> SkillRegistry:
    """Compatibility alias for older imports."""
    return get_skill_registry()
