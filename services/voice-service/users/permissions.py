"""
voice-service users.permissions
===============================

Per CRIT-20 the permission classes live in ``bi_platform_shared`` and are
re-exported from this module unchanged so existing imports keep working.
"""

from bi_platform_shared.permissions.roles import (
    IsAdmin,
    IsAnalyst,
    IsExecutive,
    IsManager,
    IsManagerOrAnalyst,
)

__all__ = [
    "IsAdmin",
    "IsAnalyst",
    "IsExecutive",
    "IsManager",
    "IsManagerOrAnalyst",
]
