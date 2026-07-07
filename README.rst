guillotina_oauth_server
=======================

``guillotina_oauth_server`` is an OAuth 2.0 Authorization Code + PKCE (``S256``)
public-client authorization server for the `Guillotina
<https://guillotina.readthedocs.io/>`_ framework.

It implements an OAuth 2.0 authorization server profile aligned with RFC 9700
guidance, including dynamic client registration (RFC 7591), authorization
server metadata (RFC 8414), resource indicators (RFC 8707), issuer
identification (RFC 9207), protected resource metadata (RFC 9728), opaque
refresh tokens, token revocation (RFC 7009), and JWT access tokens signed with
a key derived from Guillotina's configured ``jwt.secret``.

OAuth state is stored in PostgreSQL tables, configured via the
``oauth_storage`` utility settings. **A PostgreSQL database storage is
required.**

This package was previously distributed as ``guillotina.contrib.oauth``.


Installation
------------

.. code-block:: shell

    pip install guillotina_oauth_server

Optional extras:

.. code-block:: shell

    pip install guillotina_oauth_server[mcp]     # Model Context Protocol integration
    pip install guillotina_oauth_server[redis]   # shared rate-limit counters via Redis


Configuration
-------------

To enable and configure the OAuth 2.0 Authorization Code + PKCE public-client
profile, the following settings must be defined in your Guillotina
configuration (e.g. ``config.yaml``).

1. Enable the application
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add ``guillotina_oauth_server`` to your list of active applications:

.. code-block:: yaml

    applications:
      - guillotina_oauth_server

2. Configure JWT secrets
~~~~~~~~~~~~~~~~~~~~~~~~~~

Since OAuth access tokens are issued as signed JSON Web Tokens (JWT), you
**must** configure the global JWT signing settings:

.. code-block:: yaml

    jwt:
      secret: YOUR_SECURE_JWT_SECRET_KEY  # Change this to a secure key!
      algorithm: HS256

OAuth derives a purpose-specific signing key from ``jwt.secret``
(domain-separated from Guillotina's generic ``@login`` JWTs). Access tokens
carry ``token_type=oauth_access_token`` and are validated only by
``OAuthJWTValidator``.

3. Configure authentication extractors and validators
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Loading ``guillotina_oauth_server`` registers ``OAuthJWTValidator`` and the default
password/JWT validators automatically via ``app_settings``. You must still
configure ``auth_extractors`` so the browser login and consent forms work:

.. code-block:: yaml

    auth_extractors:
      - guillotina.auth.extractors.BearerAuthPolicy
      - guillotina.auth.extractors.BasicAuthPolicy
      - guillotina.auth.extractors.WSTokenAuthPolicy
      - guillotina.auth.extractors.CookiePolicy       # Required for browser login & consent form

Override ``auth_token_validators`` only when you need a custom validator order
or additional validators.

4. Set write permissions for GET requests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Guillotina normally prevents database writes on GET requests. Since the
``/oauth/authorize`` endpoint (which is a GET request) needs to create/validate
authorization states, ``check_writable_request`` must allow writes for that
path. Loading ``guillotina_oauth_server`` sets this automatically; override only if you
use a custom checker:

.. code-block:: yaml

    check_writable_request: guillotina_oauth_server.utils.writable.requires_writable_transaction

5. Customize OAuth server settings (optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Protocol settings (issuer, token TTLs, PKCE, scopes, rate limits) live under the
``oauth`` block. PostgreSQL cleanup tuning lives under
``load_utilities.oauth_storage.settings``:

.. code-block:: yaml

    oauth:
      issuer: null                    # Custom issuer URL (e.g. "https://auth.example.com"); see below
      trust_proxy_headers: false      # Honor X-Forwarded-Proto / X-VirtualHost-* when deriving issuer
      authorization_code_ttl: 600     # TTL in seconds for authorization codes (default 10 min)
      access_token_ttl: 3600          # TTL in seconds for access tokens (default 1 hour)
      refresh_token_ttl: 2592000      # TTL in seconds for refresh tokens (default 30 days)
      consent_ttl: 2592000            # Remembered consent lifetime (default 30 days; 0 = indefinite)
      allowed_code_challenge_methods: # PKCE S256 is always required for public clients
        - S256
      scopes_supported:               # Whitelist of scopes accepted at authorize and registration
        - guillotina:access
      registration_rate_limit: 20     # Dynamic registration requests per IP (0 = disabled)
      registration_rate_window: 600
      login_rate_limit: 10            # Failed login attempts per IP+username (0 = disabled)
      login_rate_window: 300
      token_rate_limit: 120           # Token endpoint requests per IP (0 = disabled)
      token_rate_window: 60
      revoke_rate_limit: 120          # Revocation endpoint requests per IP (0 = disabled)
      revoke_rate_window: 60

    load_utilities:
      oauth_storage:
        settings:
          cleanup_interval: 900       # seconds between expired-row cleanup runs
          cleanup_batch_size: 5000    # rows deleted per cleanup batch

The same cleanup keys may also be set under ``oauth`` for backward
compatibility; utility settings take precedence.

OAuth state is always persisted in PostgreSQL tables (``oauth_clients``,
``oauth_authorization_codes``, ``oauth_refresh_tokens``, ``oauth_consents``).

6. Issuer URL and reverse proxies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The issuer URL appears in discovery metadata, JWT ``iss`` claims, and
authorization redirects (RFC 9207).

When ``oauth.issuer`` is set, it must be an absolute ``http`` or ``https`` URL
without query, fragment, or userinfo. Production issuers must use ``https``
(plain ``http`` is allowed only for ``localhost``, ``127.0.0.1``, and ``::1``).

When ``oauth.issuer`` is ``null`` (the default), the issuer is derived from the
request:

- With ``trust_proxy_headers: false`` (the default), only the transport scheme
  and ``Host`` header are used. Spoofable ``X-Forwarded-Proto`` headers are
  ignored.
- With ``trust_proxy_headers: true``, set this only behind a trusted reverse
  proxy so forwarded scheme and virtual-host headers are honored.


Installing the addon
--------------------

Install the ``oauth`` addon in each container that should act as an
authorization server:

.. code-block:: shell

    # Install
    curl -X POST http://localhost:8080/db/container/@addons \
      -H "Content-Type: application/json" \
      -d '{"id": "oauth"}'

    # Uninstall (removes all OAuth data for the container)
    curl -X DELETE http://localhost:8080/db/container/@addons \
      -H "Content-Type: application/json" \
      -d '{"id": "oauth"}'


Database schema and upgrades
----------------------------

OAuth uses a versioned PostgreSQL schema. Fresh installations automatically
bootstrap the schema on startup. Existing environments should run the migration
command before deploying code that expects a newer schema.

The ``oauth_schema_meta`` table tracks the current schema version. Migrations
are forward-only and are applied transactionally from the registered
``OAUTH_MIGRATIONS`` entries.

When Guillotina starts and no OAuth tables exist, the baseline schema
(version 1) is created automatically. An advisory lock (``pg_advisory_lock``)
ensures only one worker performs the initialization, even with multiple
Gunicorn/Uvicorn workers.

Upgrade existing environments:

.. code-block:: shell

    # Phase 1: Check pending migrations
    g -c config.yaml oauth-migrate --dry-run

    # Phase 2: Apply migrations
    g -c config.yaml oauth-migrate

    # Phase 3: Deploy new code

    # Phase 4: Verify
    g -c config.yaml oauth-migrate --show-version

Databases that already have OAuth data tables but no ``oauth_schema_meta`` are
treated as unversioned. ``oauth-migrate`` validates them against the version 1
baseline, adopts them as version 1 when compatible, and then applies any pending
forward migrations.

Adding a schema migration
~~~~~~~~~~~~~~~~~~~~~~~~~

Schema migrations are forward-only. To add version ``N``:

1. Increment ``OAUTH_SCHEMA_VERSION`` in
   ``guillotina_oauth_server/storage/pg/schema.py``.
2. Update ``OAUTH_BASELINE_DDL`` so fresh installations create the final schema
   directly.
3. Update ``OAUTH_BASELINE_COLUMNS`` so unversioned existing schemas can still be
   validated against the version 1 baseline.
4. Add the migration SQL statements under ``OAUTH_MIGRATIONS[N]`` in
   ``guillotina_oauth_server/storage/pg/migrations.py``.
5. Add focused coverage in
   ``guillotina_oauth_server/tests/test_oauth_schema_migration.py``.
6. Add a ``CHANGELOG.rst`` entry.

Example:

.. code-block:: python

    # schema.py
    OAUTH_SCHEMA_VERSION = 2

    # migrations.py
    OAUTH_MIGRATIONS = {
        2: [
            "ALTER TABLE oauth_clients ADD COLUMN client_uri text",
            "CREATE INDEX IF NOT EXISTS oauth_clients_client_uri_idx ON oauth_clients (client_uri)",
        ],
    }

Do not skip versions: if the code schema version is ``3``, migrations for both
``2`` and ``3`` must be registered. Each version is applied inside a PostgreSQL
transaction and ``oauth_schema_meta.version`` is updated only after all SQL for
that version succeeds. Avoid PostgreSQL DDL that must run outside a transaction,
such as ``CREATE INDEX CONCURRENTLY``, unless the migrator is deliberately
changed to support it.

For production deployments, make the new code available for running
``oauth-migrate``, run the migration, then serve application traffic with the
code that expects the new schema.

Always take a database backup before running ``g oauth-migrate`` in production:

.. code-block:: shell

    pg_dump guillotina > backup_before_migration.sql

Additional command flags:

.. code-block:: shell

    g oauth-migrate --database db           # Target a specific database

For production, enable strict mode so startup fails immediately on schema
mismatch:

.. code-block:: yaml

    oauth:
      schema_strict: true

When ``schema_strict`` is ``false`` (default), startup logs warnings but
continues. Note: ``version > CURRENT`` (newer DB schema than code) **always**
raises a ``RuntimeError`` to prevent data corruption, regardless of
``schema_strict``.


Endpoints
---------

Endpoints are container scoped:

.. code-block:: text

    GET  /db/container/.well-known/oauth-authorization-server
    POST /db/container/oauth/register
    GET  /db/container/oauth/authorize
    POST /db/container/oauth/authorize    # login form, consent form, and consent submission
    POST /db/container/oauth/token
    POST /db/container/oauth/revoke
    GET  /db/container/oauth/consents     # list remembered consents (authenticated)
    POST /db/container/oauth/consents     # revoke a remembered consent (authenticated)

RFC 8414 discovery for issuers with a path component (such as ``/db/container``)
is also exposed at the application root:

.. code-block:: text

    GET /.well-known/oauth-authorization-server/db/container

When using MCP, protected resource metadata follows RFC 9728:

.. code-block:: text

    GET /db/container/.well-known/oauth-protected-resource
    GET /.well-known/oauth-protected-resource/db/container/@mcp/protocol

Opaque token prefixes: ``goc_`` (authorization codes), ``gor_`` (refresh
tokens).

The OAuth application does not expose ``/.well-known/openid-configuration``
because that path identifies OpenID Connect provider metadata, and this package
does not implement OpenID Connect (``id_token``, UserInfo, OIDC JWKS, subject
types, etc.).


Architecture: protocol phases
-----------------------------

The package is organized around the three phases of the protocol:

===========================  ================================  ==================
Phase                        Module                            RFC
===========================  ================================  ==================
Discovery                    ``discovery/``                    RFC 8414, RFC 9728
Grant (resource validation)  ``indicators/grant``              RFC 8707
Access (token validation)    ``indicators/access``, ``auth/``  RFC 8707
Token issuance               ``flow/``                         RFC 6749
MCP integration              ``integrations/mcp/``             --
===========================  ================================  ==================


Resource indicators (RFC 8707)
------------------------------

The ``resource`` parameter is restricted to URLs returned by registered
resolvers in ``guillotina_oauth_server.indicators``. The oauth application registers the
**container issuer** by default (``https://host/db/container``). When both
``guillotina_oauth_server`` and ``guillotina.contrib.mcp`` are in ``applications``,
OAuth also loads the MCP integration, registers ``{container}/@mcp/protocol``
(and subfolder MCP paths), and exposes MCP protected-resource metadata.

Register allowed values from your addon ``includeme`` (or startup hook):

.. code-block:: python

    from guillotina_oauth_server.indicators.registry import register_allowed_indicator_resolver

    def my_resolver(request, container):
        from guillotina_oauth_server.utils.urls import container_issuer_url
        base = container_issuer_url(request, container)
        return {f"{base}/@services/my-hook"}

    register_allowed_indicator_resolver(my_resolver)

Register a required audience for the access phase when a protocol endpoint must
enforce a specific ``aud`` value:

.. code-block:: python

    from guillotina_oauth_server.indicators.registry import register_required_indicator_resolver

    def my_audience_resolver(request, container):
        if str(getattr(request, "path", "") or "").endswith("/@services/my-hook"):
            from guillotina_oauth_server.utils.urls import container_issuer_url
            return f"{container_issuer_url(request, container)}/@services/my-hook"

    register_required_indicator_resolver(my_audience_resolver)


Authorization model
--------------------

OAuth provides **authentication** and **resource binding**. **Authorization**
is always enforced with native Guillotina permissions on the authenticated
user.

==========================  =================================================
Concern                     Mechanism
==========================  =================================================
Who is the user?            OAuth token ``sub`` claim
Which client?               OAuth token ``client_id`` claim
Which resource?             Token audience (``aud``) -- container URL or MCP endpoint
What can they do?           Guillotina roles and ACLs
==========================  =================================================

OAuth access tokens must include the ``guillotina:access`` scope.


Using PKCE and the OAuth flow (step by step)
--------------------------------------------

**Step 1 -- Generate PKCE secrets on the client.** Clients must generate a
high-entropy random ``code_verifier`` between 43 and 128 characters from the
unreserved set in RFC 7636 (``[A-Z] [a-z] [0-9] - . _ ~``), and compute its
``code_challenge`` using SHA-256 (BASE64URL encoding without padding):

.. code-block:: python

    import base64
    import hashlib
    import secrets

    code_verifier = secrets.token_urlsafe(64)
    hash_digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(hash_digest).rstrip(b"=").decode("ascii")

**Step 2 -- Register a public client:**

.. code-block:: shell

    curl -X POST http://localhost:8080/db/container/oauth/register \
      -H 'Content-Type: application/json' \
      -d '{"client_name":"MCP Client","redirect_uris":["http://127.0.0.1:12345/callback"],"token_endpoint_auth_method":"none"}'

Save the resulting ``client_id`` returned by the server.

**Step 3 -- Direct the user to the authorization endpoint** (append
``code_challenge`` and set ``code_challenge_method=S256``):

.. code-block:: text

    http://localhost:8080/db/container/oauth/authorize?response_type=code&client_id=CLIENT_ID&redirect_uri=http://127.0.0.1:12345/callback&scope=guillotina:access&code_challenge=YOUR_CODE_CHALLENGE&code_challenge_method=S256&state=some_random_state

The GET request returns an HTML login form. After login and consent, the user is
redirected back to ``redirect_uri`` with the authorization code, the original
``state``, and the issuer identifier ``iss`` (RFC 9207).

**Step 4 -- Exchange the code for tokens** (provide the original
``code_verifier`` in plaintext):

.. code-block:: shell

    curl -X POST http://localhost:8080/db/container/oauth/token \
      -H 'Content-Type: application/x-www-form-urlencoded' \
      -d 'grant_type=authorization_code&client_id=CLIENT_ID&redirect_uri=http://127.0.0.1:12345/callback&code=goc_XYZ123&code_verifier=YOUR_CODE_VERIFIER'

**Step 5 -- Refresh and revoke (optional).** Guillotina rotates refresh tokens
on every successful refresh. Clients must persist the new ``refresh_token`` and
discard the old one immediately:

.. code-block:: shell

    curl -X POST http://localhost:8080/db/container/oauth/token \
      -d 'grant_type=refresh_token&client_id=CLIENT_ID&refresh_token=YOUR_REFRESH_TOKEN'

To revoke an active refresh token (revokes the entire refresh-token family from
the same authorization grant):

.. code-block:: shell

    curl -X POST http://localhost:8080/db/container/oauth/revoke \
      -d 'client_id=CLIENT_ID&token=YOUR_REFRESH_TOKEN&token_type_hint=refresh_token'

Access token revocation is not supported
(``token_type_hint=access_token`` returns ``unsupported_token_type``).


Running the tests
-----------------

.. code-block:: shell

    pip install -e .[test]
    DATABASE=postgresql pytest guillotina_oauth_server

Integration tests require PostgreSQL (provided via ``pytest-docker-fixtures``).
Tests run with ``DATABASE=DUMMY`` skip the PostgreSQL-backed cases.


Releasing
---------

Publishing is automated and requires no PyPI token on any machine.

**One-time PyPI setup (Trusted Publishing).** On PyPI, configure a trusted
publisher for this project so GitHub Actions can upload via OIDC:

- Go to the project's *Publishing* settings (or *Your projects -> Manage ->
  Publishing*) at https://pypi.org/manage/account/publishing/
- Add a *GitHub* publisher with:

  - Owner: ``guillotinaweb``
  - Repository: ``guillotina_oauth_server``
  - Workflow filename: ``release.yml``
  - Environment name: ``pypi``

- In the GitHub repo, create an *Environment* named ``pypi``
  (*Settings -> Environments*). Optionally add required reviewers so a release
  must be approved before it is published.

No secrets are stored anywhere; PyPI trusts the workflow identity directly.

**Cutting a release.** Version, changelog, tag and the dev-version bump are all
handled by ``zest.releaser`` (already configured in ``setup.cfg``)::

    pip install zest.releaser
    fullrelease

``fullrelease`` interactively:

1. sets the final version in ``VERSION`` and dates the ``CHANGELOG.rst`` entry,
2. commits and creates a ``vX.Y.Z`` git tag,
3. pushes the commit and tag,
4. bumps ``VERSION`` to the next ``.devN`` and adds a new changelog section.

**Publishing.** After ``fullrelease`` pushes the tag, create a *GitHub Release*
for that tag (e.g. ``vX.Y.Z``). This triggers ``.github/workflows/release.yml``,
which builds the sdist/wheel, runs ``twine check``, verifies the tag matches the
``VERSION`` file, and publishes to PyPI via Trusted Publishing.

To avoid having ``zest.releaser`` upload to PyPI itself (CI does that), answer
"no" when it asks to upload, or set ``release = no`` under ``[zest.releaser]``
in ``setup.cfg``.


License
-------

GPL version 3. See ``LICENSE``.
