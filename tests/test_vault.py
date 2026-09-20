from __future__ import annotations

from cryptography.fernet import Fernet

from plane_mcp.vault import CredentialVault


def test_setup_code_stores_and_reads_encrypted_token(tmp_path):
    vault = CredentialVault(str(tmp_path / "vault.db"), Fernet.generate_key().decode())
    code = vault.create_setup_code("github-1", "octocat")

    assert vault.setup_identity(code) == ("github-1", "octocat")
    assert not vault.has_token("github-1")

    assert vault.store_token(code, "plane_api_secret") == ("github-1", "octocat")
    assert vault.has_token("github-1")
    assert vault.get_token("github-1") == "plane_api_secret"
    assert vault.setup_identity(code) is None

    database_bytes = (tmp_path / "vault.db").read_bytes()
    assert b"plane_api_secret" not in database_bytes


def test_revoke_removes_token(tmp_path):
    vault = CredentialVault(str(tmp_path / "vault.db"), Fernet.generate_key().decode())
    code = vault.create_setup_code("github-1", "octocat")
    vault.store_token(code, "plane_api_secret")

    assert vault.revoke("github-1")
    assert vault.get_token("github-1") is None
    assert not vault.revoke("github-1")


def test_expired_or_used_setup_code_fails(tmp_path):
    vault = CredentialVault(
        str(tmp_path / "vault.db"), Fernet.generate_key().decode(), setup_ttl_seconds=-1
    )
    code = vault.create_setup_code("github-1", "octocat")

    assert vault.setup_identity(code) is None
