"""Compatibility package for migrated API modules."""

import sys

from apps.api.app import core_bridge, state

sys.modules[__name__ + ".core_bridge"] = core_bridge
sys.modules[__name__ + ".state"] = state

__all__ = ["core_bridge", "state"]
