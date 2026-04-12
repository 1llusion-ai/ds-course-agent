"""Compatibility router package for migrated API routes."""

import sys

from apps.api.app.routers import chat, profile, sessions

sys.modules[__name__ + ".chat"] = chat
sys.modules[__name__ + ".profile"] = profile
sys.modules[__name__ + ".sessions"] = sessions

__all__ = ["chat", "profile", "sessions"]
