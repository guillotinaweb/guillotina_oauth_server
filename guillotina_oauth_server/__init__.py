from guillotina import configure


app_settings = {
    "commands": {
        "oauth-migrate": "guillotina_oauth_server.commands.migrate.OAuthMigrateCommand",
    },
    "oauth": {
        "enabled": True,
        "issuer": None,
        # When False (default) the issuer is derived only from the transport
        # scheme and Host header. Enable behind a trusted reverse proxy so that
        # X-Forwarded-Proto / X-VirtualHost-* headers are honored.
        "trust_proxy_headers": False,
        "authorization_code_ttl": 600,
        "access_token_ttl": 3600,
        "refresh_token_ttl": 2592000,
        "allowed_code_challenge_methods": ["S256"],
        "scopes_supported": ["guillotina:access"],
        # Lifetime of a remembered consent (seconds). After it expires the user
        # is prompted to consent again. Set to 0 to keep consents indefinitely.
        "consent_ttl": 2592000,
        # Dynamic client registration throttling (per client IP, sliding window).
        # Set ``registration_rate_limit`` to 0 to disable.
        "registration_rate_limit": 20,
        "registration_rate_window": 600,
        # When True, startup raises an error if schema is outdated or legacy.
        # Recommended for production; default False for dev/test environments.
        "schema_strict": False,
        # Failed-login throttling at the authorization endpoint (per client IP +
        # username, sliding window). Set ``login_rate_limit`` to 0 to disable.
        "login_rate_limit": 10,
        "login_rate_window": 300,
        # Token and revocation endpoint throttling (per client IP).
        # Set the limit to 0 to disable.
        "token_rate_limit": 120,
        "token_rate_window": 60,
        "revoke_rate_limit": 120,
        "revoke_rate_window": 60,
    },
    "check_writable_request": "guillotina_oauth_server.utils.writable.requires_writable_transaction",
    "auth_token_validators": [
        "guillotina_oauth_server.auth.validators.OAuthJWTValidator",
        "guillotina.auth.validators.SaltedHashPasswordValidator",
        "guillotina.auth.validators.JWTValidator",
    ],
    "load_utilities": {
        "oauth_storage": {
            "provides": "guillotina_oauth_server.interfaces.IOAuthStorageUtility",
            "factory": "guillotina_oauth_server.storage.utility.OAuthStorageUtility",
            "settings": {
                "cleanup_interval": 900,
                "cleanup_batch_size": 5000,
            },
        }
    },
}


def includeme(root, settings):
    from guillotina_oauth_server.indicators.registry import ensure_default_resource_indicators_registered

    ensure_default_resource_indicators_registered()
    configure.scan("guillotina_oauth_server.install")
    configure.scan("guillotina_oauth_server.api.services")
    if "guillotina.contrib.mcp" in set(settings.get("applications") or []):
        configure.scan("guillotina_oauth_server.integrations.mcp")
        from guillotina_oauth_server.integrations.mcp import register_mcp_oauth_integration

        register_mcp_oauth_integration()
