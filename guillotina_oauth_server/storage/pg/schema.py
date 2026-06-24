OAUTH_SCHEMA_VERSION = 1

OAUTH_SCHEMA_META_DDL = """
CREATE TABLE IF NOT EXISTS oauth_schema_meta (
    id int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version int NOT NULL
)
"""

OAUTH_MIGRATION_LOG_DDL = """
CREATE TABLE IF NOT EXISTS oauth_schema_migration_log (
    id serial PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now(),
    from_version int,
    to_version int NOT NULL,
    migration_index int NOT NULL,
    sql_hash text NOT NULL,
    success boolean NOT NULL,
    error_message text,
    duration_ms int
)
"""

OAUTH_DDL = [
    """
CREATE TABLE IF NOT EXISTS oauth_clients (
    container_db_key text NOT NULL,
    client_id text NOT NULL,
    client_name text NOT NULL,
    redirect_uris jsonb NOT NULL DEFAULT '[]',
    grant_types jsonb NOT NULL DEFAULT '[]',
    response_types jsonb NOT NULL DEFAULT '[]',
    scope text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (container_db_key, client_id)
)
""",
    """
CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
    container_db_key text NOT NULL,
    code_hash text NOT NULL,
    client_id text NOT NULL,
    user_id text NOT NULL,
    redirect_uri text NOT NULL,
    scope jsonb NOT NULL DEFAULT '[]',
    resource jsonb NOT NULL DEFAULT '[]',
    code_challenge text,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (container_db_key, code_hash)
)
""",
    """
CREATE INDEX IF NOT EXISTS oauth_codes_expires_idx
    ON oauth_authorization_codes (expires_at)
""",
    """
CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
    container_db_key text NOT NULL,
    token_hash text NOT NULL,
    client_id text NOT NULL,
    user_id text NOT NULL,
    scope jsonb NOT NULL DEFAULT '[]',
    resource jsonb NOT NULL DEFAULT '[]',
    expires_at timestamptz NOT NULL,
    rotated_from text,
    auth_code_hash text,
    revoked_at timestamptz,
    replaced_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    PRIMARY KEY (container_db_key, token_hash)
)
""",
    """
CREATE INDEX IF NOT EXISTS oauth_refresh_expires_idx
    ON oauth_refresh_tokens (expires_at)
""",
    """
CREATE INDEX IF NOT EXISTS oauth_refresh_auth_code_idx
    ON oauth_refresh_tokens (container_db_key, auth_code_hash)
    WHERE auth_code_hash IS NOT NULL
""",
    """
ALTER TABLE oauth_refresh_tokens ADD COLUMN IF NOT EXISTS revoked_at timestamptz
""",
    """
ALTER TABLE oauth_refresh_tokens ADD COLUMN IF NOT EXISTS replaced_by text
""",
    """
CREATE TABLE IF NOT EXISTS oauth_consents (
    container_db_key text NOT NULL,
    consent_key text NOT NULL,
    user_id text NOT NULL,
    client_id text NOT NULL,
    scope jsonb NOT NULL DEFAULT '[]',
    resource jsonb NOT NULL DEFAULT '[]',
    granted_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    PRIMARY KEY (container_db_key, consent_key)
)
""",
    """
ALTER TABLE oauth_consents ADD COLUMN IF NOT EXISTS expires_at timestamptz
""",
    """
CREATE INDEX IF NOT EXISTS oauth_consents_user_idx
    ON oauth_consents (container_db_key, user_id)
""",
    """
CREATE INDEX IF NOT EXISTS oauth_consents_expires_idx
    ON oauth_consents (expires_at)
    WHERE expires_at IS NOT NULL
""",
]

OAUTH_BASELINE_DDL = [
    OAUTH_SCHEMA_META_DDL,
    OAUTH_MIGRATION_LOG_DDL,
    """
CREATE TABLE IF NOT EXISTS oauth_clients (
    container_db_key text NOT NULL,
    client_id text NOT NULL,
    client_name text NOT NULL,
    redirect_uris jsonb NOT NULL DEFAULT '[]',
    grant_types jsonb NOT NULL DEFAULT '[]',
    response_types jsonb NOT NULL DEFAULT '[]',
    scope text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (container_db_key, client_id)
)
""",
    """
CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
    container_db_key text NOT NULL,
    code_hash text NOT NULL,
    client_id text NOT NULL,
    user_id text NOT NULL,
    redirect_uri text NOT NULL,
    scope jsonb NOT NULL DEFAULT '[]',
    resource jsonb NOT NULL DEFAULT '[]',
    code_challenge text,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (container_db_key, code_hash)
)
""",
    """
CREATE INDEX IF NOT EXISTS oauth_codes_expires_idx
    ON oauth_authorization_codes (expires_at)
""",
    """
CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
    container_db_key text NOT NULL,
    token_hash text NOT NULL,
    client_id text NOT NULL,
    user_id text NOT NULL,
    scope jsonb NOT NULL DEFAULT '[]',
    resource jsonb NOT NULL DEFAULT '[]',
    expires_at timestamptz NOT NULL,
    rotated_from text,
    auth_code_hash text,
    revoked_at timestamptz,
    replaced_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    PRIMARY KEY (container_db_key, token_hash)
)
""",
    """
CREATE INDEX IF NOT EXISTS oauth_refresh_expires_idx
    ON oauth_refresh_tokens (expires_at)
""",
    """
CREATE INDEX IF NOT EXISTS oauth_refresh_auth_code_idx
    ON oauth_refresh_tokens (container_db_key, auth_code_hash)
    WHERE auth_code_hash IS NOT NULL
""",
    """
CREATE TABLE IF NOT EXISTS oauth_consents (
    container_db_key text NOT NULL,
    consent_key text NOT NULL,
    user_id text NOT NULL,
    client_id text NOT NULL,
    scope jsonb NOT NULL DEFAULT '[]',
    resource jsonb NOT NULL DEFAULT '[]',
    granted_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    PRIMARY KEY (container_db_key, consent_key)
)
""",
    """
CREATE INDEX IF NOT EXISTS oauth_consents_user_idx
    ON oauth_consents (container_db_key, user_id)
""",
    """
CREATE INDEX IF NOT EXISTS oauth_consents_expires_idx
    ON oauth_consents (expires_at)
    WHERE expires_at IS NOT NULL
""",
]

OAUTH_TABLE_NAMES = [
    "oauth_clients",
    "oauth_authorization_codes",
    "oauth_refresh_tokens",
    "oauth_consents",
]

OAUTH_BASELINE_COLUMNS = {
    "oauth_clients": {
        "container_db_key": "text",
        "client_id": "text",
        "client_name": "text",
        "redirect_uris": "jsonb",
        "grant_types": "jsonb",
        "response_types": "jsonb",
        "scope": "text",
        "created_at": "timestamp with time zone",
        "updated_at": "timestamp with time zone",
    },
    "oauth_authorization_codes": {
        "container_db_key": "text",
        "code_hash": "text",
        "client_id": "text",
        "user_id": "text",
        "redirect_uri": "text",
        "scope": "jsonb",
        "resource": "jsonb",
        "code_challenge": "text",
        "expires_at": "timestamp with time zone",
        "created_at": "timestamp with time zone",
    },
    "oauth_refresh_tokens": {
        "container_db_key": "text",
        "token_hash": "text",
        "client_id": "text",
        "user_id": "text",
        "scope": "jsonb",
        "resource": "jsonb",
        "expires_at": "timestamp with time zone",
        "rotated_from": "text",
        "auth_code_hash": "text",
        "revoked_at": "timestamp with time zone",
        "replaced_by": "text",
        "created_at": "timestamp with time zone",
        "last_used_at": "timestamp with time zone",
    },
    "oauth_consents": {
        "container_db_key": "text",
        "consent_key": "text",
        "user_id": "text",
        "client_id": "text",
        "scope": "jsonb",
        "resource": "jsonb",
        "granted_at": "timestamp with time zone",
        "expires_at": "timestamp with time zone",
    },
}
