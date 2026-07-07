import asyncio
import logging

from guillotina import app_settings
from guillotina.component import get_utility
from guillotina.db.interfaces import IPostgresStorage
from guillotina.interfaces import IApplication, IDatabase
from zope.interface import implementer

from guillotina_oauth_server.interfaces import IOAuthStorageUtility
from guillotina_oauth_server.storage.pg.repository import cleanup_expired
from guillotina_oauth_server.storage.pg.schema import OAUTH_SCHEMA_VERSION
from guillotina_oauth_server.storage.pg.schema_ops import (
    SchemaStatus,
    get_oauth_schema_version,
    get_schema_status,
    install_oauth_baseline,
)


logger = logging.getLogger("guillotina_oauth_server")

_ddl_initialized = set()

OAUTH_STORAGE_DEFAULTS = {
    "cleanup_interval": 900,
    "cleanup_batch_size": 5000,
}


def get_oauth_storage_settings():
    settings = dict(OAUTH_STORAGE_DEFAULTS)
    oauth = app_settings.get("oauth") or {}
    for key in OAUTH_STORAGE_DEFAULTS:
        if key in oauth:
            settings[key] = oauth[key]
    try:
        utility = get_utility(IOAuthStorageUtility)
        utility_settings = getattr(utility, "_settings", None) or {}
        for key in OAUTH_STORAGE_DEFAULTS:
            if key in utility_settings:
                settings[key] = utility_settings[key]
    except Exception:
        pass
    return settings


async def ensure_oauth_schema(storage):
    storage_key = id(storage.pool)
    if storage_key in _ddl_initialized:
        return SchemaStatus.VERSIONED

    schema_strict = (app_settings.get("oauth") or {}).get("schema_strict", False)

    async with storage.pool.acquire() as conn:
        status = await get_schema_status(conn)

        if status == SchemaStatus.EMPTY:
            await install_oauth_baseline(conn)
            _ddl_initialized.add(storage_key)
            return SchemaStatus.VERSIONED

        if status == SchemaStatus.VERSIONED:
            _ddl_initialized.add(storage_key)
            return SchemaStatus.VERSIONED

        if status == SchemaStatus.UNVERSIONED:
            logger.error(
                "OAuth schema is unversioned (tables exist but no oauth_schema_meta). "
                "Run 'g oauth-migrate' to adopt it as version 1 and apply pending migrations."
            )
            if schema_strict:
                raise RuntimeError("OAuth unversioned schema detected with schema_strict=true")
            return status

        if status == SchemaStatus.PARTIAL:
            logger.error(
                "OAuth schema is in a partial/corrupt state. "
                "Drop oauth_* tables or fix the schema manually before running 'g oauth-migrate'."
            )
            if schema_strict:
                raise RuntimeError("OAuth partial schema detected with schema_strict=true")
            return status

        if status == SchemaStatus.NEEDS_MIGRATION:
            current = await get_oauth_schema_version(conn)
            logger.error(
                "OAuth schema version %s is behind code version %s. "
                "Run 'g oauth-migrate' before continuing.",
                current,
                OAUTH_SCHEMA_VERSION,
            )
            if schema_strict:
                raise RuntimeError(f"OAuth schema version {current} < {OAUTH_SCHEMA_VERSION}")
            return status

        if status == SchemaStatus.CODE_TOO_OLD:
            current = await get_oauth_schema_version(conn)
            raise RuntimeError(
                f"OAuth schema version {current} is newer than code version. "
                "Downgrade the database or deploy a newer code version."
            )


@implementer(IOAuthStorageUtility)
class OAuthStorageUtility:
    def __init__(self, settings=None):
        self._settings = settings or {}
        self._task = None
        self._closing = False

    def _warn_issuer_not_pinned(self):
        oauth = app_settings.get("oauth") or {}
        if oauth.get("issuer") or app_settings.get("debug"):
            return
        if oauth.get("trust_proxy_headers"):
            logger.warning(
                "oauth.issuer is not configured and oauth.trust_proxy_headers is enabled: "
                "the OAuth issuer/audience will be derived from client-supplied forwarding "
                "headers. Pin oauth.issuer to your canonical public URL to prevent spoofing."
            )
        else:
            logger.warning(
                "oauth.issuer is not configured: the OAuth issuer/audience will be derived "
                "from the request Host header. Pin oauth.issuer to your canonical public URL "
                "(or set oauth.trust_proxy_headers=True behind a trusted reverse proxy)."
            )

    async def initialize(self, app=None):
        self._warn_issuer_not_pinned()
        initialized = False
        root = get_utility(IApplication, name="root")
        for _id, db in root:
            if not IDatabase.providedBy(db):
                continue
            tm = db.get_transaction_manager()
            if not IPostgresStorage.providedBy(tm.storage):
                continue
            status = await ensure_oauth_schema(tm.storage)
            if status == SchemaStatus.VERSIONED:
                initialized = True
        if initialized:
            self._closing = False
            self._task = asyncio.create_task(self._cleanup_loop())
            logger.info("OAuth storage initialized (PostgreSQL)")
        else:
            logger.info("OAuth PostgreSQL tables skipped (no PostgreSQL database found)")

    async def finalize(self, app=None):
        self._closing = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _cleanup_loop(self):
        storage_settings = get_oauth_storage_settings()
        interval = storage_settings.get("cleanup_interval", 900)
        batch_size = storage_settings.get("cleanup_batch_size", 5000)
        while not self._closing:
            try:
                await asyncio.sleep(interval)
                await self.run_cleanup(batch_size=batch_size)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning("OAuth cleanup failed", exc_info=True)

    async def run_cleanup(self, batch_size=5000):
        root = get_utility(IApplication, name="root")
        for _id, db in root:
            if not IDatabase.providedBy(db):
                continue
            tm = db.get_transaction_manager()
            if not IPostgresStorage.providedBy(tm.storage):
                continue
            async with tm.storage.pool.acquire() as conn:
                await cleanup_expired(conn, batch_size=batch_size)
