"""
report-service users.permissions
================================

Per CRIT-20 the permission classes are now defined once in
``bi_platform_shared.permissions.roles`` and re-exported from every service.
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
