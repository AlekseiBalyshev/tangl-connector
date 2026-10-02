import glob
import os
from pathlib import Path

KEYS = (
    "TANGL_TOKEN",
    "TANGL_CLIENT_ID",
    "TANGL_CLIENT_SECRET",
    "TANGL_USERNAME",
    "TANGL_PASSWORD",
    "TANGL_COMPANY_ID",
    "TANGL_AUTH_URL",
    "TANGL_API_URL",
    "TANGL_MODEL_URL",
)

DEFAULTS = {
    "TANGL_AUTH_URL": "https://auth.tangl.cloud",
    "TANGL_API_URL": "https://platform.tangl.cloud",
    "TANGL_MODEL_URL": "https://value.tangl.cloud/models/viewer/{version_id}",
}

URL_KEYS = ("TANGL_AUTH_URL", "TANGL_API_URL", "TANGL_MODEL_URL")
TRUSTED_DOMAIN = "tangl.cloud"

HOME_DIR = Path(os.getenv("TANGL_HOME") or Path.home() / ".tangl-connector")
CREDENTIALS_FILE = HOME_DIR / "credentials.env"
CACHE_DIR = HOME_DIR / "cache"

UPLOAD_GLOBS = (
    "/mnt/user-data/uploads/*tangl*",
    "/mnt/user-data/uploads/*.env",
    "/mnt/data/*tangl*",
    "/mnt/data/*.env",
)


def parse_env_text(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip().lstrip("﻿")
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:]
        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key in KEYS and value:
            out[key] = value
    return out


def candidate_files() -> list:
    files = []
    explicit = os.getenv("TANGL_CREDENTIALS")
    if explicit:
        files.append(Path(explicit))
    files.append(CREDENTIALS_FILE)
    root = Path(__file__).resolve().parent.parent
    files += [root / ".env", Path.cwd() / ".env", Path.cwd() / "tangl.env"]
    for pattern in UPLOAD_GLOBS:
        files += [Path(p) for p in sorted(glob.glob(pattern))]
    seen, unique = set(), []
    for f in files:
        key = str(f)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def trusted_url(url: str) -> bool:
    from urllib.parse import urlparse

    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host == TRUSTED_DOMAIN or host.endswith("." + TRUSTED_DOMAIN))


def ensure_dirs():
    for d in (HOME_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass


def load() -> dict:
    """Environment first, then the first credential files that define each key.

    Server addresses outside tangl.cloud are accepted only from the environment,
    so a file in the chat cannot redirect the token to another host.
    """
    values, sources, ignored = {}, {}, []
    for key in KEYS:
        if os.getenv(key):
            values[key] = os.environ[key]
            sources[key] = "environment"
    for path in candidate_files():
        try:
            if not path.is_file() or path.stat().st_size > 64_000:
                continue
            found = parse_env_text(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        for key, value in found.items():
            if key in URL_KEYS and not trusted_url(value):
                ignored.append(key)
                continue
            if key not in values:
                values[key] = value
                sources[key] = str(path)
    for key, value in DEFAULTS.items():
        values.setdefault(key, value)
    values["_sources"] = sources
    values["_ignored"] = sorted(set(ignored))
    return values


def save(values: dict) -> Path:
    ensure_dirs()
    current = {}
    if CREDENTIALS_FILE.exists():
        current = parse_env_text(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    current.update({k: v for k, v in values.items()
                    if k in KEYS and v and (k not in URL_KEYS or trusted_url(v))})
    fd = os.open(CREDENTIALS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("".join(f"{k}={v}\n" for k, v in current.items()))
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except OSError:
        pass
    return CREDENTIALS_FILE


def auth_mode(values: dict) -> str:
    if values.get("TANGL_TOKEN"):
        return "token"
    if values.get("TANGL_CLIENT_ID") and values.get("TANGL_CLIENT_SECRET"):
        if values.get("TANGL_USERNAME") and values.get("TANGL_PASSWORD"):
            return "password"
        return "client_credentials"
    return "none"
