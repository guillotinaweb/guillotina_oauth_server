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
    get_oauth_schema_version,
    get_schema_status,
    install_oauth_baseline,
    mark_existing_schema_as_v1,
    run_oauth_migrations,
    validate_unversioned_baseline,
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
        return parser

    async def run(self, arguments, settings, app):
        if arguments.show_version:
            await self._show_versions()
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
                version = None
                if status not in (SchemaStatus.EMPTY, SchemaStatus.UNVERSIONED):
                    version = await get_oauth_schema_version(conn)
                logger.warning(
                    "db=%s version=%s status=%s code_version=%s",
                    db.id,
                    version,
                    status.value,
                    OAUTH_SCHEMA_VERSION,
                )

    async def _migrate(self, arguments):
        dry_run = arguments.dry_run
        target_version = OAUTH_SCHEMA_VERSION

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
                        mode = "Would install" if dry_run else "Installing"
                        logger.warning("db=%s %s baseline (v%s) ...", db.id, mode, OAUTH_SCHEMA_VERSION)
                        if not dry_run:
                            await install_oauth_baseline(conn)
                        result = "would be installed" if dry_run else "installed"
                        logger.warning("db=%s Baseline v%s %s.", db.id, OAUTH_SCHEMA_VERSION, result)
                        continue

                    if status == SchemaStatus.UNVERSIONED:
                        compatible, diff_messages = await validate_unversioned_baseline(conn)
                        if not compatible:
                            logger.error(
                                "db=%s Existing OAuth schema differs from baseline v1:\n  %s",
                                db.id,
                                "\n  ".join(diff_messages),
                            )
                            continue

                        logger.warning("db=%s Adopting existing OAuth schema as version 1 ...", db.id)
                        if not dry_run:
                            await mark_existing_schema_as_v1(conn)
                        if target_version == 1:
                            result = "would be marked" if dry_run else "marked"
                            logger.warning("db=%s Existing OAuth schema %s as version 1.", db.id, result)
                            continue
                        current = 1
                    else:
                        current = None

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

                    if current is not None and current < target_version:
                        await self._run_forward_migrations(conn, db.id, current, target_version, dry_run)
                finally:
                    await conn.execute(
                        "SELECT pg_advisory_unlock($1, $2)",
                        OAUTH_ADVISORY_LOCK_KEY1,
                        OAUTH_ADVISORY_LOCK_KEY2,
                    )

    async def _run_forward_migrations(self, conn, db_id, current, target_version, dry_run):
        logger.warning("db=%s Migrating from v%s to v%s ...", db_id, current, target_version)
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
                "db=%s %s v%s→%s statements=%s success=%s",
                db_id,
                mode,
                r["from_version"],
                r["to_version"],
                r["statement_count"],
                r["success"],
            )
            if not r["success"]:
                logger.error(
                    "db=%s Migration v%s→%s failed: %s. Stopping.",
                    db_id,
                    r["from_version"],
                    r["to_version"],
                    r["error_message"],
                )
                break
