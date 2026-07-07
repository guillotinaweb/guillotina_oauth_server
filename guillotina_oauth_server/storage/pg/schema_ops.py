import asyncio
import enum
import logging

from guillotina_oauth_server.storage.pg.schema import (
    OAUTH_BASELINE_COLUMNS,
    OAUTH_BASELINE_DDL,
    OAUTH_SCHEMA_VERSION,
    OAUTH_TABLE_NAMES,
)


logger = logging.getLogger("guillotina_oauth_server")

OAUTH_ADVISORY_LOCK_KEY1 = 19001
OAUTH_ADVISORY_LOCK_KEY2 = 1


class SchemaStatus(enum.Enum):
    EMPTY = "empty"
    VERSIONED = "versioned"
    NEEDS_MIGRATION = "needs_migration"
    CODE_TOO_OLD = "code_too_old"
    UNVERSIONED = "unversioned"
    PARTIAL = "partial"


async def get_schema_status(conn) -> SchemaStatus:
    row = await conn.fetchrow(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'oauth_schema_meta')"
    )
    meta_exists = row[0]
    table_existence = await _check_oauth_tables(conn)

    if meta_exists:
        if table_existence["all"] is not True:
            return SchemaStatus.PARTIAL
        row = await conn.fetchrow("SELECT version FROM oauth_schema_meta WHERE id = 1")
        if row is None or row["version"] is None:
            return SchemaStatus.PARTIAL
        version = row["version"]
        if version == OAUTH_SCHEMA_VERSION:
            return SchemaStatus.VERSIONED
        elif version < OAUTH_SCHEMA_VERSION:
            return SchemaStatus.NEEDS_MIGRATION
        else:
            return SchemaStatus.CODE_TOO_OLD
    else:
        if table_existence["any"] == 0:
            return SchemaStatus.EMPTY
        elif table_existence["any"] > 0 and table_existence["all"] is True:
            return SchemaStatus.UNVERSIONED
        else:
            return SchemaStatus.PARTIAL


async def _check_oauth_tables(conn) -> dict:
    count = 0
    for table_name in OAUTH_TABLE_NAMES:
        row = await conn.fetchrow(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = $1)",
            table_name,
        )
        if row[0]:
            count += 1
    return {"any": count, "all": count == len(OAUTH_TABLE_NAMES)}


async def get_oauth_schema_version(conn):
    row = await conn.fetchrow("SELECT version FROM oauth_schema_meta WHERE id = 1")
    if row is None:
        return None
    return row["version"]


async def set_oauth_schema_version(conn, version):
    await conn.execute(
        "INSERT INTO oauth_schema_meta (id, version) VALUES (1, $1) "
        "ON CONFLICT (id) DO UPDATE SET version = $1",
        version,
    )


async def mark_existing_schema_as_v1(conn):
    from guillotina_oauth_server.storage.pg.schema import OAUTH_SCHEMA_META_DDL

    await conn.execute(OAUTH_SCHEMA_META_DDL)
    await set_oauth_schema_version(conn, 1)


async def install_oauth_baseline(conn):
    lock_acquired = await conn.fetchval(
        "SELECT pg_try_advisory_lock($1, $2)", OAUTH_ADVISORY_LOCK_KEY1, OAUTH_ADVISORY_LOCK_KEY2
    )
    if not lock_acquired:
        for _ in range(30):
            await asyncio.sleep(0.1)
            status = await get_schema_status(conn)
            if status in (SchemaStatus.VERSIONED, SchemaStatus.NEEDS_MIGRATION):
                return status
            lock_acquired = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1, $2)", OAUTH_ADVISORY_LOCK_KEY1, OAUTH_ADVISORY_LOCK_KEY2
            )
            if lock_acquired:
                break
        else:
            raise RuntimeError("Timed out waiting for OAuth baseline installation lock")

    try:
        status = await get_schema_status(conn)
        if status != SchemaStatus.EMPTY:
            return status

        await conn.execute("BEGIN")
        try:
            for ddl in OAUTH_BASELINE_DDL:
                await conn.execute(ddl)
            await set_oauth_schema_version(conn, OAUTH_SCHEMA_VERSION)
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise

        return SchemaStatus.VERSIONED
    finally:
        await conn.execute(
            "SELECT pg_advisory_unlock($1, $2)", OAUTH_ADVISORY_LOCK_KEY1, OAUTH_ADVISORY_LOCK_KEY2
        )


async def run_oauth_migrations(conn, from_version, to_version, migrations, dry_run=False):
    results = []
    for v in range(from_version + 1, to_version + 1):
        if v not in migrations:
            raise RuntimeError(f"OAuth migration to schema version {v} is not registered")
        success = False
        error_message = None
        try:
            await conn.execute("BEGIN")
            for sql in migrations[v]:
                await conn.execute(sql)
            if dry_run:
                await conn.execute("ROLLBACK")
            else:
                await set_oauth_schema_version(conn, v)
                await conn.execute("COMMIT")
            success = True
        except Exception as exc:
            await conn.execute("ROLLBACK")
            error_message = str(exc)
            logger.error("OAuth migration v%s→%s failed: %s", v - 1, v, error_message)

        results.append(
            {
                "from_version": v - 1,
                "to_version": v,
                "statement_count": len(migrations[v]),
                "success": success,
                "error_message": error_message,
            }
        )

        if not success:
            return results

    return results


async def validate_unversioned_baseline(conn):
    compatible = True
    diff_messages = []

    for table_name in OAUTH_TABLE_NAMES:
        expected = OAUTH_BASELINE_COLUMNS.get(table_name, {})
        rows = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = $1 AND table_schema = 'public' "
            "ORDER BY ordinal_position",
            table_name,
        )
        actual = {row["column_name"]: row["data_type"] for row in rows}

        for col, expected_type in expected.items():
            if col not in actual:
                compatible = False
                diff_messages.append(f"{table_name}: missing column '{col}' (expected {expected_type})")
            elif actual[col] != expected_type:
                compatible = False
                diff_messages.append(
                    f"{table_name}: column '{col}' type '{actual[col]}' != expected '{expected_type}'"
                )

        for col in actual:
            if col not in expected:
                diff_messages.append(f"{table_name}: unexpected column '{col}' (type {actual[col]})")

        if not rows:
            compatible = False
            diff_messages.append(f"{table_name}: table does not exist in public schema")

    return compatible, diff_messages
