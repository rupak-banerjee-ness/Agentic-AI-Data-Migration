"""
Abstract contract every dialect plugin (Oracle, MySQL, PostgreSQL) must implement.

A dialect is symmetric: the same class is used whether the engine is acting
as migration source or target (see architecture.md's `DialectPair`).

Each dialect must implement:
- Type mapping between native and canonical types
- DDL export/import commands
- SQL generation (identifier quoting, DDL syntax)
- Connection management
- Schema introspection queries
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class SQLObjectType(str, Enum):
    """Types of database objects."""
    TABLE = "table"
    VIEW = "view"
    INDEX = "index"
    PROCEDURE = "procedure"
    FUNCTION = "function"
    TRIGGER = "trigger"
    SEQUENCE = "sequence"
    PACKAGE = "package"
    CONSTRAINT = "constraint"


@dataclass
class SQLObject:
    """Represents a database object."""
    object_type: SQLObjectType
    name: str
    schema: str
    definition: Optional[str] = None
    dependencies: list[str] = None
    is_system: bool = False

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


@dataclass
class ColumnMetadata:
    """Metadata for a table column."""
    name: str
    native_type: str
    nullable: bool = True
    default_value: Optional[str] = None
    is_primary_key: bool = False
    comment: Optional[str] = None


@dataclass
class TableMetadata:
    """Metadata for a table."""
    name: str
    schema: str
    columns: list[ColumnMetadata]
    primary_key_columns: list[str]
    comment: Optional[str] = None
    row_count: Optional[int] = None


class Dialect(ABC):
    """
    Type map + SQL grammar hooks for a single database engine.
    
    Symmetric: the same class is used whether the engine is acting
    as migration source or target.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the dialect name (e.g., 'oracle', 'mysql', 'postgresql')."""
        raise NotImplementedError

    @property
    @abstractmethod
    def version(self) -> str:
        """Return the target/tested version of this dialect (e.g., '23c', '8.0', '14')."""
        raise NotImplementedError

    @abstractmethod
    def type_map(self) -> dict[str, str]:
        """
        Return the native-type -> canonical-type mapping for this dialect.
        
        Example:
            {
                'INTEGER': 'INT',
                'BIGINT': 'BIGINT',
                'VARCHAR': 'STRING',
                'CLOB': 'TEXT',
            }
        """
        raise NotImplementedError

    @abstractmethod
    def export_ddl_command(self, connection_config: dict[str, Any]) -> list[str]:
        """
        Return the native command used to export schema-only DDL.
        
        Example for PostgreSQL:
            ['pg_dump', '--schema-only', '--dbname=postgresql://...']
            
        Example for MySQL:
            ['mysqldump', '--no-data', '-h', 'host', '-u', 'user', '--password=...', 'database']
            
        Example for Oracle:
            ['sqlplus', '-S', 'user/pass@host:port/sid', '@', 'export.sql']
        """
        raise NotImplementedError

    @abstractmethod
    def quote_identifier(self, identifier: str) -> str:
        """
        Quote a table/column/object identifier per this dialect's grammar.
        
        Example:
            - PostgreSQL: 'my_table' -> '"my_table"'
            - MySQL: 'my_table' -> '`my_table`'
            - Oracle: 'my_table' -> '"MY_TABLE"'  (Oracle folds to uppercase)
        """
        raise NotImplementedError

    @abstractmethod
    def build_connection_string(self, config: dict[str, Any]) -> str:
        """
        Build a connection string from the config dictionary.
        
        Args:
            config: Dictionary with keys like 'host', 'port', 'username', 'password', 'database'.
            
        Returns:
            Connection string in the dialect's native format.
        """
        raise NotImplementedError

    @abstractmethod
    def get_tables_query(self, schema: Optional[str] = None) -> str:
        """
        Return a SQL query that lists all tables in the database (or schema).
        
        Returns a query that produces columns: [schema_name, table_name, row_count (optional)]
        """
        raise NotImplementedError

    @abstractmethod
    def get_views_query(self, schema: Optional[str] = None) -> str:
        """Return a SQL query that lists all views in the database (or schema)."""
        raise NotImplementedError

    @abstractmethod
    def get_procedures_query(self, schema: Optional[str] = None) -> str:
        """Return a SQL query that lists all stored procedures in the database (or schema)."""
        raise NotImplementedError

    @abstractmethod
    def get_functions_query(self, schema: Optional[str] = None) -> str:
        """Return a SQL query that lists all functions in the database (or schema)."""
        raise NotImplementedError

    @abstractmethod
    def get_triggers_query(self, schema: Optional[str] = None) -> str:
        """Return a SQL query that lists all triggers in the database (or schema)."""
        raise NotImplementedError

    @abstractmethod
    def get_table_definition(self, table_name: str, schema: str) -> str:
        """
        Get the CREATE TABLE statement for a table.
        
        Returns the full DDL definition.
        """
        raise NotImplementedError

    def get_object_dependencies(self, obj: SQLObject) -> list[str]:
        """
        Get a list of object names that this object depends on.
        
        Override in subclasses if the dialect supports dependency tracking.
        Default: empty list.
        """
        return []

    def is_system_object(self, obj: SQLObject) -> bool:
        """
        Determine if an object is a system/internal object that should be skipped.
        
        Override in subclasses to define system object patterns.
        Default: False.
        """
        return False
