"""Abstract contract every dialect plugin (Oracle, MySQL, PostgreSQL) must implement.

A dialect is symmetric: the same class is used whether the engine is acting
as migration source or target (see architecture.md's `DialectPair`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Dialect(ABC):
    """Type map + SQL grammar hooks for a single database engine."""

    name: str

    @abstractmethod
    def type_map(self) -> dict[str, str]:
        """Return the native-type -> canonical-type mapping for this dialect."""
        raise NotImplementedError

    @abstractmethod
    def export_ddl_command(self, connection_config: dict[str, Any]) -> list[str]:
        """Return the native command used to export schema-only DDL (e.g. pg_dump --schema-only)."""
        raise NotImplementedError

    @abstractmethod
    def quote_identifier(self, identifier: str) -> str:
        """Quote a table/column/object identifier per this dialect's grammar."""
        raise NotImplementedError
