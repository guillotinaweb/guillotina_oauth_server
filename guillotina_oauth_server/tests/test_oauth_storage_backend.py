import asyncio
from datetime import timezone

import pytest
from guillotina import task_vars

from guillotina_oauth_server.storage.access import get_oauth_store, oauth_container_db_key
from guillotina_oauth_server.storage.interfaces import IOAuthStore
from guillotina_oauth_server.storage.pg.repository import PostgresOAuthStore, _parse_dt
from guillotina_oauth_server.storage.pg.schema import OAUTH_BASELINE_DDL


def assert_oauth_store(store):
    assert IOAuthStore.providedBy(store)
    for name in IOAuthStore.names():
        assert asyncio.iscoroutinefunction(getattr(store, name)), name


def test_oauth_repository_implements_interface():
    store = PostgresOAuthStore("db/guillotina")
    assert_oauth_store(store)


def test_oauth_container_db_key_includes_database_id():
    db = type("DB", (), {"id": "db"})()
    container = type("Container", (), {"id": "guillotina"})()
    token = task_vars.db.set(db)
    try:
        assert oauth_container_db_key(container) == "db/guillotina"
    finally:
        task_vars.db.reset(token)


def test_oauth_schema_uses_container_db_key():
    ddl = "\n".join(OAUTH_BASELINE_DDL)
    assert "container_db_key text NOT NULL" in ddl
    assert "container_id text NOT NULL" not in ddl


def test_oauth_schema_avoids_postgresql_specific_cleanup_function():
    ddl = "\n".join(OAUTH_BASELINE_DDL).lower()
    assert "create or replace function oauth_cleanup_expired" not in ddl
    assert "ctid" not in ddl


def test_get_oauth_store_without_pg_raises():
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        get_oauth_store(type("Container", (), {"id": "guillotina"})(), require_installed=False)


def test_oauth_repository_parses_naive_datetimes_as_utc():
    parsed = _parse_dt("2026-01-01T00:00:00")
    assert parsed.tzinfo == timezone.utc
