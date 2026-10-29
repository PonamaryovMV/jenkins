"""Смоук-тест приложения: компиляция + запуск + проверка эндпоинтов.

Запускает app.py на свободном порту и проверяет /version, /health, /ready.
Пишет отчёт в JSON; код выхода != 0, если хоть одна проверка упала.
"""

import argparse
import json
import os
import py_compile
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="путь к app.py")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    checks = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        print(f"  [{'OK' if ok else 'FAIL'}] {name} {detail}")

    try:
        py_compile.compile(args.src, doraise=True)
        check("compile", True)
    except py_compile.PyCompileError as e:
        check("compile", False, str(e))

    port = free_port()
    env = dict(os.environ, PORT=str(port), APP_VERSION="0.0.0-test")
    proc = subprocess.Popen([sys.executable, args.src], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                get(f"{base}/ready")
                break
            except OSError:
                time.sleep(0.1)
        status, body = get(f"{base}/version")
        check("/version", status == 200 and body.get("version") == "0.0.0-test", f"status={status}")
        status, body = get(f"{base}/health")
        check("/health", status == 200 and body.get("status") == "ok", f"status={status}")
        status, _ = get(f"{base}/ready")
        check("/ready", status == 200, f"status={status}")
    except OSError as e:
        check("http", False, str(e))
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    passed = all(c["ok"] for c in checks)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"passed": passed, "checks": checks}, f, ensure_ascii=False, indent=2)
    print(f"Тесты: {'пройдены' if passed else 'упали'} ({sum(c['ok'] for c in checks)}/{len(checks)})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
