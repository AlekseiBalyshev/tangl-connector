import json

import pytest
import requests

from tangl_connector import config, meta, tools
from tangl_connector.client import Client, ReadOnlyError, ReadOnlySession


def _el(id_, guid, cat, typ, level, pars, vol=None, ref=None):
    p = dict(pars)
    if ref is not None:
        p["Тип"] = {"RefIdx": ref}
    mats = {"0": {"Material": pars.get("_mat", "Бетон В25 W6 F150"), "Volume": vol, "Area": 1}} if vol else {}
    p.pop("_mat", None)
    return {"Id": id_, "Guid": guid, "Name": typ, "Type": typ, "Category": cat,
            "Meta": {"Element": {"Pars": p, "Level": {"Name": level, "Elevation": 0},
                                 "Boundings": {"Bottom": 0, "Top": 3000}, "Materials": mats}}}


META_V1 = [
    {"Id": 900, "IsRef": True, "Meta": {"Element": {"Pars": {"Код по классификатору": "W-01", "Толщина": 200}}}},
    _el(1, "g1", "Стены", "Стена 200 мм", "Этаж 1", {"Марка": "B25"}, vol=2.5, ref=0),
    _el(2, "g2", "Стены", "Стена 200 мм", "Этаж 1", {"Марка": "", "_mat": "Бетон B30"}, vol=1.5, ref=0),
    _el(3, "g3", "Двери", "Дверь EI60", "Этаж 2", {}),
    _el(5, "g5", "Камеры", "3D вид", "", {}),
    _el(6, "g6", "Перекрытия", "Плита", "Этаж 2", {"_mat": "Бетон В25 W6 F150"}, vol=4.0),
]
META_V2 = [META_V1[0], _el(1, "h1", "Стены", "Стена 250 мм", "Этаж 1", {"Марка": "B25"}, vol=2.5, ref=0),
           META_V1[3] | {"Guid": "h3"}, _el(4, "h4", "Окна", "Окно", "Этаж 2", {})]


@pytest.fixture
def models(home):
    for vid, data in (("v1", META_V1), ("v2", META_V2)):
        meta.write_cache(vid, json.dumps(data))
    Client().save_index({"v1": {"model": "Demo", "version": 1, "date": "2026-01-01", "elements": 5},
                         "v2": {"model": "Demo", "version": 2, "date": "2026-02-01", "elements": 3}})
    return home


def test_parse_env_text():
    text = "﻿# c\nexport TANGL_USERNAME = 'user@example.com'\nTANGL_PASSWORD=p=ss\nOTHER=1\nTANGL_TOKEN=\n"
    assert config.parse_env_text(text) == {"TANGL_USERNAME": "user@example.com", "TANGL_PASSWORD": "p=ss"}


def test_auth_mode():
    assert config.auth_mode({}) == "none"
    assert config.auth_mode({"TANGL_TOKEN": "x"}) == "token"
    assert config.auth_mode({"TANGL_CLIENT_ID": "a", "TANGL_CLIENT_SECRET": "b"}) == "client_credentials"
    assert config.auth_mode({"TANGL_CLIENT_ID": "a", "TANGL_CLIENT_SECRET": "b",
                             "TANGL_USERNAME": "u", "TANGL_PASSWORD": "p"}) == "password"


def test_save_and_load(home, monkeypatch):
    config.save({"TANGL_TOKEN": "abc", "JUNK": "x"})
    assert config.load()["TANGL_TOKEN"] == "abc"
    monkeypatch.setenv("TANGL_TOKEN", "env")
    assert config.load()["TANGL_TOKEN"] == "env"
    assert "JUNK" not in config.CREDENTIALS_FILE.read_text()


def test_login_rejects_empty(home):
    assert "error" in tools.login(text="hello")


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_readonly_session_blocks_writes(method):
    with pytest.raises(ReadOnlyError):
        ReadOnlySession().request(method, "https://platform.tangl.cloud/api/app/metaModels/zip")


def test_readonly_session_allows_token(monkeypatch):
    called = {}
    monkeypatch.setattr(requests.Session, "request", lambda self, m, u, *a, **k: called.setdefault("url", u))
    ReadOnlySession().request("POST", "https://auth.tangl.cloud/connect/token")
    assert called["url"].endswith("/connect/token")


@pytest.mark.parametrize("sql,ok", [
    ("SELECT * FROM elements", True),
    ("with a as (select 1) select * from a", True),
    ("SELECT 'drop table x' AS s", True),
    ('SELECT "update" FROM elements', True),
    ("DROP TABLE elements", False),
    ("SELECT 1; DROP TABLE elements", False),
    ("COPY elements TO 'x.csv'", False),
    ("SELECT 1 /* */ ; ATTACH 'x'", False),
    ("PRAGMA version", False),
])
def test_is_read_only(sql, ok):
    assert tools.is_read_only(sql) is ok


def test_flatten_resolves_type_params():
    rows, mats = meta.rows_from_meta(json.dumps(META_V1))
    assert len(rows) == 5 and len(mats) == 3
    assert rows[0]["pars"]["Код по классификатору"] == "W-01"
    assert rows[0]["pars"]["Марка"] == "B25"
    assert "Тип" not in rows[0]["pars"]
    assert rows[0]["total_volume"] == 2.5 and rows[0]["id"] == "1"


def test_query(models):
    r = tools.query("v1", "SELECT category, count(*) n, sum(total_volume) v FROM elements GROUP BY 1 ORDER BY 1")
    assert r["rows"][-1] == {"category": "Стены", "n": 2, "v": 4.0}
    assert r["source"]["text"] == "модель «Demo», версия 1 от 2026-01-01"
    r = tools.query("v1", "SELECT id FROM elements WHERE json_extract_string(pars, '$.\"Код по классификатору\"') = 'W-01'")
    assert sorted(x["id"] for x in r["rows"]) == ["1", "2"]


def test_query_limit(models):
    r = tools.query("v1", "SELECT * FROM elements", limit=2)
    assert r["truncated"] and r["row_count"] == 2


def test_query_no_file_access(models):
    r = tools.query("v1", "SELECT * FROM read_csv('/etc/hosts')")
    assert "error" in r


def test_query_compare(models):
    sql = ("SELECT count(*) FILTER (WHERE p.id IS NULL) added, count(*) FILTER (WHERE e.id IS NULL) removed, "
           "count(*) FILTER (WHERE e.id = p.id AND e.type <> p.type) changed "
           "FROM elements e FULL OUTER JOIN prev p ON e.id = p.id")
    r = tools.query("v2", sql, compare="v1")
    assert r["rows"] == [{"added": 1, "removed": 3, "changed": 1}]


def test_model_schema(models):
    s = tools.model_schema("v1")
    assert s["elements"] == 5 and s["service_elements"] == 1
    assert {c["category"] for c in s["categories"]} == {"Стены", "Двери", "Камеры", "Перекрытия"}
    assert {m["concrete_class"] for m in s["materials"]} == {"В25", "В30"}
    fill = {p["name"]: p["filled"] for p in s["parameters"]}
    assert fill["Код по классификатору"] == 2 and fill["Марка"] == 1
    assert s["link"].endswith("/v1")


def test_model_link(home, monkeypatch):
    assert tools.model_link("abc")["link"] == "https://value.tangl.cloud/models/viewer/abc"
    monkeypatch.setenv("TANGL_MODEL_URL", "https://example.com/m/{version_id}?x=1")
    assert tools.model_link("abc")["link"] == "https://example.com/m/abc?x=1"


def test_token_mode_no_network(home, monkeypatch):
    monkeypatch.setenv("TANGL_TOKEN", "Bearer abc")
    c = Client()
    assert c.authenticate() and c.token == "abc"


def test_status_rejects_bad_token(home, monkeypatch):
    import socket

    class Resp:
        status_code, content, headers = 401, b"", {}

    monkeypatch.setenv("TANGL_TOKEN", "bad")
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: type("S", (), {"close": lambda self: None})())
    monkeypatch.setattr(ReadOnlySession, "get", lambda self, *a, **k: Resp())
    s = tools.status()
    assert s["auth_ok"] is False and not s["all_ok"]
    assert any("Персональные токены" in h for h in s["hints"])


def test_concrete_by_level_and_class(models):
    sql = ("SELECT level_name, concrete_class, round(sum(volume), 2) v FROM materials "
           "WHERE category IN ('Стены', 'Перекрытия') GROUP BY ALL ORDER BY 1, 2")
    r = tools.query("v1", sql)
    assert r["rows"] == [{"level_name": "Этаж 1", "concrete_class": "В25", "v": 2.5},
                         {"level_name": "Этаж 1", "concrete_class": "В30", "v": 1.5},
                         {"level_name": "Этаж 2", "concrete_class": "В25", "v": 4.0}]


@pytest.mark.parametrize("name,expected", [
    ("N Бетон В25 W6 F150", "В25"), ("Бетон B22,5", "В22,5"), ("Concrete B30", "В30"),
    ("Бетон кл. В 15", "В15"), ("ЖБ В40", "В40"), ("Арматура A500C", None),
    ("Кирпич М150", None), ("Бетон", None), ("Стекло B25", None),
])
def test_concrete_class(name, expected):
    assert meta.concrete_class(name) == expected


def test_service_filter(models):
    r = tools.query("v1", "SELECT count(*) n FROM elements WHERE NOT service")
    assert r["rows"] == [{"n": 4}]


def test_compare_materials(models):
    r = tools.query("v2", "SELECT (SELECT count(*) FROM materials) a, (SELECT count(*) FROM prev_materials) b", compare="v1")
    assert r["rows"] == [{"a": 1, "b": 3}]
    assert r["compare_source"]["version"] == 1


def test_size_guard(home, monkeypatch):
    c = Client()
    c.save_index({"big": {"model": "Big", "version": 1, "elements": 400_000}})
    called = []
    monkeypatch.setattr(Client, "model_meta", lambda self, vid: called.append(vid))
    with pytest.raises(meta.ModelTooLarge, match="400 000 элементов – больше, чем"):
        meta.ensure_cache(c, "big")
    assert called == []
    monkeypatch.setenv("TANGL_MAX_ELEMENTS", "500000")
    meta.check_size({"elements": 400_000})


def test_status_port(home, monkeypatch):
    import socket

    seen = []
    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout=0: seen.append(addr) or type("S", (), {"close": lambda self: None})())
    monkeypatch.setenv("TANGL_AUTH_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("TANGL_API_URL", "https://tangl.local")
    s = tools.status()
    assert s["network_ok"] and sorted(seen) == [("127.0.0.1", 8765), ("tangl.local", 443)]


def test_clean(models):
    config.save({"TANGL_TOKEN": "x"})
    r = tools.clean()
    assert r["removed_files"] >= 4 and config.CREDENTIALS_FILE.exists()
    tools.clean(everything=True)
    assert not config.CREDENTIALS_FILE.exists()


def test_file_cannot_redirect_hosts(home, monkeypatch):
    (home / "tangl.env").write_text(
        "TANGL_TOKEN=t\nTANGL_API_URL=https://evil.example.com\nTANGL_AUTH_URL=https://auth.tangl.cloud.evil.io\n",
        encoding="utf-8")
    cfg = config.load()
    assert cfg["TANGL_TOKEN"] == "t"
    assert cfg["TANGL_API_URL"] == "https://platform.tangl.cloud"
    assert cfg["TANGL_AUTH_URL"] == "https://auth.tangl.cloud"
    assert cfg["_ignored"] == ["TANGL_API_URL", "TANGL_AUTH_URL"]
    monkeypatch.setenv("TANGL_API_URL", "http://tangl.local:8080")
    assert config.load()["TANGL_API_URL"] == "http://tangl.local:8080"


def test_login_skips_foreign_hosts(home):
    config.save({"TANGL_TOKEN": "t", "TANGL_API_URL": "https://evil.example.com"})
    text = config.CREDENTIALS_FILE.read_text()
    assert "evil" not in text and "TANGL_TOKEN=t" in text


def test_private_permissions(home):
    import os
    import stat

    config.save({"TANGL_TOKEN": "t"})
    assert stat.S_IMODE(os.stat(config.CREDENTIALS_FILE).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(config.HOME_DIR).st_mode) == 0o700
