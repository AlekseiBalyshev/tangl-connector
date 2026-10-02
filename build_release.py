#!/usr/bin/env python3
"""Stamp the version and build release artifacts.

    python build_release.py --version 0.1.0 --date 2026-09-30            # stamp only
    python build_release.py --version 0.1.0 --date 2026-09-30 --build    # + releases/v0.1.0_2026-09-30/
    python build_release.py --version 0.1.0 --date 2026-09-30 --build --out dist
"""

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILL_NAME = "tangl-connector"
SKILL_FILES = ["SKILL.md", "tangl.py", "LICENSE"]
SKILL_DIRS = ["tangl_connector", "references"]
STAMPED = ["SKILL.md", "USER_GUIDE.md"]
VERSION_LINE = re.compile(r"^\*\*Версия:\*\* .*$", re.M)


def parse_version(v: str) -> tuple:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", v)
    if not m:
        raise SystemExit(f"bad version: {v}")
    return tuple(int(x) for x in m.groups())


def released_versions(ref: str = "origin/main") -> list:
    subprocess.run(["git", "fetch", "-q", "origin", ref.split("/", 1)[1]], cwd=ROOT, check=False)
    res = subprocess.run(["git", "ls-tree", "--name-only", f"{ref}:releases"], cwd=ROOT,
                         capture_output=True, text=True)
    found = []
    for name in res.stdout.split():
        m = re.match(r"v(\d+\.\d+\.\d+)_", name)
        if m:
            found.append(parse_version(m.group(1)))
    return sorted(found)


def allowed_next(last: tuple) -> set:
    a, b, c = last
    return {(a, b, c + 1), (a, b + 1, 0), (a + 1, 0, 0)}


def check_version(version: str, released: list):
    new = parse_version(version)
    if not released:
        return
    last = released[-1]
    if new not in allowed_next(last):
        options = ", ".join(".".join(map(str, v)) for v in sorted(allowed_next(last)))
        raise SystemExit(f"version {version} does not follow {'.'.join(map(str, last))} on main; use one of: {options}")


def stamp(version: str, date: str):
    line = f"**Версия:** v{version} · {date}"
    for name in STAMPED:
        p = ROOT / name
        text = p.read_text(encoding="utf-8")
        if not VERSION_LINE.search(text):
            raise SystemExit(f"no version line in {name}")
        p.write_text(VERSION_LINE.sub(line, text, count=1), encoding="utf-8")
    init = ROOT / "tangl_connector" / "__init__.py"
    init.write_text(f'__version__ = "{version}"\n', encoding="utf-8")


def tracked_files() -> list:
    res = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True)
    files = [ROOT / f for f in res.stdout.split("\n") if f]
    return files or [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]


def check_stopwords(files) -> list:
    sw_file = ROOT / ".stopwords"
    if not sw_file.exists():
        return []
    words = [w.strip().lower() for w in sw_file.read_text(encoding="utf-8").splitlines()
             if w.strip() and not w.startswith("#")]
    hits = []
    for f in files:
        if f.name == ".stopwords" or not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8").lower()
        except (UnicodeDecodeError, OSError):
            continue
        hits += [f"{f.relative_to(ROOT)}: {w}" for w in words if w in text]
    return hits


def skill_files() -> list:
    files = [ROOT / f for f in SKILL_FILES]
    for d in SKILL_DIRS:
        files += sorted(p for p in (ROOT / d).rglob("*")
                        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    return files


def build_zip(version: str, out: Path) -> Path:
    path = out / f"{SKILL_NAME}-skill-v{version}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in skill_files():
            z.write(f, f"{SKILL_NAME}/{f.relative_to(ROOT).as_posix()}")
    return path


def build_pdf(version: str, out: Path):
    try:
        from markdown_pdf import MarkdownPdf, Section
    except ImportError:
        print("markdown-pdf not installed, PDF skipped (pip install markdown-pdf)", file=sys.stderr)
        return None
    text = (ROOT / "USER_GUIDE.md").read_text(encoding="utf-8")
    text = text.replace("](../../releases", "](https://github.com/AlekseiBalyshev/tangl-connector/releases")
    pdf = MarkdownPdf(toc_level=2)
    pdf.add_section(Section(text))
    pdf.meta["title"] = "Tangl Connector – руководство пользователя"
    path = out / f"{SKILL_NAME}-user-guide-v{version}.pdf"
    pdf.save(str(path))
    return path


INSTALL = """## Установка в 4 шага

Нужны платный тариф Claude (Pro, Max, Team или Enterprise) и платная лицензия Tangl: коннектор работает через API Tangl и персональные токены.

1. **Токен.** В Tangl откройте «Персональные токены» → «Создать токен», скопируйте токен и сохраните в текстовый файл `tangl.env` одной строкой: `TANGL_TOKEN=ваш_токен`
2. **Настройки Claude.** [Settings → Capabilities](https://claude.ai/settings/capabilities): включите *Code execution and file creation* и *Allow network egress*, добавьте домены `auth.tangl.cloud` и `platform.tangl.cloud`.
3. **Навык.** Скачайте `{zip}` ниже, в разделе *Assets*, и загрузите: Settings → Capabilities → Skills → *Upload skill*.
4. **Проект.** Создайте проект в Claude, добавьте в его файлы `tangl.env` и спросите: *«Проверь подключение к Tangl»*.

Подробная инструкция с примерами – `{pdf}` ниже или [USER_GUIDE.md](https://github.com/AlekseiBalyshev/tangl-connector/blob/main/USER_GUIDE.md).
"""


def changelog_section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## v{re.escape(version)}\b.*?$\n(.*?)(?=^## v|\Z)", text, re.M | re.S)
    if not m:
        raise SystemExit(f"no CHANGELOG section for v{version}")
    return m.group(1).strip()


def release_notes(version: str) -> str:
    zip_name = f"{SKILL_NAME}-skill-v{version}.zip"
    pdf_name = f"{SKILL_NAME}-user-guide-v{version}.pdf"
    return (INSTALL.format(zip=zip_name, pdf=pdf_name)
            + "\n## Что нового\n\n" + changelog_section(version) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--skip-version-check", action="store_true")
    a = ap.parse_args()

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
        raise SystemExit(f"bad date: {a.date}")
    if not a.skip_version_check:
        check_version(a.version, released_versions())
    stamp(a.version, a.date)

    hits = check_stopwords(tracked_files() + skill_files())
    if hits:
        raise SystemExit("stop-words found:\n  " + "\n  ".join(hits))

    if not a.build:
        print(f"stamped v{a.version}")
        return
    out = Path(a.out) if a.out else ROOT / "releases" / f"v{a.version}_{a.date}"
    out.mkdir(parents=True, exist_ok=True)
    made = [build_zip(a.version, out), build_pdf(a.version, out)]
    shutil.copy(ROOT / "CHANGELOG.md", out / "CHANGELOG.md")
    (out / "RELEASE_NOTES.md").write_text(release_notes(a.version), encoding="utf-8")
    for p in filter(None, made):
        print(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p)


if __name__ == "__main__":
    main()
