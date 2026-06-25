# AGENTS.md

## Commands
- Install full CI/test extras with `pip install -e ".[test,mcp,redis]"`; `pip install -e ".[test]"` is enough unless touching MCP or Redis paths.
- CI pre-checks are `pip install flake8 isort black==24.10.0`, then `flake8 guillotina_oauth_server --config=setup.cfg`, `isort -c guillotina_oauth_server`, `black --check --verbose guillotina_oauth_server`.
- CI tests run `pytest --capture=no --tb=native -v guillotina_oauth_server --cov=guillotina_oauth_server --cov-report term-missing --cov-append guillotina_oauth_server` with `DATABASE` set to both `DUMMY` and `postgresql`.
- Run a focused PostgreSQL test as `DATABASE=postgresql pytest -q guillotina_oauth_server/tests/test_oauth_token.py::test_name`; Docker must be available because PostgreSQL comes from `pytest-docker-fixtures`.
- `DATABASE=DUMMY` deliberately skips tests marked by `requires_pg` in `tests/conftest.py`; do not treat it as full verification for endpoint/storage changes.

## Repo Wiring
- This is a single Python package, `guillotina_oauth_server`, for Guillotina; supported Python versions are 3.10-3.13.
- `guillotina_oauth_server/__init__.py` is the main wiring point: it registers `oauth-migrate`, auth validators, the writable-request override, the `oauth_storage` utility, scans `install` and `api.services`, and only scans/registers MCP integration when `guillotina.contrib.mcp` is in `applications`.
- The Guillotina addon id is `oauth` (`install.py`); API handlers require the addon to be installed per container unless code explicitly passes `require_installed=False`.
- OAuth routes are dispatched from `api/services.py` through `OAUTH_GET_ACTIONS` and `OAUTH_POST_ACTIONS`; endpoint logic lives under `api/endpoints/`.
- `/oauth/authorize` intentionally writes during GET; keep `check_writable_request` pointing at `guillotina_oauth_server.utils.writable.requires_writable_transaction` unless changing that flow deliberately.

## Storage And Schema
- OAuth storage is PostgreSQL-only: `get_oauth_store()` requires an active Guillotina transaction whose storage provides `IPostgresStorage`.
- Stored rows are scoped by `storage/access.py` as `db_id/container.id`, not just container id.
- Fresh PostgreSQL installs bootstrap the versioned baseline schema automatically; existing environments use `g -c config.yaml oauth-migrate --dry-run`, then `g -c config.yaml oauth-migrate`, then `g -c config.yaml oauth-migrate --show-version`.
- Legacy tables without `oauth_schema_meta` must be handled with `g oauth-migrate --bootstrap-legacy`; `oauth.schema_strict=true` turns legacy/outdated schema warnings into startup errors, and DB schema newer than code always raises.
- For schema changes, update `storage/pg/schema.py` (`OAUTH_SCHEMA_VERSION`, baseline DDL, and baseline column map), add migration SQL in `storage/pg/migrations.py`, and cover it in `tests/test_oauth_schema_migration.py`.

## Behavior Gotchas
- JWT access tokens are OAuth-specific tokens signed from the global Guillotina `jwt.secret`; real configs must also set `jwt.algorithm`.
- Browser login and consent need `CookiePolicy` in `auth_extractors`; tests use `OAUTH_SETTINGS`/`OAUTH_MCP_SETTINGS` in `tests/conftest.py` as the reference configuration.
- Resource indicators are registry-driven: the container issuer is registered by default, while MCP resource/audience/protected-resource metadata is registered only when `guillotina.contrib.mcp` is enabled.
- Rate limits are disabled by setting the relevant limit to `0`; Redis-backed counters are used only when both `guillotina.contrib.redis` is in `applications` and `redis` settings are present, otherwise limits are per-process memory.

## Release Notes
- Every PR must add an entry to `CHANGELOG.rst` under the top `X.Y.Z (unreleased)` section, using the Guillotina format (a `- description.` bullet followed by an indented `[nick]` line); the `changelog` CI job fails PRs that do not touch `CHANGELOG.rst` unless the `skip changelog` label is applied.
- Formatting config is split: Black line length is 110 (`pyproject.toml`), while flake8 max line length is 120 (`setup.cfg`).
- `setup.cfg` sets `zest.releaser` `release = no`; local `fullrelease` should not upload to PyPI because GitHub Release publishing uses Trusted Publishing.
- The release workflow publishes only when a GitHub Release is published, and it fails if the tag `vX.Y.Z` does not match the `VERSION` file.
