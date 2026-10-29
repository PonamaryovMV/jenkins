"""Quality Gate по SCA-отчёту.

Сравнивает число уязвимостей каждой серьёзности с лимитами из policy.json
(-1 — без ограничения). Пишет решение в JSON; код выхода 1, если гейт не пройден.
"""

import argparse
import json
import os
import sys

SEVERITIES = ("critical", "high", "medium", "low")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    report = json.load(open(args.report, encoding="utf-8"))
    policy = json.load(open(args.policy, encoding="utf-8"))
    limits = policy["maxVulnerabilities"]
    found = report["summary"]

    violations = []
    print(f"Quality Gate '{policy['name']}' для {report['target']['app']}:{report['target']['version']}")
    print(f"  {'severity':10} {'найдено':>8} {'лимит':>6}")
    for sev in SEVERITIES:
        limit = limits.get(sev, -1)
        n = found.get(sev, 0)
        bad = limit >= 0 and n > limit
        print(f"  {sev:10} {n:>8} {('∞' if limit < 0 else limit):>6}  {'✖' if bad else '✔'}")
        if bad:
            violations.append(f"{sev}: {n} > {limit}")

    status = "FAILED" if violations else "PASSED"
    summary = ", ".join(f"{s}={found.get(s, 0)}" for s in SEVERITIES)
    result = {
        "status": status,
        "policy": policy["name"],
        "summary": summary,
        "violations": violations,
        "emulated": report.get("emulated", False),
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Quality Gate: {status}" + (f" ({'; '.join(violations)})" if violations else ""))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
