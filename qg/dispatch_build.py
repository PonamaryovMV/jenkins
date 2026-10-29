"""Запускает сборку образа в GitHub Actions (workflow build.yaml в gitops-main).

Токен — переменная GH_TOKEN (в Jenkins: credential github-token).
Нужны права на запуск workflow: classic PAT со scope `repo`
или fine-grained с Actions: Read and write на gitops-main.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

REPO = "PonamaryovMV/gitops-main"
WORKFLOW = "build.yaml"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--ref", default="main")
    args = ap.parse_args()

    token = os.getenv("GH_TOKEN", "")
    if not token or token == "not-set":
        print("GH_TOKEN не задан: впишите GITHUB_TOKEN в scripts/.env и перезапустите up.ps1")
        return 1

    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches"
    body = json.dumps({"ref": args.ref, "inputs": {"app": args.app, "version": args.version}}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"GitHub Actions: сборка {args.app}:{args.version} запущена (HTTP {r.status})")
            print(f"https://github.com/{REPO}/actions/workflows/{WORKFLOW}")
            return 0
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        print(f"GitHub API вернул {e.code}: {detail}")
        if e.code in (401, 403, 404):
            print("Проверьте права токена: classic — scope `repo`; fine-grained — Actions: Read and write на gitops-main")
        return 1


if __name__ == "__main__":
    sys.exit(main())
