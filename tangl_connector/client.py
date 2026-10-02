import base64
import hashlib
import json
import lzma
import os
import time
from typing import Optional

import requests

from . import config


class TanglError(Exception):
    pass


class ReadOnlyError(TanglError):
    pass


_ALLOWED_WRITES = ("/connect/token",)


class ReadOnlySession(requests.Session):
    """Only GET/HEAD requests leave the process; token endpoint is the sole exception."""

    def request(self, method, url, *args, **kwargs):
        m = str(method).upper()
        if m not in ("GET", "HEAD", "OPTIONS"):
            path = requests.utils.urlparse(str(url)).path
            if not any(path.endswith(p) for p in _ALLOWED_WRITES):
                raise ReadOnlyError(f"read-only connector: {m} {path} is not allowed")
        return super().request(method, url, *args, **kwargs)


def decode_jwt(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _fix_trailing_comma(text: str) -> str:
    text = text.rstrip()
    if text.endswith(",]"):
        return text[:-2] + "]"
    if text.endswith(",}"):
        return text[:-2] + "}"
    return text


class Client:
    def __init__(self, values: Optional[dict] = None):
        self.cfg = values if values is not None else config.load()
        self.mode = config.auth_mode(self.cfg)
        self.auth_url = self.cfg["TANGL_AUTH_URL"].rstrip("/")
        self.api_url = self.cfg["TANGL_API_URL"].rstrip("/")
        self.hosts = {"auth": self.auth_url, "platform": self.api_url}
        self.session = ReadOnlySession()
        self.session.verify = os.getenv("TANGL_VERIFY_SSL", "true").lower() not in ("0", "false", "no")
        self.token: Optional[str] = None
        self.expiry = 0.0
        self.last_error: Optional[str] = None

    def _identity(self) -> str:
        raw = "|".join(self.cfg.get(k, "") for k in ("TANGL_TOKEN", "TANGL_CLIENT_ID", "TANGL_USERNAME"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _cache_file(self):
        return config.CACHE_DIR / f"token_{self._identity()}.json"

    def _load_cached(self) -> bool:
        try:
            data = json.loads(self._cache_file().read_text(encoding="utf-8"))
        except Exception:
            return False
        if data.get("expires_at", 0) > time.time() + 60:
            self.token, self.expiry = data["access_token"], data["expires_at"]
            return True
        return False

    def _save_cached(self):
        try:
            config.ensure_dirs()
            f = self._cache_file()
            f.write_text(json.dumps({"access_token": self.token, "expires_at": self.expiry}), encoding="utf-8")
            os.chmod(f, 0o600)
        except OSError:
            pass

    def _drop_token(self):
        self.token, self.expiry = None, 0.0
        try:
            self._cache_file().unlink()
        except OSError:
            pass

    def authenticate(self) -> bool:
        self.last_error = None
        if self.mode == "none":
            self.last_error = "no credentials"
            return False
        if self.mode == "token":
            self.token = self.cfg["TANGL_TOKEN"].strip()
            if self.token.lower().startswith("bearer "):
                self.token = self.token[7:].strip()
            exp = decode_jwt(self.token).get("exp")
            self.expiry = float(exp) if exp else time.time() + 10 * 365 * 86400
            return True
        data = {
            "client_id": self.cfg["TANGL_CLIENT_ID"],
            "client_secret": self.cfg["TANGL_CLIENT_SECRET"],
        }
        if self.mode == "password":
            data.update(grant_type="password", username=self.cfg["TANGL_USERNAME"],
                        password=self.cfg["TANGL_PASSWORD"])
        else:
            data.update(grant_type="client_credentials")
        try:
            resp = self.session.post(f"{self.auth_url}/connect/token", data=data, timeout=20)
        except requests.RequestException as e:
            self.last_error = f"network: {e.__class__.__name__}"
            return False
        if resp.status_code != 200:
            try:
                self.last_error = resp.json().get("error") or f"HTTP {resp.status_code}"
            except ValueError:
                self.last_error = f"HTTP {resp.status_code}"
            return False
        body = resp.json()
        self.token = body.get("access_token")
        self.expiry = time.time() + int(body.get("expires_in", 3600)) - 60
        self._save_cached()
        return bool(self.token)

    def ensure_token(self):
        if self.token and self.expiry > time.time():
            return
        if self.mode != "token" and self._load_cached():
            return
        if not self.authenticate():
            raise TanglError(f"authentication failed: {self.last_error}")

    def get(self, endpoint: str, host: str = "platform", timeout: int = 60, raw: bool = False, **kwargs):
        self.ensure_token()
        url = f"{self.hosts.get(host, host)}{endpoint}"
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = self.session.get(url, headers=headers, timeout=timeout, **kwargs)
            if resp.status_code == 401 and attempt == 1 and self.mode != "token":
                self._drop_token()
                self.ensure_token()
                continue
            break
        if resp.status_code == 401 and self.mode == "token":
            raise TanglError("HTTP 401: персональный токен не принят (истёк или удалён)")
        if resp.status_code >= 400:
            raise TanglError(f"GET {endpoint} -> HTTP {resp.status_code}")
        if raw:
            return resp.content
        if not resp.content:
            return None
        if "json" in resp.headers.get("Content-Type", ""):
            return resp.json()
        return resp.text

    def companies(self) -> list:
        data = self.get("/api/app/company", host="auth")
        return data if isinstance(data, list) else []

    def company_ids(self) -> list:
        if self.cfg.get("TANGL_COMPANY_ID"):
            return [c.strip() for c in self.cfg["TANGL_COMPANY_ID"].split(",") if c.strip()]
        try:
            ids = [c["id"] for c in self.companies() if c.get("id")]
        except TanglError:
            ids = []
        if not ids:
            claim = decode_jwt(self.token or "").get("company_id") or []
            ids = [claim] if isinstance(claim, str) else list(claim)
        return ids

    def models(self, company_id: str) -> list:
        data = self.get(f"/api/app/metaModelsList/{company_id}")
        return data if isinstance(data, list) else []

    def model_meta(self, version_id: str) -> str:
        """tangl-meta JSON of a version (LZMA, base64-wrapped or raw on /stream)."""
        params = {"storageType": "tangl-meta"}
        try:
            content = self.get(f"/api/app/metaModelsData/{version_id}", params=params, timeout=180, raw=True)
            b64 = json.loads(content)
            if isinstance(b64, str):
                return _fix_trailing_comma(lzma.decompress(base64.b64decode(b64)).decode("utf-8"))
        except (TanglError, ValueError, lzma.LZMAError):
            pass
        content = self.get(f"/api/app/metaModelsData/{version_id}/stream", params=params, timeout=300, raw=True)
        try:
            text = lzma.decompress(content).decode("utf-8")
        except lzma.LZMAError:
            text = lzma.decompress(base64.b64decode(json.loads(content))).decode("utf-8")
        return _fix_trailing_comma(text)

    def _index_file(self):
        return config.CACHE_DIR / f"versions_{self._identity()}.json"

    def load_index(self) -> dict:
        try:
            return json.loads(self._index_file().read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_index(self, entries: dict):
        index = self.load_index()
        index.update(entries)
        try:
            config.ensure_dirs()
            self._index_file().write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def index_entries(model: dict, company: str = "") -> dict:
        return {
            v.get("id"): {
                "model": model.get("name"),
                "model_id": model.get("id"),
                "version": v.get("versionIndex"),
                "sw": model.get("sw"),
                "date": v.get("date"),
                "company": company,
                "elements": v.get("elementsCount") or v.get("totalElementsCount"),
            }
            for v in model.get("versions") or [] if v.get("id")
        }

    def version_info(self, version_id: str) -> dict:
        info = self.load_index().get(version_id)
        if info:
            return info
        entries = {}
        for cid in self.company_ids():
            try:
                for m in self.models(cid):
                    entries.update(self.index_entries(m, cid))
            except TanglError:
                continue
        self.save_index(entries)
        return entries.get(version_id) or {}

    def viewer_url(self, version_id: str) -> str:
        return self.cfg["TANGL_MODEL_URL"].replace("{version_id}", version_id)
