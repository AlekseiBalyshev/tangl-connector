import json

import pytest
import requests

from tangl_connector import config, meta, tools
from tangl_connector.client import Client, ReadOnlyError, ReadOnlySession


def _el(id_, guid, cat, typ, level, pars, vol=None, ref=None):
    p = dict(pars)
    if ref is not None:
        p["Тип"] = {"RefIdx": ref}
    mats = {"m": {"Volume": vol, "Area": 1}} if vol else {}
    return {"Id": id_, "Guid": guid, "Name": typ, "Type": typ, "Category": cat,
            "Meta": {"Element": {"Pars": p, "Level": {"Name": level, "Elevation": 0},
                                 "Boundings": {"Bottom": 0, "Top": 3000}, "Materials": mats}}}


META_V1 = [
    {"Id": 900, "IsRef": True, "Meta": {"Element": {"Pars": {"Код по классификатору": "W-01", "Толщина": 200}}}},
    _el(1, "g1", "Стены", "Стена 200 мм", "Этаж 1", {"Марка": "B25"}, vol=2.5, ref=0),
    _el(2, "g2", "Стены", "Стена 200 мм", "Этаж 1", {"Марка": ""}, vol=1.5, ref=0),
    _el(3, "g3", "Двери", "Дверь EI60", "Этаж 2", {}),
]
META_V2 = [META_V1[0], _el(1, "h1", "Стены", "Стена 250 мм", "Этаж 1", {"Марка": "B25"}, vol=2.5, ref=0),
           META_V1[3] | {"Guid": "h3"}, _el(4, "h4", "Окна", "Окно", "Этаж 2", {})]


@pytest.fixture
def models(home):
    for vid, data in (("v1", META_V1), ("v2", META_V2)):
        meta.write_parquet(meta.rows_from_meta(json.dumps(data)), meta.cache_path(vid))
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
    rows = meta.rows_from_meta(json.dumps(META_V1))
    assert len(rows) == 3
    assert rows[0]["pars"]["Код по классификатору"] == "W-01"
    assert rows[0]["pars"]["Марка"] == "B25"
    assert "Тип" not in rows[0]["pars"]
    assert rows[0]["total_volume"] == 2.5 and rows[0]["id"] == "1"


def test_query(models):
    r = tools.query("v1", "SELECT category, count(*) n, sum(total_volume) v FROM elements GROUP BY 1 ORDER BY 1")
    assert r["rows"] == [{"category": "Двери", "n": 1, "v": None}, {"category": "Стены", "n": 2, "v": 4.0}]
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
    assert r["rows"] == [{"added": 1, "removed": 1, "changed": 1}]


def test_model_schema(models):
    s = tools.model_schema("v1")
    assert s["elements"] == 3
    assert {c["category"] for c in s["categories"]} == {"Стены", "Двери"}
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
