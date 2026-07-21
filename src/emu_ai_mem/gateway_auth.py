from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class GatewayOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """MCP OAuth provider delegating user identity and repository access to GitHub."""

    def __init__(
        self,
        *,
        db_path: Path,
        base_url: str,
        github_client_id: str,
        github_client_secret: str,
        encryption_key: str,
        github_allowlist: set[str] | None = None,
    ) -> None:
        self.db_path = db_path
        self.base_url = base_url.rstrip("/")
        self.github_client_id = github_client_id
        self.github_client_secret = github_client_secret
        self.fernet = Fernet(encryption_key.encode())
        self.github_allowlist = {item.casefold() for item in (github_allowlist or set())}
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self) -> None:
        db = self._connect()
        try:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS oauth_clients (
                    client_id TEXT PRIMARY KEY, document_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_transactions (
                    state TEXT PRIMARY KEY, client_id TEXT NOT NULL,
                    params_json TEXT NOT NULL, expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS authorization_codes (
                    code_hash TEXT PRIMARY KEY, document_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    token_hash TEXT PRIMARY KEY, token_type TEXT NOT NULL,
                    client_id TEXT NOT NULL, subject TEXT NOT NULL,
                    scopes_json TEXT NOT NULL, expires_at INTEGER NOT NULL,
                    resource TEXT, pair_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS github_accounts (
                    subject TEXT PRIMARY KEY, token_ciphertext BLOB NOT NULL,
                    refresh_ciphertext BLOB, expires_at INTEGER,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS github_vaults (
                    subject TEXT NOT NULL, name TEXT NOT NULL,
                    repository TEXT NOT NULL, kind TEXT NOT NULL,
                    default_vault INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(subject,name), UNIQUE(subject,repository)
                );
                """
            )
            account_columns = {
                str(row[1]) for row in db.execute("PRAGMA table_info(github_accounts)")
            }
            if "refresh_ciphertext" not in account_columns:
                db.execute("ALTER TABLE github_accounts ADD COLUMN refresh_ciphertext BLOB")
            if "expires_at" not in account_columns:
                db.execute("ALTER TABLE github_accounts ADD COLUMN expires_at INTEGER")
            db.commit()
        finally:
            db.close()

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT document_json FROM oauth_clients WHERE client_id=?", (client_id,)
            ).fetchone()
            return OAuthClientInformationFull.model_validate_json(row[0]) if row else None
        finally:
            db.close()

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            client_info.client_id = secrets.token_urlsafe(24)
        db = self._connect()
        try:
            db.execute(
                "INSERT OR REPLACE INTO oauth_clients VALUES(?,?)",
                (client_info.client_id, client_info.model_dump_json()),
            )
            db.commit()
        finally:
            db.close()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        state = secrets.token_urlsafe(32)
        db = self._connect()
        try:
            db.execute(
                "INSERT INTO auth_transactions VALUES(?,?,?,?)",
                (
                    state,
                    client.client_id,
                    params.model_dump_json(),
                    int(time.time()) + 600,
                ),
            )
            db.commit()
        finally:
            db.close()
        return "https://github.com/login/oauth/authorize?" + urlencode(
            {
                "client_id": self.github_client_id,
                "redirect_uri": f"{self.base_url}/oauth/github/callback",
                "scope": "read:user repo",
                "state": state,
            }
        )

    async def complete_github_authorization(self, code: str, state: str) -> str:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT * FROM auth_transactions WHERE state=? AND expires_at>?",
                (state, int(time.time())),
            ).fetchone()
            if not row:
                raise ValueError("Invalid or expired OAuth state")
            db.execute("DELETE FROM auth_transactions WHERE state=?", (state,))
            db.commit()
        finally:
            db.close()
        async with httpx.AsyncClient(timeout=20) as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.github_client_id,
                    "client_secret": self.github_client_secret,
                    "code": code,
                    "redirect_uri": f"{self.base_url}/oauth/github/callback",
                },
            )
            token_response.raise_for_status()
            github_grant = token_response.json()
            github_token = str(github_grant.get("access_token") or "")
            if not github_token:
                raise ValueError("GitHub did not return an access token")
            user_response = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {github_token}"},
            )
            user_response.raise_for_status()
            subject = str(user_response.json()["login"]).casefold()
        if self.github_allowlist and subject not in self.github_allowlist:
            raise ValueError("GitHub account is not in EMU_MEM_GATEWAY_GITHUB_ALLOWLIST")
        params = AuthorizationParams.model_validate_json(row["params_json"])
        authorization_code = AuthorizationCode(
            code=secrets.token_urlsafe(32),
            scopes=params.scopes or ["memory:read", "memory:write"],
            expires_at=time.time() + 300,
            client_id=str(row["client_id"]),
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            subject=subject,
        )
        db = self._connect()
        try:
            refresh_token = str(github_grant.get("refresh_token") or "")
            expires_in = github_grant.get("expires_in")
            expires_at = int(time.time()) + int(expires_in) if expires_in else None
            db.execute(
                "INSERT OR REPLACE INTO github_accounts "
                "(subject,token_ciphertext,refresh_ciphertext,expires_at,updated_at) "
                "VALUES(?,?,?,?,?)",
                (
                    subject,
                    self.fernet.encrypt(github_token.encode()),
                    self.fernet.encrypt(refresh_token.encode()) if refresh_token else None,
                    expires_at,
                    int(time.time()),
                ),
            )
            db.execute(
                "INSERT INTO authorization_codes VALUES(?,?)",
                (_digest(authorization_code.code), authorization_code.model_dump_json()),
            )
            db.commit()
        finally:
            db.close()
        query = {"code": authorization_code.code}
        original_state = params.state
        if original_state:
            query["state"] = original_state
        separator = "&" if "?" in str(params.redirect_uri) else "?"
        return str(params.redirect_uri) + separator + urlencode(query)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT document_json FROM authorization_codes WHERE code_hash=?",
                (_digest(authorization_code),),
            ).fetchone()
            if not row:
                return None
            result = AuthorizationCode.model_validate_json(row[0])
            return result if result.client_id == client.client_id else None
        finally:
            db.close()

    def _issue_tokens(
        self, *, client_id: str, subject: str, scopes: list[str], resource: str | None
    ) -> OAuthToken:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(40)
        pair_id = secrets.token_hex(16)
        now = int(time.time())
        db = self._connect()
        try:
            db.executemany(
                "INSERT INTO oauth_tokens VALUES(?,?,?,?,?,?,?,?)",
                [
                    (_digest(access), "access", client_id, subject, json.dumps(scopes), now + 3600, resource, pair_id),
                    (_digest(refresh), "refresh", client_id, subject, json.dumps(scopes), now + 2592000, resource, pair_id),
                ],
            )
            db.commit()
        finally:
            db.close()
        return OAuthToken(
            access_token=access,
            refresh_token=refresh,
            expires_in=3600,
            scope=" ".join(scopes),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        db = self._connect()
        try:
            db.execute(
                "DELETE FROM authorization_codes WHERE code_hash=?",
                (_digest(authorization_code.code),),
            )
            db.commit()
        finally:
            db.close()
        return self._issue_tokens(
            client_id=str(client.client_id),
            subject=str(authorization_code.subject),
            scopes=authorization_code.scopes,
            resource=authorization_code.resource,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        row = self._token_row(refresh_token, "refresh")
        if not row or row["client_id"] != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=row["client_id"],
            scopes=json.loads(row["scopes_json"]),
            expires_at=row["expires_at"],
            subject=row["subject"],
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        row = self._token_row(refresh_token.token, "refresh")
        if not row:
            raise ValueError("Invalid refresh token")
        self._revoke_pair(str(row["pair_id"]))
        granted = [scope for scope in scopes if scope in refresh_token.scopes] or refresh_token.scopes
        return self._issue_tokens(
            client_id=str(client.client_id),
            subject=str(refresh_token.subject),
            scopes=granted,
            resource=row["resource"],
        )

    def _token_row(self, token: str, token_type: str) -> sqlite3.Row | None:
        db = self._connect()
        try:
            row: sqlite3.Row | None = db.execute(
                "SELECT * FROM oauth_tokens WHERE token_hash=? AND token_type=? AND expires_at>?",
                (_digest(token), token_type, int(time.time())),
            ).fetchone()
            return row
        finally:
            db.close()

    async def load_access_token(self, token: str) -> AccessToken | None:
        row = self._token_row(token, "access")
        if not row:
            return None
        return AccessToken(
            token=token,
            client_id=row["client_id"],
            scopes=json.loads(row["scopes_json"]),
            expires_at=row["expires_at"],
            resource=row["resource"],
            subject=row["subject"],
        )

    def _revoke_pair(self, pair_id: str) -> None:
        db = self._connect()
        try:
            db.execute("DELETE FROM oauth_tokens WHERE pair_id=?", (pair_id,))
            db.commit()
        finally:
            db.close()

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        row = self._token_row(token.token, "access" if isinstance(token, AccessToken) else "refresh")
        if row:
            self._revoke_pair(str(row["pair_id"]))

    async def github_token(self, subject: str) -> str:
        db = self._connect()
        try:
            row = db.execute(
                "SELECT token_ciphertext,refresh_ciphertext,expires_at "
                "FROM github_accounts WHERE subject=?",
                (subject,),
            ).fetchone()
            if not row:
                raise ValueError("GitHub account is not connected")
            token = self.fernet.decrypt(bytes(row["token_ciphertext"])).decode()
            expires_at = row["expires_at"]
            if expires_at is None or int(expires_at) > int(time.time()) + 60:
                return token
            refresh_ciphertext = row["refresh_ciphertext"]
            if refresh_ciphertext is None:
                raise ValueError("GitHub authorization expired; reconnect the account")
            refresh_token = self.fernet.decrypt(bytes(refresh_ciphertext)).decode()
        finally:
            db.close()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.github_client_id,
                    "client_secret": self.github_client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
            response.raise_for_status()
            grant = response.json()
        access_token = str(grant.get("access_token") or "")
        rotated_refresh = str(grant.get("refresh_token") or refresh_token)
        expires_in = grant.get("expires_in")
        if not access_token or not expires_in:
            raise ValueError("GitHub token refresh returned an incomplete grant")
        db = self._connect()
        try:
            db.execute(
                "UPDATE github_accounts SET token_ciphertext=?,refresh_ciphertext=?,"
                "expires_at=?,updated_at=? WHERE subject=?",
                (
                    self.fernet.encrypt(access_token.encode()),
                    self.fernet.encrypt(rotated_refresh.encode()),
                    int(time.time()) + int(expires_in),
                    int(time.time()),
                    subject,
                ),
            )
            db.commit()
        finally:
            db.close()
        return access_token

    def configure_vault(self, subject: str, name: str, repository: str, kind: str) -> None:
        if kind not in {"personal", "team"}:
            raise ValueError("kind must be personal or team")
        db = self._connect()
        try:
            db.execute(
                "INSERT INTO github_vaults VALUES(?,?,?,?,?) "
                "ON CONFLICT(subject,name) DO UPDATE SET repository=excluded.repository,kind=excluded.kind",
                (subject, name, repository, kind, int(kind == "personal")),
            )
            db.commit()
        finally:
            db.close()

    def vaults(self, subject: str) -> list[dict[str, Any]]:
        db = self._connect()
        try:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT name,repository,kind,default_vault FROM github_vaults WHERE subject=? ORDER BY name",
                    (subject,),
                ).fetchall()
            ]
        finally:
            db.close()

    def subjects_for_repository(self, repository: str) -> list[str]:
        db = self._connect()
        try:
            return [
                str(row[0])
                for row in db.execute(
                    "SELECT subject FROM github_vaults WHERE repository=?", (repository,)
                ).fetchall()
            ]
        finally:
            db.close()
