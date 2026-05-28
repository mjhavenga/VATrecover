from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


AUTH_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
CONNECTIONS_URL = "https://api.xero.com/connections"


@dataclass(frozen=True)
class XeroOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...] = (
        "offline_access",
        "accounting.transactions.read",
        "accounting.settings.read",
        "accounting.contacts.read",
    )


class FileTokenStore:
    """Small JSON token store for local practice-run tooling."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, token: dict[str, Any]) -> None:
        token = dict(token)
        token.setdefault("created_at", int(time.time()))
        if "expires_in" in token:
            token["expires_at"] = int(time.time()) + int(token["expires_in"]) - 60
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(token, indent=2), encoding="utf-8")


class XeroAuthClient:
    def __init__(self, config: XeroOAuthConfig, token_store: FileTokenStore):
        self.config = config
        self.token_store = token_store

    def authorization_url(self, state: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.config.client_id,
                "redirect_uri": self.config.redirect_uri,
                "scope": " ".join(self.config.scopes),
                "state": state,
            }
        )
        return f"{AUTH_URL}?{query}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        import requests

        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
            },
            auth=(self.config.client_id, self.config.client_secret),
            timeout=30,
        )
        response.raise_for_status()
        token = response.json()
        self.token_store.save(token)
        return token

    def refresh(self) -> dict[str, Any]:
        import requests

        token = self.token_store.load()
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("No refresh_token found. Complete the authorization code flow first.")
        response = requests.post(
            TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(self.config.client_id, self.config.client_secret),
            timeout=30,
        )
        response.raise_for_status()
        refreshed = response.json()
        self.token_store.save(refreshed)
        return refreshed

    def access_token(self) -> str:
        token = self.token_store.load()
        if not token:
            raise RuntimeError("No Xero token found. Complete the authorization code flow first.")
        if int(token.get("expires_at", 0)) <= int(time.time()):
            token = self.refresh()
        return str(token["access_token"])
