"""Encrypted per-user Plane token storage and one-time setup links."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class CredentialVault:
    """Store encrypted Plane PATs in a local SQLite database."""

    def __init__(self, path: str, encryption_key: str, *, setup_ttl_seconds: int = 600) -> None:
        if not encryption_key:
            raise ValueError("PAT_VAULT_KEY is required")
        try:
            self._fernet = Fernet(encryption_key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise ValueError("PAT_VAULT_KEY must be a valid Fernet key") from exc
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.setup_ttl_seconds = setup_ttl_seconds
        self._initialize()

    @classmethod
    def from_env(cls) -> CredentialVault:
        return cls(
            os.environ.get("PAT_VAULT_PATH", "/data/plane-mcp.db"),
            os.environ["PAT_VAULT_KEY"],
            setup_ttl_seconds=int(os.environ.get("PAT_SETUP_TTL_SECONDS", "600")),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS credentials (
                    github_user_id TEXT PRIMARY KEY,
                    github_login TEXT NOT NULL,
                    plane_token BLOB NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS setup_codes (
                    code_hash TEXT PRIMARY KEY,
                    github_user_id TEXT NOT NULL,
                    github_login TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS setup_codes_user_idx
                    ON setup_codes(github_user_id);
                """
            )

    @staticmethod
    def _hash_code(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def create_setup_code(self, github_user_id: str, github_login: str) -> str:
        code = secrets.token_urlsafe(32)
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM setup_codes WHERE github_user_id = ? OR expires_at < ?",
                (github_user_id, now),
            )
            connection.execute(
                """
                INSERT INTO setup_codes(code_hash, github_user_id, github_login, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    self._hash_code(code),
                    github_user_id,
                    github_login,
                    now + self.setup_ttl_seconds,
                ),
            )
        return code

    def setup_identity(self, code: str) -> tuple[str, str] | None:
        now = int(time.time())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT github_user_id, github_login
                FROM setup_codes
                WHERE code_hash = ? AND used_at IS NULL AND expires_at >= ?
                """,
                (self._hash_code(code), now),
            ).fetchone()
        if row is None:
            return None
        return str(row["github_user_id"]), str(row["github_login"])

    def store_token(self, code: str, plane_token: str) -> tuple[str, str]:
        identity = self.setup_identity(code)
        if identity is None:
            raise ValueError("The setup link is invalid, expired, or already used")
        github_user_id, github_login = identity
        now = int(time.time())
        encrypted = self._fernet.encrypt(plane_token.encode("utf-8"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO credentials(
                    github_user_id, github_login, plane_token, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(github_user_id) DO UPDATE SET
                    github_login = excluded.github_login,
                    plane_token = excluded.plane_token,
                    updated_at = excluded.updated_at
                """,
                (github_user_id, github_login, encrypted, now, now),
            )
            updated = connection.execute(
                """
                UPDATE setup_codes SET used_at = ?
                WHERE code_hash = ? AND used_at IS NULL
                """,
                (now, self._hash_code(code)),
            )
            if updated.rowcount != 1:
                raise ValueError("The setup link was already used")
        return identity

    def get_token(self, github_user_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT plane_token FROM credentials WHERE github_user_id = ?",
                (github_user_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return self._fernet.decrypt(bytes(row["plane_token"])).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Stored Plane token cannot be decrypted") from exc

    def has_token(self, github_user_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM credentials WHERE github_user_id = ?",
                (github_user_id,),
            ).fetchone()
        return row is not None

    def revoke(self, github_user_id: str) -> bool:
        with self._connect() as connection:
            deleted = connection.execute(
                "DELETE FROM credentials WHERE github_user_id = ?",
                (github_user_id,),
            )
        return deleted.rowcount == 1
