CHANGELOG
=========

1.0.1 (2026-06-24)
------------------

- Add automated PyPI publishing via GitHub Actions using Trusted Publishing
  (OIDC); no API token is stored. Releases are cut with ``zest.releaser`` and
  published when a GitHub Release is created.
  [guillotinaweb]

- Add gitleaks secret scanning to CI and extend ``.gitignore`` with
  credential/secret file patterns.
  [guillotinaweb]

- Document the versioned PostgreSQL schema and ``oauth-migrate`` upgrade
  workflow in the README ("Releasing" and "Database schema and upgrades").
  [guillotinaweb]

1.0.0 (2026-06-24)
------------------

- Initial release of guillotina oauth server.
  [guillotinaweb]
