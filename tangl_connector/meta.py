import json
import os
import re
from pathlib import Path

from . import config

SCHEMA_VERSION = 2
DEFAULT_MAX_ELEMENTS = 200_000

SERVICE_CATEGORIES = {
    "камеры", "уровни", "оси", "виды", "листы", "сведения о проекте", "линии",
    "cameras", "levels", "grids", "views", "sheets", "project information", "lines",
    "ifcgrid", "ifcannotation", "ifcbuildingstorey", "ifcsite", "ifcbuilding", "ifcproject",
}

_CONCRETE = re.compile(r"бетон|concrete|ж/?б", re.IGNORECASE)
_CLASS = re.compile(r"(?<![0-9A-Za-zА-Яа-яЁё])[ВB]\s?(\d{1,3}(?:[.,]\d{1,2})?)(?![0-9])")

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
    "service": "BOOLEAN",
    "pars": "JSON",
}

MATERIAL_COLUMNS = {
    "id": "VARCHAR",
    "category": "VARCHAR",
    "type": "VARCHAR",
    "level_name": "VARCHAR",
    "level_elevation": "DOUBLE",
    "material": "VARCHAR",
    "concrete_class": "VARCHAR",
    "volume": "DOUBLE",
    "area": "DOUBLE",
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


def concrete_class(material: str):
    """«Бетон В25 W6 F150» -> «В25»; None for non-concrete materials."""
    if not material or not _CONCRETE.search(material):
        return None
    m = _CLASS.search(material)
    return f"В{m.group(1)}" if m else None


def _materials(meta_el: dict) -> list:
    mats = meta_el.get("Materials") or {}
    items = mats.items() if isinstance(mats, dict) else enumerate(mats) if isinstance(mats, list) else []
    out = []
    for key, m in items:
        if not isinstance(m, dict):
            continue
        name = m.get("Material") or m.get("Имя") or m.get("Name") or (key if not str(key).isdigit() else "")
        out.append((str(name or ""), _num(m.get("Volume")), _num(m.get("Area"))))
    return out


def flatten(el: dict, elements: list):
    """Returns (element row, material rows)."""
    meta_el = _element(el)
    level = meta_el.get("Level") if isinstance(meta_el.get("Level"), dict) else {}
    bounds = meta_el.get("Boundings") if isinstance(meta_el.get("Boundings"), dict) else {}
    mats = _materials(meta_el)
    vol = sum(v or 0.0 for _, v, _ in mats)
    area = sum(a or 0.0 for _, _, a in mats)
    category = el.get("Category") or ""
    row = {
        "id": None if el.get("Id") is None else str(el.get("Id")),
        "guid": el.get("Guid") or "",
        "name": el.get("Name") or "",
        "type": el.get("Type") or "",
        "category": category,
        "level_name": level.get("Name") or "",
        "level_elevation": _num(level.get("Elevation")),
        "bbox_bottom": _num(bounds.get("Bottom")),
        "bbox_top": _num(bounds.get("Top")),
        "total_volume": round(vol, 4) if vol else None,
        "total_area": round(area, 4) if area else None,
        "service": category.strip().lower() in SERVICE_CATEGORIES,
        "pars": resolve_pars(el, elements),
    }
    mrows = [{
        "id": row["id"], "category": category, "type": row["type"],
        "level_name": row["level_name"], "level_elevation": row["level_elevation"],
        "material": name, "concrete_class": concrete_class(name),
        "volume": round(v, 6) if v else None, "area": round(a, 6) if a else None,
    } for name, v, a in mats]
    return row, mrows


def rows_from_meta(text: str):
    """(elements, materials) rows of a tangl-meta document."""
    elements = json.loads(text)
    if not isinstance(elements, list):
        raise ValueError("unexpected model data format")
    rows, mats = [], []
    for el in elements:
        if el.get("IsRef"):
            continue
        r, m = flatten(el, elements)
        rows.append(r)
        mats += m
    return rows, mats


def _safe(version_id: str) -> str:
    return "".join(ch for ch in version_id if ch.isalnum() or ch == "-")


def cache_path(version_id: str, table: str = "elements") -> Path:
    return config.CACHE_DIR / f"{table}_v{SCHEMA_VERSION}_{_safe(version_id)}.parquet"


def write_parquet(rows: list, path: Path, columns: dict = None):
    import duckdb

    columns = columns or COLUMNS
    path.parent.mkdir(parents=True, exist_ok=True)
    ndjson = path.with_suffix(".ndjson")
    with open(ndjson, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    cols = ", ".join(f"'{k}': '{v}'" for k, v in columns.items())
    con = duckdb.connect()
    try:
        con.execute(
            f"COPY (SELECT * FROM read_json('{ndjson.as_posix()}', format='newline_delimited', "
            f"columns={{{cols}}})) TO '{path.as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        con.close()
        ndjson.unlink(missing_ok=True)


def write_cache(version_id: str, text: str):
    rows, mats = rows_from_meta(text)
    write_parquet(mats, cache_path(version_id, "materials"), MATERIAL_COLUMNS)
    write_parquet(rows, cache_path(version_id), COLUMNS)


class ModelTooLarge(Exception):
    pass


def max_elements() -> int:
    try:
        return int(os.getenv("TANGL_MAX_ELEMENTS") or DEFAULT_MAX_ELEMENTS)
    except ValueError:
        return DEFAULT_MAX_ELEMENTS


def check_size(info: dict):
    n = (info or {}).get("elements") or 0
    if n > max_elements():
        raise ModelTooLarge(
            f"В версии {n:,} элементов – больше, чем помещается в память среды ({max_elements():,}). "
            "Выбери модель отдельного раздела или секции, а не сводную."
            .replace(",", " ")
        )


def ensure_cache(client, version_id: str) -> Path:
    path = cache_path(version_id)
    if not path.exists() or not cache_path(version_id, "materials").exists():
        check_size(client.version_info(version_id))
        write_cache(version_id, client.model_meta(version_id))
    return path


def connect(client, version_id: str, compare: str = ""):
    import duckdb

    con = duckdb.connect()
    tables = {"": version_id}
    if compare:
        tables["prev"] = compare
    for prefix, vid in tables.items():
        ensure_cache(client, vid)
        for table in ("elements", "materials"):
            name = f"{prefix}_{table}" if prefix and table != "elements" else (prefix or table)
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{cache_path(vid, table).as_posix()}')")
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con
