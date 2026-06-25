CHANGELOG
=========

1.0.3 (unreleased)
------------------

- Release: tag releases as ``vX.Y.Z`` via ``zest.releaser`` ``tag-format`` for
  consistency with the existing ``v1.0.0``/``v1.0.1`` tags.
  [rboixaderg]

- CI: bump GitHub Actions to their Node.js 24 majors (``checkout@v7``,
  ``setup-python@v6``, ``upload-artifact@v7``, ``download-artifact@v8``) to clear
  the Node.js 20 deprecation warnings.
  [rboixaderg]


1.0.2 (2026-06-25)
------------------

- Reject OAuth access tokens in the generic Guillotina JWT validator: a custom
  ``guillotina_oauth_server.auth.validators.JWTValidator`` now replaces
  ``guillotina.auth.validators.JWTValidator`` so OAuth-issued access tokens are
  only honored through the dedicated OAuth validator (with signature, issuer and
  audience checks) and never through the generic JWT path.
  [rboixaderg]

- MCP: emit the OAuth ``WWW-Authenticate`` challenge for ``/@mcp/protocol`` from
  a self-contained ASGI middleware (``OAuthMCPChallengeMiddleware``) instead of
  importing ``guillotina.contrib.mcp.interfaces.IMCPAuthPolicy``, which is absent
  from upstream Guillotina and broke the MCP integration on import.
  [rboixaderg]

- CI: pin and run gitleaks directly for secret scanning instead of the
  marketplace action.
  [rboixaderg]

- CI: fail pull requests that do not update ``CHANGELOG.rst`` (use the
  ``skip changelog`` label to opt out for changes that need no release note).
  [rboixaderg]

1.0.1 (2026-06-24)
------------------

- Add automated PyPI publishing via GitHub Actions using Trusted Publishing
  (OIDC); no API token is stored. Releases are cut with ``zest.releaser`` and
  published when a GitHub Release is created.
  [rboixaderg]

- Add gitleaks secret scanning to CI and extend ``.gitignore`` with
  credential/secret file patterns.
  [rboixaderg]

- Document the versioned PostgreSQL schema and ``oauth-migrate`` upgrade
  workflow in the README ("Releasing" and "Database schema and upgrades").
  [rboixaderg]

1.0.0 (2026-06-24)
------------------

- Initial release of guillotina oauth server.
  [rboixaderg]
