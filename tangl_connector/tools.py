import json
import re
import socket
import sys
from collections import Counter
from urllib.parse import urlparse

from . import __version__, config, meta
from .client import Client, TanglError

MAX_ROWS = 5000


def _hosts(cfg: dict) -> list:
    return sorted({urlparse(cfg[k]).hostname for k in ("TANGL_AUTH_URL", "TANGL_API_URL") if cfg.get(k)})


def status() -> dict:
    cfg = config.load()
    mode = config.auth_mode(cfg)
    out = {"version": __version__, "auth_mode": mode, "network_ok": True, "auth_ok": False,
           "duckdb_ok": True, "hints": []}
    try:
        import duckdb  # noqa: F401
    except ImportError:
        out["duckdb_ok"] = False
        out["hints"].append("Не установлен пакет duckdb: выполни `pip install duckdb`.")
    for host in _hosts(cfg):
        try:
            socket.create_connection((host, 443), timeout=8).close()
        except OSError:
            out["network_ok"] = False
    if not out["network_ok"]:
        out["hints"].append(
            "Нет выхода в сеть к " + ", ".join(_hosts(cfg)) + ". Добавь эти адреса в список "
            "разрешённых доменов (Claude: Settings → Capabilities → Allow network egress)."
        )
    if mode == "none":
        out["hints"].append("Нет данных для входа. Попроси у пользователя файл tangl.env и вызови `login`.")
    elif out["network_ok"]:
        c = Client(cfg)
        if c.authenticate():
            out["auth_ok"] = True
            try:
                out["companies"] = [
                    {"id": x.get("id"), "name": x.get("name"), "personal": bool(x.get("isPersonal"))}
                    for x in c.companies()
                ]
            except TanglError:
                out["companies"] = [{"id": i} for i in c.company_ids()]
        else:
            out["auth_error"] = c.last_error
            out["hints"].append(_auth_hint(mode, c.last_error))
    out["all_ok"] = out["network_ok"] and out["auth_ok"] and out["duckdb_ok"]
    return out


def _auth_hint(mode: str, error: str) -> str:
    if mode == "client_credentials" and error == "unauthorized_client":
        return ("Этот клиент API не поддерживает вход без пользователя. "
                "Добавь в tangl.env TANGL_USERNAME и TANGL_PASSWORD.")
    if error in ("invalid_grant",):
        return "Неверный логин или пароль Tangl."
    if error in ("invalid_client",):
        return "Неверные TANGL_CLIENT_ID / TANGL_CLIENT_SECRET."
    if mode == "token":
        return "Токен не принят: проверь, что он не истёк и не отозван."
    return f"Не удалось войти в Tangl: {error}."


def login(text: str = "", file: str = "") -> dict:
    if file:
        with open(file, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    values = config.parse_env_text(text or "")
    if not values:
        return {"error": "в тексте нет строк вида TANGL_...=значение"}
    path = config.save(values)
    result = status()
    result["saved_keys"] = sorted(values)
    result["saved_to"] = str(path)
    return result


def _versions_filter(versions, uploader, date_from, date_to):
    out = []
    for v in versions:
        date = str(v.get("date") or "")
        if uploader and uploader.lower() not in str(v.get("lastModifiedEmail") or "").lower():
            continue
        if date_from and date < date_from:
            continue
        if date_to and date[:len(date_to)] > date_to:
            continue
        out.append(v)
    return out


def find_models(query="", company="", versions="latest", sw="", uploader="",
                date_from="", date_to="", limit=20, offset=0) -> dict:
    c = Client()
    c.ensure_token()
    names = {}
    try:
        names = {x["id"]: x.get("name") for x in c.companies() if x.get("id")}
    except TanglError:
        pass
    ids = c.company_ids()
    if company:
        q = company.lower()
        ids = [i for i in ids if q == i.lower() or q in str(names.get(i, "")).lower()]
        if not ids:
            return {"error": f"компания «{company}» не найдена", "companies": names}

    q = (query or "").lower().strip()
    rows, scanned = [], 0
    for cid in ids:
        try:
            models = c.models(cid)
        except TanglError:
            continue
        scanned += len(models)
        for m in models:
            if m.get("isDeleted"):
                continue
            if sw and sw.lower() not in str(m.get("sw") or "").lower():
                continue
            vers = m.get("versions") or []
            if q and not (q in str(m.get("name") or "").lower() or q == str(m.get("id")).lower()
                          or any(q == str(v.get("id")).lower() for v in vers)):
                continue
            passing = _versions_filter(vers, uploader, date_from, date_to)
            if not passing:
                continue
            ordered = sorted(passing, key=lambda v: v.get("versionIndex", 0), reverse=True)
            if versions == "latest":
                chosen = ordered[:1]
            elif versions == "all":
                chosen = ordered
            else:
                try:
                    chosen = [v for v in ordered if v.get("versionIndex") == int(versions)]
                except ValueError:
                    return {"error": "versions: latest | all | номер версии"}
            latest = ordered[0].get("versionIndex")
            for v in chosen:
                rows.append({
                    "model": m.get("name"),
                    "model_id": m.get("id"),
                    "company": names.get(cid, cid),
                    "sw": m.get("sw"),
                    "version": v.get("versionIndex"),
                    "is_latest": v.get("versionIndex") == latest,
                    "version_id": v.get("id"),
                    "date": v.get("date"),
                    "uploader": v.get("lastModifiedEmail"),
                    "description": v.get("desc"),
                    "elements": v.get("totalElementsCount"),
                    "link": c.viewer_url(v.get("id")),
                })
    rows.sort(key=lambda r: (str(r["model"]).lower(), -(r["version"] or 0)))
    page = rows[offset:offset + limit]
    out = {"models_scanned": scanned, "total_matches": len(rows), "returned": len(page), "items": page}
    if len(rows) > offset + len(page):
        out["note"] = f"Показано {len(page)} из {len(rows)}; следующая страница: --offset {offset + len(page)}."
    by_name = {}
    for r in rows:
        by_name.setdefault(r["model"], set()).add(r["sw"])
    mixed = sorted(n for n, s in by_name.items() if len({x for x in s if x}) > 1)
    if mixed:
        out["warning"] = ("Под одним именем есть модели из разных источников (RVT и IFC): "
                          + ", ".join(mixed) + ". Это разные наборы данных, уточни у пользователя.")
    return out


def model_schema(version_id: str, category: str = "", top: int = 200) -> dict:
    c = Client()
    con = meta.connect(c, version_id)
    where, params = "", []
    if category:
        where, params = "WHERE lower(category) LIKE ?", [f"%{category.lower()}%"]
    total = con.execute(f"SELECT count(*) FROM elements {where}", params).fetchone()[0]
    cats = con.execute(
        f"SELECT category, count(*) n, round(sum(total_volume), 3) volume_m3, round(sum(total_area), 3) area_m2 "
        f"FROM elements {where} GROUP BY 1 ORDER BY n DESC", params).fetchall()
    levels = con.execute(
        f"SELECT level_name, any_value(level_elevation) elevation, count(*) n FROM elements {where} "
        f"GROUP BY 1 ORDER BY elevation NULLS LAST", params).fetchall()
    filled, examples = Counter(), {}
    for (pars,) in con.execute(f"SELECT pars FROM elements {where}", params).fetchall():
        for k, v in (json.loads(pars) if pars else {}).items():
            if v not in (None, "", [], {}):
                filled[k] += 1
                if k not in examples and not isinstance(v, (dict, list)):
                    examples[k] = v
    parameters = [
        {"name": k, "filled": n, "filled_pct": round(100 * n / total, 1) if total else 0,
         "example": examples.get(k)}
        for k, n in filled.most_common(top)
    ]
    return {
        "version_id": version_id,
        "category_filter": category or None,
        "elements": total,
        "categories": [{"category": a, "elements": b, "volume_m3": v, "area_m2": s} for a, b, v, s in cats],
        "levels": [{"level": a, "elevation": b, "elements": n} for a, b, n in levels],
        "parameters_total": len(filled),
        "parameters": parameters,
        "link": c.viewer_url(version_id),
    }


_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|COPY|ATTACH|DETACH|INSTALL|LOAD|PRAGMA|EXPORT|IMPORT|SET|RESET|CALL|CHECKPOINT|VACUUM)\b",
    re.IGNORECASE,
)


def _strip_literals(sql: str) -> str:
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r'"(?:[^"]|"")*"', '""', sql)
    return re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)


def is_read_only(sql: str) -> bool:
    bare = _strip_literals(sql).strip().lstrip("(").lstrip()
    if not re.match(r"(SELECT|WITH|FROM)\b", bare, re.IGNORECASE):
        return False
    if ";" in bare.rstrip().rstrip(";"):
        return False
    return not _FORBIDDEN.search(bare)


def query(version_id: str, sql: str, compare: str = "", limit: int = 1000) -> dict:
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        return {"error": "пустой запрос"}
    if not is_read_only(sql):
        return {"error": "разрешены только запросы на чтение (SELECT / WITH)"}
    limit = max(1, min(int(limit), MAX_ROWS))
    c = Client()
    con = meta.connect(c, version_id, compare=compare)
    try:
        cur = con.execute(f"SELECT * FROM ({sql}) q LIMIT {limit + 1}")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        return {"error": str(e).splitlines()[0], "sql": sql}
    truncated = len(rows) > limit
    out = {"version_id": version_id, "columns": cols, "row_count": min(len(rows), limit),
           "truncated": truncated, "rows": rows[:limit]}
    if compare:
        out["compare_version_id"] = compare
    if truncated:
        out["note"] = f"Показаны первые {limit} строк. Сузь запрос или агрегируй."
    return out


def model_link(version_id: str) -> dict:
    return {"version_id": version_id, "link": Client().viewer_url(version_id)}


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def emit(obj, output_file: str = ""):
    text = dump(obj)
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(text)
        print(json.dumps({"saved": output_file}, ensure_ascii=False))
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
