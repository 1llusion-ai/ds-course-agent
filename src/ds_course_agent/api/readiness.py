"""Production readiness composition for the HTTP edge."""

from __future__ import annotations

import ds_course_agent.shared.config as config
from ds_course_agent.retrieval.index_manifest import check_production_index_readiness
from ds_course_agent.shared.config.production import check_production_settings
from ds_course_agent.shared.config.schema import Settings
from ds_course_agent.shared.readiness import ReadinessReport
from ds_course_agent.tools.code_executor import check_python_execution_readiness
from ds_course_agent.tools.web_search import check_web_search_readiness


def _runtime_settings() -> Settings:
    """Build a typed snapshot from the public config seam used by tests/deploys."""

    return Settings(
        APP_ENV=config.APP_ENV,
        AUTH_SECRET_KEY=config.AUTH_SECRET_KEY,
        AUTH_COOKIE_SECURE=config.AUTH_COOKIE_SECURE,
        CORS_ALLOW_ORIGINS=config.CORS_ALLOW_ORIGINS,
        CHROMA_PERSIST_DIR=config.CHROMA_PERSIST_DIR,
        RAG_INDEX_MANIFEST_PATH=config.RAG_INDEX_MANIFEST_PATH,
        COLLECTION_NAME=config.collection_name,
        COURSE_COLLECTION_NAME="",
        EMBEDDING_MODEL=config.MODEL_EMBEDDING,
    )


def build_readiness_report() -> ReadinessReport:
    """Run read-only production checks and return a typed aggregate."""

    settings = _runtime_settings()
    checks = list(check_production_settings(settings))
    if settings.APP_ENV == "production":
        checks.extend(
            (
                check_production_index_readiness(settings),
                check_python_execution_readiness(),
                check_web_search_readiness(),
            )
        )
    return ReadinessReport(tuple(checks))


__all__ = ["build_readiness_report"]
