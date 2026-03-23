"""
core/services/__init__.py – Gemeinsame Typen für alle Services
"""

from dataclasses import dataclass


@dataclass
class ServiceResult:
    """Rückgabewert jeder Service-Operation."""
    success: bool
    message: str = ""
    data: object = None

    @classmethod
    def ok(cls, data=None, message: str = "") -> "ServiceResult":
        return cls(success=True, message=message, data=data)

    @classmethod
    def fail(cls, message: str) -> "ServiceResult":
        return cls(success=False, message=message)
