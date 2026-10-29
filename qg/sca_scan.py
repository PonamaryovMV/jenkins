"""ЭМУЛЯЦИЯ SCA (Software Composition Analysis).

Настоящего сканера нет: состав компонентов собирается по импортам app.py и базовому
образу, а уязвимости берутся из фиксированного каталога по выбранному профилю.
ID уязвимостей имеют префикс SIM- — это заведомо выдуманные записи.

Формат отчёта близок к тому, что отдают реальные SCA (компоненты + уязвимости + сводка),
поэтому Quality Gate можно потом переключить на настоящий сканер без переделки.
"""

import argparse
import ast
import datetime as dt
import json
import os
import sys

BASE_IMAGE = "python:3.14-slim"

# Выдуманный каталог уязвимостей: profile → список находок
CATALOG = {
    "low": [
        {"id": "SIM-2026-0101", "severity": "low", "component": "deb:libc6",
         "fixedIn": "2.41-12", "title": "Утечка информации в отладочном выводе"},
        {"id": "SIM-2026-0102", "severity": "low", "component": "deb:ncurses-base",
         "fixedIn": "6.5-3", "title": "Некорректная обработка terminfo"},
    ],
    "medium": [
        {"id": "SIM-2026-0201", "severity": "medium", "component": "deb:openssl",
         "fixedIn": "3.5.4-1", "title": "DoS при разборе специально сформированного сертификата"},
    ],
    "high": [
        {"id": "SIM-2026-0301", "severity": "high", "component": "python:http.server",
         "fixedIn": "3.14.1", "title": "Path traversal в обработчике статических файлов"},
    ],
    "critical": [
        {"id": "SIM-2026-0401", "severity": "critical", "component": "deb:zlib1g",
         "fixedIn": "1:1.3.1-2", "title": "RCE при распаковке повреждённого потока"},
    ],
}

# Какие группы находок попадают в отчёт при каждом профиле
PROFILES = {
    "clean": [],
    "low": ["low"],
    "medium": ["low", "medium"],
    "high": ["low", "medium", "high"],
    "critical": ["low", "medium", "high", "critical"],
}


def components_from_source(src_dir: str) -> list[dict]:
    """Компоненты: базовый образ + модули, импортируемые в app.py."""
    comps = [{"type": "container", "name": BASE_IMAGE}]
    app_py = os.path.join(src_dir, "app.py")
    try:
        tree = ast.parse(open(app_py, encoding="utf-8").read())
    except (OSError, SyntaxError) as e:
        print(f"  ! не удалось разобрать {app_py}: {e}")
        return comps
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    stdlib = getattr(sys, "stdlib_module_names", set())
    for m in sorted(modules):
        comps.append({"type": "python-stdlib" if m in stdlib else "python-package", "name": m})
    return comps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--profile", choices=list(PROFILES), default="clean")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    print(f"SCA (эмуляция) {args.app}:{args.version}, профиль '{args.profile}'")
    components = components_from_source(args.src)
    vulns = [v for group in PROFILES[args.profile] for v in CATALOG[group]]
    summary = {s: sum(v["severity"] == s for v in vulns) for s in ("critical", "high", "medium", "low")}

    report = {
        "tool": "sca-emulator",
        "emulated": True,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "target": {"app": args.app, "version": args.version, "baseImage": BASE_IMAGE},
        "profile": args.profile,
        "components": components,
        "vulnerabilities": vulns,
        "summary": summary,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"  компонентов: {len(components)}, уязвимостей: {len(vulns)}")
    for v in vulns:
        print(f"  [{v['severity'].upper():8}] {v['id']} {v['component']}: {v['title']} (fix: {v['fixedIn']})")
    print("  " + ", ".join(f"{k}={n}" for k, n in summary.items()))
    return 0  # решение принимает Quality Gate, сам скан не падает


if __name__ == "__main__":
    sys.exit(main())
