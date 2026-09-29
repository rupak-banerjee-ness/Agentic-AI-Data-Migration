"""Schema Extractor Adapter: driver-based schema introspection -> object catalog + FK dependency graph.

Uses each dialect's SQL-query methods (dialects/base.py) executed over the
matching DB-API driver connection. Deliberately avoids shelling out to native
dump tools (pg_dump/mysqldump/sqlplus) -- those aren't guaranteed to be
installed on the host running the platform, and would require passing DB
credentials via process argv.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from dialects import get_dialect
from dialects.base import Dialect
from tool_adapters.base import (
    AdapterConfig,
    AdapterType,
    BaseToolAdapter,
    ExecutionState,
    RollbackResult,
    ToolResult,
)
from tool_adapters.base import JobStatus as AdapterJobStatus


def _connect(dialect_name: str, connection_config: dict[str, Any]):
    if dialect_name == "postgresql":
        import psycopg2

        return psycopg2.connect(
            host=connection_config.get("host", "localhost"),
            port=connection_config.get("port", 5432),
            user=connection_config.get("username", "postgres"),
            password=connection_config.get("password", ""),
            dbname=connection_config.get("database", "postgres"),
        )
    if dialect_name == "mysql":
        import mysql.connector

        return mysql.connector.connect(
            host=connection_config.get("host", "localhost"),
            port=connection_config.get("port", 3306),
            user=connection_config.get("username", "root"),
            password=connection_config.get("password", ""),
            database=connection_config.get("database", ""),
        )
    if dialect_name == "oracle":
        import oracledb

        dsn = oracledb.makedsn(
            connection_config.get("host", "localhost"),
            connection_config.get("port", 1521),
            service_name=connection_config.get("database", "XE"),
        )
        conn = oracledb.connect(
            user=connection_config.get("username", "sample_user"),
            password=connection_config.get("password", ""),
            dsn=dsn,
        )
        # DBMS_METADATA.GET_DDL defaults to emitting full STORAGE/segment
        # clauses, which is measurably slow (multiple seconds) for tables
        # with LOB columns; suppressing them also yields cleaner DDL text.
        cursor = conn.cursor()
        cursor.execute(
            """
            BEGIN
                DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'STORAGE', FALSE);
                DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'SEGMENT_ATTRIBUTES', FALSE);
            END;
            """
        )
        cursor.close()
        return conn
    raise ValueError(f"Unsupported dialect: {dialect_name!r}")


def _default_namespace(dialect_name: str, connection_config: dict[str, Any]) -> str:
    """The namespace to discover: schema (Postgres), database (MySQL), or owner (Oracle)."""
    if dialect_name == "postgresql":
        return connection_config.get("schema_name") or "public"
    if dialect_name == "mysql":
        return connection_config.get("database", "")
    if dialect_name == "oracle":
        return connection_config.get("username", "")
    raise ValueError(f"Unsupported dialect: {dialect_name!r}")


class SchemaExtractorAdapter(BaseToolAdapter):
    """Runs discovery queries against a live connection to build the object catalog."""

    @property
    def adapter_type(self) -> AdapterType:
        return AdapterType.SCHEMA_EXTRACTOR

    @property
    def name(self) -> str:
        return "schema_extractor_adapter"

    def prepare(self, config: dict[str, Any]) -> AdapterConfig:
        if "dialect" not in config or "connection" not in config:
            raise ValueError("schema_extractor_adapter requires 'dialect' and 'connection' keys")
        return AdapterConfig(options=config)

    def run(self, config: AdapterConfig) -> ToolResult:
        start = time.monotonic()
        dialect_name: str = config.options["dialect"]
        connection_config: dict[str, Any] = config.options["connection"]
        dialect = get_dialect(dialect_name)
        namespace = _default_namespace(dialect_name, connection_config)

        conn = _connect(dialect_name, connection_config)
        try:
            catalog = self._build_catalog(dialect, namespace, conn)
            dependency_graph = self._build_dependency_graph(dialect, namespace, conn)
        finally:
            conn.close()

        return ToolResult(
            success=True,
            output={"object_catalog": catalog, "dependency_graph": dependency_graph},
            execution_time_seconds=time.monotonic() - start,
        )

    def status(self, job_id: str) -> AdapterJobStatus:
        # Discovery runs synchronously within run(); nothing long-running to poll.
        return AdapterJobStatus(job_id=job_id, state=ExecutionState.SUCCESS, progress_percent=100)

    def rollback(self, job_id: str) -> RollbackResult:
        # Read-only operation: nothing to undo.
        return RollbackResult(success=True, detail={"note": "schema discovery is read-only"})

    def _build_catalog(self, dialect: Dialect, namespace: str, conn: Any) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        object_queries = {
            "table": dialect.get_tables_query(namespace),
            "view": dialect.get_views_query(namespace),
            "procedure": dialect.get_procedures_query(namespace),
            "function": dialect.get_functions_query(namespace),
            "trigger": dialect.get_triggers_query(namespace),
        }
        for object_type, query in object_queries.items():
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            cursor.close()
            for row in rows:
                # Triggers queries return a 3rd column (owning table_name); other
                # object types only return (schema, name).
                owner, obj_name = row[0], row[1]
                table_name = row[2] if object_type == "trigger" and len(row) > 2 else None
                entry: dict[str, Any] = {
                    "object_type": object_type,
                    "name": obj_name,
                    "schema": owner,
                    "definition": None,
                }
                if object_type == "table":
                    entry["columns"] = self._fetch_columns(dialect, namespace, obj_name, conn)
                entry["definition"] = self._fetch_definition(
                    dialect, object_type, owner, obj_name, table_name, conn
                )
                catalog.append(entry)
        return catalog

    def _fetch_columns(
        self, dialect: Dialect, namespace: str, table_name: str, conn: Any
    ) -> list[dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute(dialect.get_columns_query(table_name, namespace))
        columns = [
            {
                "name": row[0],
                "native_type": row[1],
                "nullable": bool(row[2]),
                "default_value": row[3],
                "is_primary_key": bool(row[4]),
            }
            for row in cursor.fetchall()
        ]
        cursor.close()
        return columns

    # MySQL's SHOW CREATE * statements return several trailing metadata columns
    # (character_set_client, collation_connection, ...) after the DDL column,
    # so (unlike Oracle/Postgres single-column results) the DDL text isn't
    # reliably the *last* column -- look it up by name instead.
    _MYSQL_DDL_COLUMN = {
        "table": "Create Table",
        "view": "Create View",
        "procedure": "Create Procedure",
        "function": "Create Function",
        "trigger": "SQL Original Statement",
    }

    def _fetch_definition(
        self,
        dialect: Dialect,
        object_type: str,
        owner: str,
        obj_name: str,
        table_name: Optional[str],
        conn: Any,
    ) -> Optional[str]:
        query_builders = {
            "table": lambda: dialect.get_table_definition(obj_name, owner),
            "view": lambda: dialect.get_view_definition(obj_name, owner),
            "procedure": lambda: dialect.get_procedure_definition(obj_name, owner),
            "function": lambda: dialect.get_function_definition(obj_name, owner),
            "trigger": lambda: dialect.get_trigger_definition(obj_name, owner, table_name),
        }
        try:
            query = query_builders[object_type]()
            if dialect.name == "mysql":
                cursor = conn.cursor(dictionary=True)
                cursor.execute(query)
                row = cursor.fetchone()
                cursor.close()
                if row is None:
                    return None
                ddl = row.get(self._MYSQL_DDL_COLUMN[object_type])
            else:
                cursor = conn.cursor()
                cursor.execute(query)
                row = cursor.fetchone()
                cursor.close()
                if row is None:
                    return None
                ddl = row[-1]
            if hasattr(ddl, "read"):
                ddl = ddl.read()
            return str(ddl) if ddl is not None else None
        except Exception:
            return None  # DDL text is best-effort/for-display only; never fail discovery over it.

    def _build_dependency_graph(
        self, dialect: Dialect, namespace: str, conn: Any
    ) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {}
        cursor = conn.cursor()
        cursor.execute(dialect.get_foreign_keys_query(namespace))
        for row in cursor.fetchall():
            _constraint_name, table_name, _column_name, ref_table_name, _ref_column_name = row
            graph.setdefault(table_name, [])
            if ref_table_name not in graph[table_name]:
                graph[table_name].append(ref_table_name)
        cursor.close()
        return graph
