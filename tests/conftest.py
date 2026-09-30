import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def home(tmp_path, monkeypatch):
    from tangl_connector import config

    monkeypatch.setattr(config, "HOME_DIR", tmp_path)
    monkeypatch.setattr(config, "CREDENTIALS_FILE", tmp_path / "credentials.env")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "UPLOAD_GLOBS", ())
    monkeypatch.chdir(tmp_path)
    for key in config.KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("TANGL_CREDENTIALS", raising=False)
    return tmp_path
