"""个性化讲解 Skill

导出 PersonalizedExplanationSkill 类，保持与旧接口兼容。
"""
from .scripts.executor import PersonalizedExplanationSkill, explain

__all__ = ['PersonalizedExplanationSkill', 'explain']
