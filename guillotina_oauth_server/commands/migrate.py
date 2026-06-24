import logging

from guillotina.commands import Command
from guillotina.component import get_utility
from guillotina.db.interfaces import IPostgresStorage
from guillotina.interfaces import IApplication, IDatabase

from guillotina_oauth_server.storage.pg.migrations import OAUTH_MIGRATIONS
from guillotina_oauth_server.storage.pg.schema import OAUTH_SCHEMA_VERSION
from guillotina_oauth_server.storage.pg.schema_ops import (
    OAUTH_ADVISORY_LOCK_KEY1,
    OAUTH_ADVISORY_LOCK_KEY2,
    SchemaStatus,
    bootstrap_legacy_schema,
    get_oauth_schema_version,
    get_schema_status,
    install_oauth_baseline,
    run_oauth_migrations,
    set_oauth_schema_version,
    validate_legacy_schema,
)


logger = logging.getLogger("guillotina_oauth_server")


class OAuthMigrateCommand(Command):
    description = "Run OAuth PostgreSQL schema migration"

    def get_parser(self):
        parser = super().get_parser()
        parser.add_argument("--database", dest="database", help="Target specific database name", default=None)
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            help="Show pending migrations without applying",
            default=False,
        )
        parser.add_argument(
            "--show-version",
            dest="show_version",
            action="store_true",
            help="Show current version per database",
            default=False,
        )
        parser.add_argument(
            "--bootstrap-legacy",
            dest="bootstrap_legacy",
            action="store_true",
            help="Validate legacy schema against baseline and mark as version 1",
            default=False,
        )
        parser.add_argument(
            "--force",
            dest="force",
            action="store_true",
            help="Force bootstrap-legacy even when schema differs from baseline",
            default=False,
        )
        parser.add_argument(
            "--target-version",
            dest="target_version",
            type=int,
            default=OAUTH_SCHEMA_VERSION,
            help=f"Migrate to a specific version (default: {OAUTH_SCHEMA_VERSION})",
        )
        parser.add_argument(
            "--rollback",
            dest="rollback",
            action="store_true",
            help="Rollback the last applied migration (requires backward_sql)",
            default=False,
        )
        return parser

    async def run(self, arguments, settings, app):
        if arguments.show_version:
            await self._show_versions()
            return

        if arguments.bootstrap_legacy:
            await self._bootstrap_legacy(arguments.force)
            return

        if arguments.rollback:
            await self._rollback(arguments)
            return

        await self._migrate(arguments)

    async def _iter_pg_databases(self, db_name=None):
        root = get_utility(IApplication, name="root")
        for _id, db in root:
            if not IDatabase.providedBy(db):
                continue
            if db_name and db.id != db_name:
                continue
            tm = db.get_transaction_manager()
            if not IPostgresStorage.providedBy(tm.storage):
                continue
            yield db, tm.storage

    async def _show_versions(self):
        async for db, storage in self._iter_pg_databases(db_name=self.arguments.database):
            async with storage.pool.acquire() as conn:
                status = await get_schema_status(conn)
                version = await get_oauth_schema_version(conn)
                logger.warning(
                    "db=%s version=%s status=%s code_version=%s",
                    db.id,
                    version,
                    status.value,
                    OAUTH_SCHEMA_VERSION,
                )

    async def _bootstrap_legacy(self, force):
        async for db, storage in self._iter_pg_databases(db_name=self.arguments.database):
            async with storage.pool.acquire() as conn:
                status = await get_schema_status(conn)
                if status != SchemaStatus.LEGACY:
                    logger.warning(
                        "db=%s Skipping bootstrap-legacy: status=%s (expected LEGACY)",
                        db.id,
                        status.value,
                    )
                    continue

                compatible, diff_messages = await validate_legacy_schema(conn)

                if not compatible:
                    logger.warning(
                        "db=%s Schema differs from baseline v1:\n  %s",
                        db.id,
                        "\n  ".join(diff_messages),
                    )
                    if not force:
                        logger.error(
                            "db=%s Use --force to mark as version 1 despite differences. "
                            "Alternatively, DROP oauth_* tables and let startup bootstrap cleanly.",
                            db.id,
                        )
                        continue

                    logger.warning(
                        "db=%s Forcing bootstrap-legacy despite %d difference(s).",
                        db.id,
                        len(diff_messages),
                    )

                await bootstrap_legacy_schema(conn)
                logger.warning("db=%s Marked legacy schema as version 1.", db.id)

    async def _rollback(self, arguments):
        async for db, storage in self._iter_pg_databases(db_name=arguments.database):
            async with storage.pool.acquire() as conn:
                version = await get_oauth_schema_version(conn)
                if version is None:
                    logger.warning("db=%s No schema version found, nothing to rollback.", db.id)
                    continue

                target_v = version - 1
                if target_v < 1:
                    logger.warning("db=%s At version 1 (baseline), cannot rollback.", db.id)
                    continue

                if version not in OAUTH_MIGRATIONS:
                    logger.warning("db=%s No migrations registered for version %s.", db.id, version)
                    continue

                last_idx = len(OAUTH_MIGRATIONS[version]) - 1
                for idx in range(last_idx, -1, -1):
                    _forward_sql, backward_sql = OAUTH_MIGRATIONS[version][idx]
                    if backward_sql is None:
                        logger.warning(
                            "db=%s Migration v%s idx=%s has no backward_sql, cannot rollback.",
                            db.id,
                            version,
                            idx,
                        )
                        continue

                    logger.warning("db=%s Rolling back v%s idx=%s ...", db.id, version, idx)
                    await conn.execute("BEGIN")
                    try:
                        await conn.execute(backward_sql)
                        await set_oauth_schema_version(conn, target_v)
                        await conn.execute("COMMIT")
                        logger.warning("db=%s Rolled back to version %s.", db.id, target_v)
                    except Exception:
                        await conn.execute("ROLLBACK")
                        raise
                    break

    async def _migrate(self, arguments):
        dry_run = arguments.dry_run
        target_version = arguments.target_version

        async for db, storage in self._iter_pg_databases(db_name=arguments.database):
            async with storage.pool.acquire() as conn:
                lock_acquired = await conn.fetchval(
                    "SELECT pg_try_advisory_lock($1, $2)",
                    OAUTH_ADVISORY_LOCK_KEY1,
                    OAUTH_ADVISORY_LOCK_KEY2,
                )
                if not lock_acquired:
                    logger.error("db=%s Another OAuth migration is in progress. Try again later.", db.id)
                    continue

                try:
                    status = await get_schema_status(conn)

                    if status == SchemaStatus.EMPTY:
                        logger.warning("db=%s Installing baseline (v1) ...", db.id)
                        if not dry_run:
                            await install_oauth_baseline(conn)
                        logger.warning("db=%s Baseline v1 installed.", db.id)
                        continue

                    if status == SchemaStatus.LEGACY:
                        logger.error(
                            "db=%s Schema is legacy. Run 'g oauth-migrate --bootstrap-legacy' first.",
                            db.id,
                        )
                        continue

                    if status == SchemaStatus.PARTIAL:
                        logger.error("db=%s Schema is partial/corrupt. Manual intervention required.", db.id)
                        continue

                    if status == SchemaStatus.VERSIONED:
                        logger.warning("db=%s Already at version %s (current).", db.id, OAUTH_SCHEMA_VERSION)
                        continue

                    if status == SchemaStatus.CODE_TOO_OLD:
                        current = await get_oauth_schema_version(conn)
                        logger.error(
                            "db=%s DB version %s > code version %s. Deploy newer code or downgrade DB.",
                            db.id,
                            current,
                            OAUTH_SCHEMA_VERSION,
                        )
                        continue

                    if status == SchemaStatus.NEEDS_MIGRATION:
                        current = await get_oauth_schema_version(conn)
                        logger.warning("db=%s Migrating from v%s to v%s ...", db.id, current, target_version)
                        results = await run_oauth_migrations(
                            conn,
                            from_version=current,
                            to_version=target_version,
                            migrations=OAUTH_MIGRATIONS,
                            dry_run=dry_run,
                        )
                        for r in results:
                            mode = "DRY-RUN" if dry_run else "APPLIED"
                            logger.warning(
                                "db=%s %s v%s→%s idx=%s hash=%s success=%s duration=%sms",
                                db.id,
                                mode,
                                r["from_version"],
                                r["to_version"],
                                r["migration_index"],
                                r["sql_hash"],
                                r["success"],
                                r["duration_ms"],
                            )
                            if not r["success"]:
                                logger.error(
                                    "db=%s Migration v%s→%s failed: %s. Stopping.",
                                    db.id,
                                    r["from_version"],
                                    r["to_version"],
                                    r["error_message"],
                                )
                                break
                finally:
                    await conn.execute(
                        "SELECT pg_advisory_unlock($1, $2)",
                        OAUTH_ADVISORY_LOCK_KEY1,
                        OAUTH_ADVISORY_LOCK_KEY2,
                    )
