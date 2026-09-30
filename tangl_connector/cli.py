import argparse
import sys

from . import tools
from .client import TanglError


def build_parser():
    p = argparse.ArgumentParser(prog="tangl", description="Tangl connector (read-only)")
    p.add_argument("--output-file", default="")
    sub = p.add_subparsers(dest="tool", required=True)

    sub.add_parser("status")

    s = sub.add_parser("login")
    s.add_argument("--file", default="")

    s = sub.add_parser("find_models")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--company", default="")
    s.add_argument("--versions", default="latest")
    s.add_argument("--sw", default="")
    s.add_argument("--uploader", default="")
    s.add_argument("--date-from", default="")
    s.add_argument("--date-to", default="")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--offset", type=int, default=0)

    s = sub.add_parser("model_schema")
    s.add_argument("version_id")
    s.add_argument("--category", default="")
    s.add_argument("--top", type=int, default=200)

    s = sub.add_parser("query")
    s.add_argument("version_id")
    s.add_argument("sql", nargs="?", default="")
    s.add_argument("--sql-file", default="")
    s.add_argument("--compare", default="")
    s.add_argument("--limit", type=int, default=1000)

    s = sub.add_parser("model_link")
    s.add_argument("version_id")
    return p


def run(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        if a.tool == "status":
            out = tools.status()
        elif a.tool == "login":
            out = tools.login(text="" if a.file else sys.stdin.read(), file=a.file)
        elif a.tool == "find_models":
            out = tools.find_models(a.query, a.company, a.versions, a.sw, a.uploader,
                                    a.date_from, a.date_to, a.limit, a.offset)
        elif a.tool == "model_schema":
            out = tools.model_schema(a.version_id, a.category, a.top)
        elif a.tool == "query":
            sql = a.sql
            if a.sql_file:
                with open(a.sql_file, encoding="utf-8") as f:
                    sql = f.read()
            elif sql == "-":
                sql = sys.stdin.read()
            out = tools.query(a.version_id, sql, a.compare, a.limit)
        else:
            out = tools.model_link(a.version_id)
    except TanglError as e:
        out = {"error": str(e)}
    tools.emit(out, a.output_file)
    return 1 if isinstance(out, dict) and "error" in out else 0
