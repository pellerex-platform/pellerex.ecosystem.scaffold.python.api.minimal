"""Secret-reading tests (P4 / PY-D6 / PY-R13).

Proves the app reads a secret from the CSI **tmpfs file mount** (one file per secret) and
that secret material is NEVER sourced from an environment variable.
"""

from app.config import Secrets


def test_reads_secret_from_tmpfs_mount(tmp_path):
    # Simulate the CSI mount: one file per secret, named after the Key Vault object.
    (tmp_path / "DbConnectionString").write_text("Server=db;Database=acme;")

    secrets = Secrets(_secrets_dir=str(tmp_path))

    assert secrets.db_connection_string == "Server=db;Database=acme;"
    assert secrets.has_database_secret is True


def test_secret_is_not_read_from_env(monkeypatch, tmp_path):
    # Even with the env var set, the secret must come only from the mount (PY-R13).
    monkeypatch.setenv("DbConnectionString", "FROM-ENV-SHOULD-BE-IGNORED")

    secrets = Secrets(_secrets_dir=str(tmp_path))  # empty dir → no secret file

    assert secrets.db_connection_string != "FROM-ENV-SHOULD-BE-IGNORED"
    assert secrets.db_connection_string is None


def test_missing_secret_is_tolerated(tmp_path):
    # No file present → None, app still boots (secret is Optional).
    secrets = Secrets(_secrets_dir=str(tmp_path))
    assert secrets.db_connection_string is None
    assert secrets.has_database_secret is False
