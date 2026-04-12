"""Compatibility package for migrated API modules."""

import sys

from apps.api.app import core_bridge, routers, schemas, state

sys.modules[__name__ + ".core_bridge"] = core_bridge
sys.modules[__name__ + ".routers"] = routers
sys.modules[__name__ + ".schemas"] = schemas
sys.modules[__name__ + ".state"] = state

__all__ = ["core_bridge", "routers", "schemas", "state"]
