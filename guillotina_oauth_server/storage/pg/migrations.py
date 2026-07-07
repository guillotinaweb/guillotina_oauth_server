# Forward-only migrations keyed by target schema version.
# When adding version N, also update schema.py's OAUTH_SCHEMA_VERSION,
# OAUTH_BASELINE_DDL, OAUTH_BASELINE_COLUMNS, and the schema migration tests.
OAUTH_MIGRATIONS: dict[int, list[str]] = {}
