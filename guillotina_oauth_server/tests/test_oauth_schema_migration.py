import pytest

from guillotina_oauth_server.storage.pg.schema import (
    OAUTH_BASELINE_COLUMNS,
    OAUTH_BASELINE_DDL,
    OAUTH_SCHEMA_VERSION,
    OAUTH_TABLE_NAMES,
)
from guillotina_oauth_server.storage.pg.schema_ops import (
    SchemaStatus,
    get_schema_status,
    install_oauth_baseline,
    mark_existing_schema_as_v1,
    run_oauth_migrations,
    set_oauth_schema_version,
    validate_unversioned_baseline,
)
from guillotina_oauth_server.tests.conftest import requires_pg


pytestmark = pytest.mark.asyncio


class FakeConnection:
    def __init__(self, meta_exists=True, meta_version=OAUTH_SCHEMA_VERSION, existing_tables=None):
        self._meta_exists = meta_exists
        self._meta_version = meta_version
        self._existing_tables = set(OAUTH_TABLE_NAMES) if existing_tables is None else existing_tables
        self._executed = []

    async def fetchrow(self, query, *args):
        if "information_schema.tables" in query:
            if "oauth_schema_meta'" in query:
                return (self._meta_exists,)
            return (args[0] in self._existing_tables,)
        if "SELECT version FROM oauth_schema_meta" in query:
            if self._meta_exists and self._meta_version is not None:
                return {"version": self._meta_version}
            return None
        return None

    async def fetchval(self, query, *args):
        if "pg_try_advisory_lock" in query:
            return True
        if "pg_advisory_unlock" in query:
            return True
        return None

    async def execute(self, query, *args):
        self._executed.append((query.strip()[:100], args))

    async def fetch(self, query, *args):
        return []


class FakeConnectionNoLock(FakeConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock_count = 0

    async def fetchval(self, query, *args):
        if "pg_try_advisory_lock" in query:
            self._lock_count += 1
            return self._lock_count > 1
        return await super().fetchval(query, *args)


class FakeInfoSchemaConnection(FakeConnection):
    async def fetch(self, query, *args):
        if "information_schema.columns" in query:
            return [
                {"column_name": name, "data_type": data_type}
                for name, data_type in OAUTH_BASELINE_COLUMNS[args[0]].items()
            ]
        return []


class FakeInfoSchemaMismatchConnection(FakeConnection):
    async def fetch(self, query, *args):
        if "information_schema.columns" in query:
            if args[0] == "oauth_clients":
                return [
                    {"column_name": "container_db_key", "data_type": "text"},
                    {"column_name": "client_id", "data_type": "integer"},
                ]
            return []
        return []


@pytest.mark.parametrize(
    "conn, expected",
    [
        (FakeConnection(meta_exists=False, existing_tables=set()), SchemaStatus.EMPTY),
        (FakeConnection(meta_exists=True, meta_version=OAUTH_SCHEMA_VERSION), SchemaStatus.VERSIONED),
        (FakeConnection(meta_exists=True, meta_version=0), SchemaStatus.NEEDS_MIGRATION),
        (FakeConnection(meta_exists=True, meta_version=999), SchemaStatus.CODE_TOO_OLD),
        (FakeConnection(meta_exists=False), SchemaStatus.UNVERSIONED),
        (FakeConnection(meta_exists=False, existing_tables={"oauth_clients"}), SchemaStatus.PARTIAL),
        (FakeConnection(meta_exists=True, existing_tables={"oauth_clients"}), SchemaStatus.PARTIAL),
        (FakeConnection(meta_exists=True, meta_version=None), SchemaStatus.PARTIAL),
    ],
)
async def test_get_schema_status(conn, expected):
    assert await get_schema_status(conn) == expected


async def test_validate_unversioned_baseline_accepts_current_v1_shape():
    compatible, diffs = await validate_unversioned_baseline(FakeInfoSchemaConnection())

    assert compatible is True
    assert diffs == []


async def test_validate_unversioned_baseline_rejects_missing_or_changed_columns():
    compatible, diffs = await validate_unversioned_baseline(FakeInfoSchemaMismatchConnection())

    assert compatible is False
    assert any("client_id" in diff for diff in diffs)


async def test_set_oauth_schema_version_uses_upsert():
    conn = FakeConnection(meta_exists=True, meta_version=0)

    await set_oauth_schema_version(conn, 1)

    assert any("ON CONFLICT (id)" in query for query, _args in conn._executed)


async def test_install_oauth_baseline_creates_schema_transactionally():
    conn = FakeConnection(meta_exists=False, existing_tables=set())

    status = await install_oauth_baseline(conn)

    assert status == SchemaStatus.VERSIONED
    assert any("CREATE TABLE IF NOT EXISTS" in query for query, _args in conn._executed)
    assert any("INSERT INTO oauth_schema_meta" in query for query, _args in conn._executed)
    assert any(query == "COMMIT" for query, _args in conn._executed)


async def test_install_oauth_baseline_waits_for_advisory_lock():
    status = await install_oauth_baseline(FakeConnectionNoLock(meta_exists=False, existing_tables=set()))

    assert status == SchemaStatus.VERSIONED


async def test_run_oauth_migrations_applies_registered_version():
    conn = FakeConnection(meta_exists=True, meta_version=1)

    results = await run_oauth_migrations(conn, 1, 2, {2: ["SELECT 1"]})

    assert results == [
        {
            "from_version": 1,
            "to_version": 2,
            "statement_count": 1,
            "success": True,
            "error_message": None,
        }
    ]
    assert any(query == "SELECT 1" for query, _args in conn._executed)
    assert any("INSERT INTO oauth_schema_meta" in query for query, _args in conn._executed)
    assert any(query == "COMMIT" for query, _args in conn._executed)


async def test_run_oauth_migrations_dry_run_does_not_update_version():
    conn = FakeConnection(meta_exists=True, meta_version=1)

    results = await run_oauth_migrations(conn, 1, 2, {2: ["SELECT 1"]}, dry_run=True)

    assert results[0]["success"] is True
    assert any(query == "SELECT 1" for query, _args in conn._executed)
    assert not any("INSERT INTO oauth_schema_meta" in query for query, _args in conn._executed)
    assert any(query == "ROLLBACK" for query, _args in conn._executed)


async def test_run_oauth_migrations_requires_registered_target_version():
    with pytest.raises(RuntimeError, match="schema version 2 is not registered"):
        await run_oauth_migrations(FakeConnection(meta_exists=True, meta_version=1), 1, 2, {})


async def _iter_pg_storages():
    from guillotina.component import get_utility
    from guillotina.db.interfaces import IPostgresStorage
    from guillotina.interfaces import IApplication, IDatabase

    root = get_utility(IApplication, name="root")
    for _id, db in root:
        if not IDatabase.providedBy(db):
            continue
        tm = db.get_transaction_manager()
        if IPostgresStorage.providedBy(tm.storage):
            yield tm.storage


async def _drop_oauth_schema(storage):
    async with storage.pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS oauth_consents CASCADE")
        await conn.execute("DROP TABLE IF EXISTS oauth_refresh_tokens CASCADE")
        await conn.execute("DROP TABLE IF EXISTS oauth_authorization_codes CASCADE")
        await conn.execute("DROP TABLE IF EXISTS oauth_clients CASCADE")
        await conn.execute("DROP TABLE IF EXISTS oauth_schema_meta CASCADE")


async def _create_unversioned_baseline(conn):
    for ddl in OAUTH_BASELINE_DDL:
        if "oauth_schema_meta" not in ddl:
            await conn.execute(ddl)


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_postgresql_baseline_bootstrap_is_versioned_and_matches_declared_columns(guillotina_main):
    async for storage in _iter_pg_storages():
        await _drop_oauth_schema(storage)

        async with storage.pool.acquire() as conn:
            assert await get_schema_status(conn) == SchemaStatus.EMPTY
            assert await install_oauth_baseline(conn) == SchemaStatus.VERSIONED
            assert await install_oauth_baseline(conn) == SchemaStatus.VERSIONED
            assert await get_schema_status(conn) == SchemaStatus.VERSIONED
            row = await conn.fetchrow("SELECT version FROM oauth_schema_meta WHERE id = 1")
            assert row["version"] == OAUTH_SCHEMA_VERSION

            for table_name, expected_cols in OAUTH_BASELINE_COLUMNS.items():
                rows = await conn.fetch(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = $1 AND table_schema = 'public' "
                    "ORDER BY ordinal_position",
                    table_name,
                )
                actual = {row["column_name"]: row["data_type"] for row in rows}
                for column_name, expected_type in expected_cols.items():
                    assert actual[column_name] == expected_type


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_postgresql_unversioned_schema_can_be_adopted_as_v1(guillotina_main):
    async for storage in _iter_pg_storages():
        await _drop_oauth_schema(storage)

        async with storage.pool.acquire() as conn:
            await _create_unversioned_baseline(conn)
            assert await get_schema_status(conn) == SchemaStatus.UNVERSIONED
            compatible, diffs = await validate_unversioned_baseline(conn)
            assert compatible is True
            assert diffs == []

            await mark_existing_schema_as_v1(conn)

            assert await get_schema_status(conn) == SchemaStatus.VERSIONED


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_ensure_oauth_schema_bootstraps_empty_postgresql_storage(guillotina_main):
    from guillotina_oauth_server.storage import utility

    async for storage in _iter_pg_storages():
        await _drop_oauth_schema(storage)
        utility._ddl_initialized.clear()

        status = await utility.ensure_oauth_schema(storage)

        assert status == SchemaStatus.VERSIONED
        assert id(storage.pool) in utility._ddl_initialized


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_schema_strict_blocks_unversioned_schema_on_startup(guillotina_main):
    from guillotina import app_settings

    from guillotina_oauth_server.storage import utility

    async for storage in _iter_pg_storages():
        await _drop_oauth_schema(storage)
        async with storage.pool.acquire() as conn:
            await _create_unversioned_baseline(conn)

        utility._ddl_initialized.clear()
        app_settings["oauth"]["schema_strict"] = True
        try:
            with pytest.raises(RuntimeError, match="unversioned"):
                await utility.ensure_oauth_schema(storage)
        finally:
            app_settings["oauth"]["schema_strict"] = False
            await _drop_oauth_schema(storage)
            utility._ddl_initialized.clear()


@pytest.mark.app_settings(
    {
        "applications": ["guillotina", "guillotina_oauth_server"],
        "oauth": {"schema_strict": False},
    }
)
@requires_pg
async def test_code_too_old_always_blocks_startup(guillotina_main):
    from guillotina_oauth_server.storage import utility

    async for storage in _iter_pg_storages():
        await _drop_oauth_schema(storage)
        async with storage.pool.acquire() as conn:
            await install_oauth_baseline(conn)
            await conn.execute("UPDATE oauth_schema_meta SET version = 999 WHERE id = 1")

        utility._ddl_initialized.clear()
        try:
            with pytest.raises(RuntimeError, match="newer than code version"):
                await utility.ensure_oauth_schema(storage)
        finally:
            await _drop_oauth_schema(storage)
            utility._ddl_initialized.clear()
