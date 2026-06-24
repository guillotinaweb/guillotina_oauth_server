import asyncio

import pytest

from guillotina_oauth_server.storage.pg.schema import (
    OAUTH_BASELINE_COLUMNS,
    OAUTH_BASELINE_DDL,
    OAUTH_SCHEMA_VERSION,
    OAUTH_TABLE_NAMES,
)
from guillotina_oauth_server.storage.pg.schema_ops import (
    SchemaStatus,
    bootstrap_legacy_schema,
    get_schema_status,
    install_oauth_baseline,
    set_oauth_schema_version,
    validate_legacy_schema,
)
from guillotina_oauth_server.tests.conftest import requires_pg


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fake connection for unit tests (no PG required)
# ---------------------------------------------------------------------------


class FakeConnection:
    def __init__(self, meta_exists=True, meta_version=OAUTH_SCHEMA_VERSION, existing_tables=None):
        self._meta_exists = meta_exists
        self._meta_version = meta_version
        self._existing_tables = existing_tables
        if self._existing_tables is None:
            self._existing_tables = set(OAUTH_TABLE_NAMES)
        self._executed = []
        self._fetchval_results = {}
        self._fetchrow_results = {}

    def _table_exists(self, table_name):
        return table_name in self._existing_tables

    async def fetchrow(self, query, *args):
        if "information_schema.tables" in query:
            if "oauth_schema_meta'" in query:
                return (self._meta_exists,)
            if "$1" in query:
                return (self._table_exists(args[0]),)
        if "SELECT version FROM oauth_schema_meta" in query:
            if self._meta_exists and self._meta_version is not None:
                return {"version": self._meta_version}
            return None
        key = (query.strip()[:80], tuple(args))
        if key in self._fetchrow_results:
            return self._fetchrow_results[key]
        return None

    async def fetchval(self, query, *args):
        if "pg_try_advisory_lock" in query:
            return True
        if "pg_advisory_unlock" in query:
            return True
        key = (query.strip()[:80], tuple(args))
        return self._fetchval_results.get(key)

    async def execute(self, query, *args):
        self._executed.append((query.strip()[:80], args))

    async def fetch(self, query, *args):
        return []


class FakeConnectionNoLock(FakeConnection):
    _lock_count = 0

    async def fetchval(self, query, *args):
        if "pg_try_advisory_lock" in query:
            self._lock_count += 1
            if self._lock_count == 1:
                return False
            return True
        if "pg_advisory_unlock" in query:
            return True
        return await super().fetchval(query, *args)


# ---------------------------------------------------------------------------
# Unit tests: SchemaStatus detection
# ---------------------------------------------------------------------------


async def test_get_schema_status_empty():
    conn = FakeConnection(meta_exists=False, existing_tables=set())
    status = await get_schema_status(conn)
    assert status == SchemaStatus.EMPTY


async def test_get_schema_status_versioned():
    conn = FakeConnection(meta_exists=True, meta_version=OAUTH_SCHEMA_VERSION)
    status = await get_schema_status(conn)
    assert status == SchemaStatus.VERSIONED


async def test_get_schema_status_needs_migration():
    conn = FakeConnection(meta_exists=True, meta_version=0)
    status = await get_schema_status(conn)
    assert status == SchemaStatus.NEEDS_MIGRATION


async def test_get_schema_status_code_too_old():
    conn = FakeConnection(meta_exists=True, meta_version=999)
    status = await get_schema_status(conn)
    assert status == SchemaStatus.CODE_TOO_OLD


async def test_get_schema_status_legacy():
    conn = FakeConnection(meta_exists=False)
    status = await get_schema_status(conn)
    assert status == SchemaStatus.LEGACY


async def test_get_schema_status_partial():
    conn = FakeConnection(meta_exists=False, existing_tables={"oauth_clients"})
    status = await get_schema_status(conn)
    assert status == SchemaStatus.PARTIAL


async def test_get_schema_status_partial_meta_null():
    conn = FakeConnection(meta_exists=True, meta_version=None)
    status = await get_schema_status(conn)
    assert status == SchemaStatus.PARTIAL


# ---------------------------------------------------------------------------
# Unit tests: validate_legacy_schema
# ---------------------------------------------------------------------------


class FakeInfoSchemaConnection(FakeConnection):
    async def fetch(self, query, *args):
        if "information_schema.columns" in query:
            table_name = args[0] if args else "oauth_clients"
            expected_cols = OAUTH_BASELINE_COLUMNS.get(table_name, {})
            return [{"column_name": k, "data_type": v} for k, v in expected_cols.items()]
        return []


async def test_validate_legacy_schema_compatible():
    conn = FakeInfoSchemaConnection()
    compatible, diffs = await validate_legacy_schema(conn)
    assert compatible is True
    assert len(diffs) == 0


class FakeInfoSchemaMismatchConnection(FakeConnection):
    async def fetch(self, query, *args):
        if "information_schema.columns" in query:
            table_name = args[0]
            if table_name == "oauth_clients":
                return [
                    {"column_name": "container_db_key", "data_type": "text"},
                    {"column_name": "client_id", "data_type": "integer"},
                ]
            return []
        return []


async def test_validate_legacy_schema_mismatch():
    conn = FakeInfoSchemaMismatchConnection()
    compatible, diffs = await validate_legacy_schema(conn)
    assert compatible is False
    assert len(diffs) > 0
    assert any("client_id" in d for d in diffs)


# ---------------------------------------------------------------------------
# Unit tests: set_oauth_schema_version
# ---------------------------------------------------------------------------


async def test_set_oauth_schema_version():
    conn = FakeConnection(meta_exists=True, meta_version=0)
    await set_oauth_schema_version(conn, 1)
    upsert_called = any("ON CONFLICT (id)" in q for q, _ in conn._executed)
    assert upsert_called


# ---------------------------------------------------------------------------
# Unit tests: install_oauth_baseline (with lock)
# ---------------------------------------------------------------------------


async def test_install_baseline_empty(monkeypatch):
    conn = FakeConnection(meta_exists=False, existing_tables=set())
    status = await install_oauth_baseline(conn)
    assert status == SchemaStatus.VERSIONED
    assert any("CREATE TABLE IF NOT EXISTS" in q for q, _ in conn._executed)
    assert any("COMMIT" in q for q, _ in conn._executed)


async def test_install_baseline_lock_retry(monkeypatch):
    conn = FakeConnectionNoLock(
        meta_exists=False,
        existing_tables=set(),
    )
    status = await install_oauth_baseline(conn)
    assert status == SchemaStatus.VERSIONED


async def test_install_baseline_already_versioned():
    conn = FakeConnection(meta_exists=True, meta_version=OAUTH_SCHEMA_VERSION)
    status = await install_oauth_baseline(conn)
    assert status == SchemaStatus.VERSIONED


# ---------------------------------------------------------------------------
# Unit tests: concurrent bootstrap
# ---------------------------------------------------------------------------


async def test_concurrent_bootstrap():
    class ConcurrentConnection(FakeConnection):
        def __init__(self, conn_id):
            super().__init__(meta_exists=False, existing_tables=set())
            self.conn_id = conn_id

        async def fetchval(self, query, *args):
            if "pg_try_advisory_lock" in query:
                return True
            return await super().fetchval(query, *args)

    conn1 = ConcurrentConnection(1)
    conn2 = ConcurrentConnection(2)

    async def bootstrap(conn):
        status = await install_oauth_baseline(conn)
        return conn.conn_id, status

    results = await asyncio.gather(bootstrap(conn1), bootstrap(conn2))
    assert all(r[1] == SchemaStatus.VERSIONED for r in results), results


# ---------------------------------------------------------------------------
# Integration tests (requires PostgreSQL)
# ---------------------------------------------------------------------------


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_bootstrap_fresh_install(guillotina_main):
    from guillotina.component import get_utility
    from guillotina.db.interfaces import IPostgresStorage
    from guillotina.interfaces import IApplication, IDatabase

    root = get_utility(IApplication, name="root")
    for _id, db in root:
        if not IDatabase.providedBy(db):
            continue
        tm = db.get_transaction_manager()
        if not IPostgresStorage.providedBy(tm.storage):
            continue

        async with tm.storage.pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS oauth_consents CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_refresh_tokens CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_authorization_codes CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_clients CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_migration_log CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_meta CASCADE")

        async with tm.storage.pool.acquire() as conn:
            status = await install_oauth_baseline(conn)
            assert status == SchemaStatus.VERSIONED

        async with tm.storage.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT version FROM oauth_schema_meta WHERE id = 1")
            assert row["version"] == OAUTH_SCHEMA_VERSION

            for table_name in OAUTH_TABLE_NAMES:
                row = await conn.fetchrow(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = $1)",
                    table_name,
                )
                assert row[0] is True, f"Table {table_name} should exist"

            meta_row = await conn.fetchrow(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'oauth_schema_meta')"
            )
            assert meta_row[0] is True

            log_row = await conn.fetchrow(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'oauth_schema_migration_log')"
            )
            assert log_row[0] is True


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_bootstrap_idempotent(guillotina_main):
    from guillotina.component import get_utility
    from guillotina.db.interfaces import IPostgresStorage
    from guillotina.interfaces import IApplication, IDatabase

    root = get_utility(IApplication, name="root")
    for _id, db in root:
        if not IDatabase.providedBy(db):
            continue
        tm = db.get_transaction_manager()
        if not IPostgresStorage.providedBy(tm.storage):
            continue

        async with tm.storage.pool.acquire() as conn:
            status = await install_oauth_baseline(conn)
            assert status == SchemaStatus.VERSIONED

        async with tm.storage.pool.acquire() as conn:
            status2 = await install_oauth_baseline(conn)
            assert status2 == SchemaStatus.VERSIONED


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_baseline_is_clean_no_alter_columns(guillotina_main):
    from guillotina.component import get_utility
    from guillotina.db.interfaces import IPostgresStorage
    from guillotina.interfaces import IApplication, IDatabase

    root = get_utility(IApplication, name="root")
    for _id, db in root:
        if not IDatabase.providedBy(db):
            continue
        tm = db.get_transaction_manager()
        if not IPostgresStorage.providedBy(tm.storage):
            continue

        async with tm.storage.pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS oauth_consents CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_refresh_tokens CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_authorization_codes CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_clients CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_migration_log CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_meta CASCADE")

        async with tm.storage.pool.acquire() as conn:
            await install_oauth_baseline(conn)

        async with tm.storage.pool.acquire() as conn:
            for table_name, expected_cols in OAUTH_BASELINE_COLUMNS.items():
                rows = await conn.fetch(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = $1 AND table_schema = 'public' "
                    "ORDER BY ordinal_position",
                    table_name,
                )
                actual = {r["column_name"]: r["data_type"] for r in rows}
                for col, exp_type in expected_cols.items():
                    assert col in actual, f"{table_name}.{col} missing"
                    assert actual[col] == exp_type, f"{table_name}.{col} type {actual[col]} != {exp_type}"


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_legacy_detection_and_bootstrap(guillotina_main):
    from guillotina.component import get_utility
    from guillotina.db.interfaces import IPostgresStorage
    from guillotina.interfaces import IApplication, IDatabase

    root = get_utility(IApplication, name="root")
    for _id, db in root:
        if not IDatabase.providedBy(db):
            continue
        tm = db.get_transaction_manager()
        if not IPostgresStorage.providedBy(tm.storage):
            continue

        async with tm.storage.pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS oauth_consents CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_refresh_tokens CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_authorization_codes CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_clients CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_migration_log CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_meta CASCADE")

            # Create data tables without meta tables (simulates legacy setup)
            meta_ddl = {"oauth_schema_meta", "oauth_schema_migration_log"}
            data_ddl = [d for d in OAUTH_BASELINE_DDL if not any(marker in d for marker in meta_ddl)]
            for ddl in data_ddl:
                await conn.execute(ddl)

        async with tm.storage.pool.acquire() as conn:
            status = await get_schema_status(conn)
            assert status == SchemaStatus.LEGACY

        async with tm.storage.pool.acquire() as conn:
            compatible, diffs = await validate_legacy_schema(conn)
            assert compatible is True
            assert len(diffs) == 0

        async with tm.storage.pool.acquire() as conn:
            await bootstrap_legacy_schema(conn)

        async with tm.storage.pool.acquire() as conn:
            status = await get_schema_status(conn)
            assert status == SchemaStatus.VERSIONED


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_get_schema_status_on_real_pg(guillotina_main):
    from guillotina.component import get_utility
    from guillotina.db.interfaces import IPostgresStorage
    from guillotina.interfaces import IApplication, IDatabase

    root = get_utility(IApplication, name="root")
    for _id, db in root:
        if not IDatabase.providedBy(db):
            continue
        tm = db.get_transaction_manager()
        if not IPostgresStorage.providedBy(tm.storage):
            continue

        async with tm.storage.pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS oauth_consents CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_refresh_tokens CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_authorization_codes CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_clients CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_migration_log CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_meta CASCADE")

            status = await get_schema_status(conn)
            assert status == SchemaStatus.EMPTY

            await install_oauth_baseline(conn)
            status = await get_schema_status(conn)
            assert status == SchemaStatus.VERSIONED


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_ensure_oauth_schema_empty_to_versioned(guillotina_main):
    from guillotina.component import get_utility
    from guillotina.db.interfaces import IPostgresStorage
    from guillotina.interfaces import IApplication, IDatabase

    root = get_utility(IApplication, name="root")
    for _id, db in root:
        if not IDatabase.providedBy(db):
            continue
        tm = db.get_transaction_manager()
        if not IPostgresStorage.providedBy(tm.storage):
            continue

        async with tm.storage.pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS oauth_consents CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_refresh_tokens CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_authorization_codes CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_clients CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_migration_log CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_meta CASCADE")

        from guillotina_oauth_server.storage import utility

        utility._ddl_initialized.clear()

        status = await utility.ensure_oauth_schema(tm.storage)
        assert status == SchemaStatus.VERSIONED
        assert id(tm.storage.pool) in utility._ddl_initialized


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_schema_strict_true_blocks_legacy(guillotina_main):
    from guillotina.component import get_utility
    from guillotina.db.interfaces import IPostgresStorage
    from guillotina.interfaces import IApplication, IDatabase

    root = get_utility(IApplication, name="root")
    for _id, db in root:
        if not IDatabase.providedBy(db):
            continue
        tm = db.get_transaction_manager()
        if not IPostgresStorage.providedBy(tm.storage):
            continue

        async with tm.storage.pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS oauth_consents CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_refresh_tokens CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_authorization_codes CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_clients CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_migration_log CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_meta CASCADE")

            # Create data tables without meta tables (simulates legacy for strict test)
            meta_ddl = {"oauth_schema_meta", "oauth_schema_migration_log"}
            data_ddl = [d for d in OAUTH_BASELINE_DDL if not any(marker in d for marker in meta_ddl)]
            for ddl in data_ddl:
                await conn.execute(ddl)

        from guillotina import app_settings

        from guillotina_oauth_server.storage import utility

        utility._ddl_initialized.clear()
        app_settings["oauth"]["schema_strict"] = True

        try:
            with pytest.raises(RuntimeError, match="legacy"):
                await utility.ensure_oauth_schema(tm.storage)
        finally:
            app_settings["oauth"]["schema_strict"] = False


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_code_too_old_always_blocks(guillotina_main):
    from guillotina.component import get_utility
    from guillotina.db.interfaces import IPostgresStorage
    from guillotina.interfaces import IApplication, IDatabase

    root = get_utility(IApplication, name="root")
    for _id, db in root:
        if not IDatabase.providedBy(db):
            continue
        tm = db.get_transaction_manager()
        if not IPostgresStorage.providedBy(tm.storage):
            continue

        async with tm.storage.pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS oauth_consents CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_refresh_tokens CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_authorization_codes CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_clients CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_migration_log CASCADE")
            await conn.execute("DROP TABLE IF EXISTS oauth_schema_meta CASCADE")
            await install_oauth_baseline(conn)
            await conn.execute("UPDATE oauth_schema_meta SET version = 999 WHERE id = 1")

        from guillotina_oauth_server.storage import utility

        utility._ddl_initialized.clear()

        with pytest.raises(RuntimeError, match="newer than code version"):
            await utility.ensure_oauth_schema(tm.storage)
