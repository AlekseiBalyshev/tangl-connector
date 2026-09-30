import json
from pathlib import Path

from . import config

SCHEMA_VERSION = 1

COLUMNS = {
    "id": "VARCHAR",
    "guid": "VARCHAR",
    "name": "VARCHAR",
    "type": "VARCHAR",
    "category": "VARCHAR",
    "level_name": "VARCHAR",
    "level_elevation": "DOUBLE",
    "bbox_bottom": "DOUBLE",
    "bbox_top": "DOUBLE",
    "total_volume": "DOUBLE",
    "total_area": "DOUBLE",
    "pars": "JSON",
}


def _element(el: dict) -> dict:
    return (el.get("Meta") or {}).get("Element") or {}


def resolve_pars(el: dict, elements: list) -> dict:
    """Instance parameters plus type parameters pulled in through RefIdx."""
    raw = _element(el).get("Pars") or {}
    merged, ref = {}, {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict) and "RefIdx" in v:
                idx = v["RefIdx"]
                if isinstance(idx, int) and 0 <= idx < len(elements):
                    for rk, rv in (_element(elements[idx]).get("Pars") or {}).items():
                        if not (isinstance(rv, dict) and "RefIdx" in rv):
                            ref[rk] = rv
            else:
                merged[k] = v
    merged.update(ref)
    return merged


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def flatten(el: dict, elements: list) -> dict:
    meta_el = _element(el)
    level = meta_el.get("Level") if isinstance(meta_el.get("Level"), dict) else {}
    bounds = meta_el.get("Boundings") if isinstance(meta_el.get("Boundings"), dict) else {}
    mats = meta_el.get("Materials") or {}
    mat_iter = mats.values() if isinstance(mats, dict) else mats if isinstance(mats, list) else []
    vol = area = 0.0
    for m in mat_iter:
        if isinstance(m, dict):
            vol += _num(m.get("Volume")) or 0.0
            area += _num(m.get("Area")) or 0.0
    return {
        "id": None if el.get("Id") is None else str(el.get("Id")),
        "guid": el.get("Guid") or "",
        "name": el.get("Name") or "",
        "type": el.get("Type") or "",
        "category": el.get("Category") or "",
        "level_name": level.get("Name") or "",
        "level_elevation": _num(level.get("Elevation")),
        "bbox_bottom": _num(bounds.get("Bottom")),
        "bbox_top": _num(bounds.get("Top")),
        "total_volume": round(vol, 4) if vol else None,
        "total_area": round(area, 4) if area else None,
        "pars": resolve_pars(el, elements),
    }


def rows_from_meta(text: str) -> list:
    elements = json.loads(text)
    if not isinstance(elements, list):
        raise ValueError("unexpected model data format")
    return [flatten(el, elements) for el in elements if not el.get("IsRef")]


def cache_path(version_id: str) -> Path:
    safe = "".join(ch for ch in version_id if ch.isalnum() or ch == "-")
    return config.CACHE_DIR / f"elements_v{SCHEMA_VERSION}_{safe}.parquet"


def write_parquet(rows: list, path: Path):
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    ndjson = path.with_suffix(".ndjson")
    with open(ndjson, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    cols = ", ".join(f"'{k}': '{v}'" for k, v in COLUMNS.items())
    con = duckdb.connect()
    try:
        con.execute(
            f"COPY (SELECT * FROM read_json('{ndjson.as_posix()}', format='newline_delimited', "
            f"columns={{{cols}}})) TO '{path.as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        con.close()
        ndjson.unlink(missing_ok=True)


def ensure_cache(client, version_id: str) -> Path:
    path = cache_path(version_id)
    if not path.exists():
        write_parquet(rows_from_meta(client.model_meta(version_id)), path)
    return path


def connect(client, version_id: str, compare: str = ""):
    import duckdb

    con = duckdb.connect()
    tables = {"elements": version_id}
    if compare:
        tables["prev"] = compare
    for name, vid in tables.items():
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{ensure_cache(client, vid).as_posix()}')")
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con
