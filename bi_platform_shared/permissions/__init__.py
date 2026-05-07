"""Shared DRF permission classes."""

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
