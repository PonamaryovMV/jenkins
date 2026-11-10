#!/usr/bin/env python3
"""Инструменты релизного флоу стенда (вызываются из Jenkinsfile'ов).

Подкоманды:
  images   — проверить, что образы сервисов есть в registry, и получить их digest
  sca      — ЭМУЛЯЦИЯ SCA по списку образов
  sast     — ЭМУЛЯЦИЯ SAST по списку репозиториев
  gate     — Quality Gate по отчётам SCA и SAST (policy.json)
  release  — записать release.yaml сервисов в ветку ФП одним коммитом (BuildRelease)
             + план выкатки по волнам release-plan.yaml (из deploy.dependsOn в values)
  plan     — только посчитать и показать план (проверка зависимостей без коммита)
  exclude  — исключить сервис из релиза: planned / urgent / clear (ExcludeService)
  dast     — ЭМУЛЯЦИЯ DAST по списку репозиториев (джоба DAST, её запускает Kargo)

Jenkins пишет только в git. В Kargo он не ходит.
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

# ФП берётся из окружения: Jenkinsfile выставляет FP по папке джобы (qa-at/BuildRelease → qa-at)
FP = os.getenv("FP", "qa-at")
AS, FS = FP.split("-", 1)
# Чьи образы использует ФП. На стенде у qa-bt своих образов нет — она берёт демо-образы qa-at
# (в values: main.container.imageFunctionalSystem: at).
IMAGE_FP = os.getenv("IMAGE_FP") or {"qa-bt": "qa-at"}.get(FP, FP)
COMPONENTS = ["api", "worker"]
REGISTRY = os.getenv("REGISTRY", "ghcr.io/ponamaryovmv")
SOURCE_ORG = os.getenv("SOURCE_ORG", "https://github.com/PonamaryovMV")
GITOPS_REPO = os.getenv("GITOPS_REPO", "https://github.com/PonamaryovMV/gitops-main.git")
GITOPS_PROD_REPO = os.getenv("GITOPS_PROD_REPO", "https://github.com/PonamaryovMV/gitops-prod.git")
FP_BRANCH = os.getenv("FP_BRANCH", FP)
SEVERITIES = ("critical", "high", "medium", "low")


# ---------------------------------------------------------------- утилиты
def log(msg: str) -> None:
    print(msg, flush=True)


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def services_arg(value: str) -> list:
    items = [s.strip() for s in value.replace(";", ",").split(",") if s.strip()]
    if not items:
        raise SystemExit("Не выбран ни один сервис")
    return items


def image(svc: str, comp: str, version: str) -> str:
    return f"{REGISTRY}/{IMAGE_FP}-{svc}-{comp}:{version}"


def source_repo(svc: str) -> str:
    return f"{SOURCE_ORG}/{FP}-{svc}"


def auth_url(url: str) -> str:
    """https://github.com/... → https://git:<token>@github.com/... (токен из GH_TOKEN)."""
    token = os.getenv("GH_TOKEN", "")
    if not token or not url.startswith("https://"):
        return url
    return url.replace("https://", f"https://git:{token}@", 1)


def git(*args, cwd=None, capture=False) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, check=True, text=True,
                         stdout=subprocess.PIPE if capture else None)
    return (res.stdout or "").strip() if capture else ""


def clone(url: str, branch: str, dest: str, full: bool = False) -> None:
    args = ["clone", "-q", "--branch", branch]
    if not full:
        args += ["--depth", "50"]
    git(*args, auth_url(url), dest)
    git("config", "user.name", "jenkins", cwd=dest)
    git("config", "user.email", "jenkins@stand.local", cwd=dest)


def commit_and_push(repo_dir: str, branch: str, message: str, attempts: int = 5) -> str:
    """Один коммит; при гонке с параллельной сборкой — rebase и повтор."""
    git("add", "-A", cwd=repo_dir)
    if not git("status", "--porcelain", cwd=repo_dir, capture=True):
        log("Изменений нет — коммит не нужен")
        return git("rev-parse", "HEAD", cwd=repo_dir, capture=True)
    git("commit", "-q", "-m", message, cwd=repo_dir)
    for i in range(1, attempts + 1):
        try:
            git("push", "-q", "origin", f"HEAD:{branch}", cwd=repo_dir)
            sha = git("rev-parse", "HEAD", cwd=repo_dir, capture=True)
            log(f"Запушено в {branch}: {sha}")
            return sha
        except subprocess.CalledProcessError:
            log(f"push отклонён (попытка {i}/{attempts}) — pull --rebase и повтор")
            time.sleep(2 * i)
            git("pull", "-q", "--rebase", "origin", branch, cwd=repo_dir)
    raise SystemExit("Не удалось запушить после нескольких попыток")


# ---------------------------------------------------------------- images
def registry_digest(ref: str) -> str:
    """digest образа в ghcr (анонимно, для публичных пакетов)."""
    host, rest = ref.split("/", 1)
    name, tag = rest.rsplit(":", 1)
    token_url = f"https://{host}/token?scope=repository:{name}:pull"
    token = json.load(urllib.request.urlopen(token_url, timeout=20))["token"]
    req = urllib.request.Request(
        f"https://{host}/v2/{name}/manifests/{tag}", method="HEAD",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": ", ".join([
                "application/vnd.oci.image.index.v1+json",
                "application/vnd.oci.image.manifest.v1+json",
                "application/vnd.docker.distribution.manifest.list.v2+json",
                "application/vnd.docker.distribution.manifest.v2+json",
            ]),
        })
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.headers["Docker-Content-Digest"]


def cmd_images(a) -> int:
    result, missing = {}, []
    for svc in services_arg(a.services):
        result[svc] = {"images": [], "digests": {}, "source": {"repo": source_repo(svc), "commit": a.version}}
        for comp in COMPONENTS:
            ref = image(svc, comp, a.version)
            try:
                digest = "sha256:offline" if a.offline else registry_digest(ref)
                log(f"  ✓ {ref}  {digest}")
                result[svc]["images"].append(ref)
                result[svc]["digests"][f"{IMAGE_FP}-{svc}-{comp}"] = digest
            except (urllib.error.URLError, KeyError, ValueError) as e:
                log(f"  ✖ {ref}: {e}")
                missing.append(ref)
    write_json(a.out, result)
    if missing:
        log(f"Образов нет в registry: {len(missing)}. Выберите существующую версию.")
        return 1
    return 0


# ---------------------------------------------------------------- SCA / SAST (эмуляция)
SCA_CATALOG = {
    "low": [{"id": "SIM-SCA-0101", "severity": "low", "component": "deb:libc6", "title": "Утечка информации в отладочном выводе"}],
    "medium": [{"id": "SIM-SCA-0201", "severity": "medium", "component": "deb:openssl", "title": "DoS при разборе сертификата"}],
    "high": [{"id": "SIM-SCA-0301", "severity": "high", "component": "python:http.server", "title": "Path traversal"}],
    "critical": [{"id": "SIM-SCA-0401", "severity": "critical", "component": "deb:zlib1g", "title": "RCE при распаковке"}],
}
SAST_CATALOG = {
    "low": [{"id": "SIM-SAST-11", "severity": "low", "rule": "py/unused-import", "title": "Неиспользуемый импорт"}],
    "medium": [{"id": "SIM-SAST-21", "severity": "medium", "rule": "py/weak-hash", "title": "Слабый алгоритм хеширования"}],
    "high": [{"id": "SIM-SAST-31", "severity": "high", "rule": "py/sql-injection", "title": "SQL-инъекция"}],
    "critical": [{"id": "SIM-SAST-41", "severity": "critical", "rule": "py/hardcoded-secret", "title": "Секрет в коде"}],
}
LEVELS = {"clean": [], "low": ["low"], "medium": ["low", "medium"],
          "high": ["low", "medium", "high"], "critical": ["low", "medium", "high", "critical"]}


def emulate(kind: str, catalog: dict, targets: list, profile: str, out: str, extra: dict) -> int:
    findings = []
    # находки привязываем к первому объекту проверки — для эмуляции этого достаточно
    for group in LEVELS[profile]:
        for f in catalog[group]:
            findings.append({**f, "target": targets[0] if targets else ""})
    summary = {s: sum(f["severity"] == s for f in findings) for s in SEVERITIES}
    report = {"tool": f"{kind}-emulator", "emulated": True, "profile": profile,
              "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "targets": targets, "findings": findings, "summary": summary, **extra}
    write_json(out, report)
    log(f"{kind.upper()} (эмуляция), профиль '{profile}', объектов: {len(targets)}")
    for t in targets:
        log(f"  · {t}")
    for f in findings:
        log(f"  [{f['severity'].upper():8}] {f['id']}: {f['title']}")
    log("  " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    return 0


def cmd_sca(a) -> int:
    data = read_json(a.images)
    images = [ref for svc in data.values() for ref in svc["images"]]
    return emulate("sca", SCA_CATALOG, images, a.profile, a.out, {})


def cmd_sast(a) -> int:
    data = read_json(a.images)
    repos = [f"{svc['source']['repo']}@{svc['source']['commit']}" for svc in data.values()]
    return emulate("sast", SAST_CATALOG, repos, a.profile, a.out, {})


def cmd_gate(a) -> int:
    policy = read_json(a.policy)
    verdict, violations = {}, []
    for kind, path in (("sca", a.sca), ("sast", a.sast)):
        found = read_json(path)["summary"]
        limits = policy[kind]
        log(f"Quality Gate {kind.upper()}:")
        for sev in SEVERITIES:
            limit, n = limits.get(sev, -1), found.get(sev, 0)
            bad = limit >= 0 and n > limit
            log(f"  {sev:9} найдено {n:>2}  лимит {('∞' if limit < 0 else limit):>2}  {'✖' if bad else '✔'}")
            if bad:
                violations.append(f"{kind} {sev}: {n} > {limit}")
        verdict[kind] = "FAILED" if any(v.startswith(kind) for v in violations) else "PASSED"
    result = {"status": "FAILED" if violations else "PASSED", "violations": violations, **verdict}
    write_json(a.out, result)
    log(f"Quality Gate: {result['status']}" + (f" ({'; '.join(violations)})" if violations else ""))
    return 1 if violations else 0


# ---------------------------------------------------------------- BuildRelease → ветка ФП
def release_doc(svc: str, version: str, info: dict, task: str, build: str, gate: dict) -> str:
    lines = [
        f"# Фиксирует версию сервиса. Пишет BuildRelease (ветка ФП {FP_BRANCH}), в окружения копирует Kargo.",
        "main:",
        "  container:",
        f"    registry: {REGISTRY}",
        f"    version: {version}",
        "",
        "list_image_build:",
        *[f"  - {ref}" for ref in info["images"]],
        "",
        "release:",
        f"  task: {task}",
        f"  build: {build}",
        "  source:",
        f"    repo: {info['source']['repo']}",
        f"    commit: {info['source']['commit']}",
        "  digests:",
        *[f"    {name}: \"{d}\"" for name, d in info["digests"].items()],
        "  checks:",
        f"    sca: {gate.get('sca', 'PASSED')}",
        f"    sast: {gate.get('sast', 'PASSED')}",
    ]
    return "\n".join(lines) + "\n"


def cmd_release(a) -> int:
    data, gate = read_json(a.images), read_json(a.gate)
    if gate["status"] != "PASSED":
        raise SystemExit("Quality Gate не пройден — в git ничего не пишем")
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "gitops")
        clone(a.repo, FP_BRANCH, repo)
        for svc, info in data.items():
            path = os.path.join(repo, AS, FS, svc, "release.yaml")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(release_doc(svc, a.version, info, a.task, a.build, gate))
            log(f"  {AS}/{FS}/{svc}/release.yaml → {a.version}")
        write_plan(repo, a.repo, a.prod_repo)
        parts = ", ".join(f"{svc} {a.version}" for svc in data)
        sha = commit_and_push(repo, FP_BRANCH, f"{a.task} ФП {AS}/{FS}: {parts} (build #{a.build}, SCA/SAST PASSED)")
    write_json(a.out, {"branch": FP_BRANCH, "commit": sha})
    return 0


# ---------------------------------------------------------------- ExcludeService
def read_yaml(path: str):
    import yaml  # pyyaml ставится в пайплайне: pip install pyyaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def cmd_exclude(a) -> int:
    import yaml  # pyyaml ставится в пайплайне: pip install pyyaml
    svc = a.service
    with tempfile.TemporaryDirectory() as tmp:
        prod = os.path.join(tmp, "prod")
        clone(a.prod_repo, "main", prod, full=True)
        prod_file = f"{AS}/{FS}/{svc}/prod/release.yaml"

        if a.mode == "planned":
            # новый Freight: в ветке ФП файл сервиса = то, что сейчас в PROD
            src = os.path.join(prod, prod_file)
            if not os.path.exists(src):
                raise SystemExit(f"В gitops-prod нет {prod_file}: сервис ещё не был в PROD, возвращать некуда")
            with open(src, encoding="utf-8") as f:
                content = f.read()
            prod_version = (yaml.safe_load(content) or {})["main"]["container"]["version"]
            repo = os.path.join(tmp, "gitops")
            clone(a.repo, FP_BRANCH, repo)
            dst = os.path.join(repo, AS, FS, svc, "release.yaml")
            rel_version = read_yaml(dst)["main"]["container"]["version"] if os.path.exists(dst) else None
            if rel_version == prod_version:
                # релиз уже доехал до PROD — берём то, что было в PROD до него
                last = git("log", "-n", "1", "--format=%H", "--", prod_file, cwd=prod, capture=True)
                try:
                    content = git("show", f"{last}^:{prod_file}", cwd=prod, capture=True) + "\n"
                except subprocess.CalledProcessError:
                    raise SystemExit(f"{svc}: в релизе та же версия, что в PROD ({prod_version}), и более ранней в gitops-prod нет — исключать нечего")
                prod_version = (yaml.safe_load(content) or {})["main"]["container"]["version"]
                log(f"Версия релиза уже в PROD — возвращаем к предыдущей версии PROD: {prod_version}")
            with open(dst, "w", encoding="utf-8") as f:
                f.write(content)
            write_plan(repo, a.repo, a.prod_repo)
            sha = commit_and_push(repo, FP_BRANCH,
                                  f"{a.task}: {svc} исключён из релиза ({a.reason}), возврат к {prod_version} (версия PROD)")
            log(f"Новый коммит в {FP_BRANCH}: {sha}. Kargo создаст Freight — проведите его uat → prod.")
            return 0

        excl_path = os.path.join(prod, AS, FS, "release-exclude.yaml")
        doc = read_yaml(excl_path) if os.path.exists(excl_path) else {}
        excluded = doc.get("excluded") or {}

        if a.mode == "urgent":
            # коммит, где файл сервиса последний раз менялся, и его родитель — состояние до релиза
            last = git("log", "-n", "1", "--format=%H", "--", prod_file, cwd=prod, capture=True)
            if not last:
                raise SystemExit(f"В истории gitops-prod нет {prod_file}")
            try:
                restore = git("rev-parse", f"{last}^", cwd=prod, capture=True)
            except subprocess.CalledProcessError:
                raise SystemExit("У последнего изменения нет родителя — откатывать некуда")
            prev = git("show", f"{restore}:{prod_file}", cwd=prod, capture=True)
            prev_version = (yaml.safe_load(prev) or {}).get("main", {}).get("container", {}).get("version", "?")
            excluded[svc] = {"task": a.task, "reason": a.reason, "restoreFrom": restore, "version": prev_version}
            message = f"{a.task}: срочное исключение {svc} из PROD ({a.reason}), возврат к {prev_version}"
            hint = "Теперь в Kargo повторите Promote текущего Freight в prod."
        else:  # clear
            if svc not in excluded:
                log(f"{svc} не исключён — делать нечего")
                return 0
            excluded.pop(svc)
            message = f"{a.task}: снято исключение {svc} из PROD"
            hint = "Следующий Promote в prod снова возьмёт сервис из Freight."

        header = ("# Срочное исключение сервисов из PROD (пишет Jenkins ExcludeService MODE=urgent, чистит MODE=clear).\n"
                  "# Kargo при промоушене в prod не переносит эти сервисы из Freight, а возвращает их файлы на коммит restoreFrom.\n")
        with open(excl_path, "w", encoding="utf-8") as f:
            f.write(header)
            yaml.safe_dump({"excluded": excluded}, f, allow_unicode=True, sort_keys=True, default_flow_style=False)
        commit_and_push(prod, "main", message)
        log(hint)
    return 0


# ---------------------------------------------------------------- план выкатки (волны)
# Разработчик в values окружения сервиса пишет:
#   deploy:
#     dependsOn: [api]
# Отсюда считается порядок: волна 1 — сервисы без зависимостей, волна 2 — те, чьи зависимости
# все в волне 1, и т.д. Kargo выкатывает волны по очереди: коммит волны → ждёт, пока её
# Deployment'ы выкатились с нужной версией и готовы → следующая волна.
def build_waves(services: list, deps: dict) -> list:
    """deps: {сервис: [зависимости]} → [[сервисы волны 1], [сервисы волны 2], ...]."""
    from graphlib import TopologicalSorter, CycleError
    for svc, ds in deps.items():
        unknown = sorted(set(ds) - set(services))
        if unknown:
            raise SystemExit(f"{svc}: в deploy.dependsOn сервисы не из ФП {AS}/{FS}: {', '.join(unknown)}")
    ts = TopologicalSorter({s: deps.get(s, []) for s in services})
    try:
        ts.prepare()
    except CycleError as e:
        raise SystemExit(f"Зависимости по кругу: {' → '.join(e.args[1])}. Исправьте deploy.dependsOn в values")
    waves = []
    while ts.is_active():
        ready = sorted(ts.get_ready())
        waves.append(ready)
        ts.done(*ready)
    return waves


def env_dependencies(repo_dir: str) -> dict:
    """{окружение: {сервис: [зависимости]}} из values <АС>-<ФП>-<сервис>-<окр>.yaml."""
    result = {}
    base = os.path.join(repo_dir, AS, FS)
    if not os.path.isdir(base):
        return result
    for svc in sorted(os.listdir(base)):
        svc_dir = os.path.join(base, svc)
        if not os.path.isdir(svc_dir):
            continue
        for env in sorted(os.listdir(svc_dir)):
            values = os.path.join(svc_dir, env, f"{FP}-{svc}-{env}.yaml")
            if os.path.isfile(values):
                doc = read_yaml(values)
                result.setdefault(env, {})[svc] = list(((doc.get("deploy") or {}).get("dependsOn")) or [])
    return result


def compute_plan(branch_dir: str, main_repo: str, prod_repo: str) -> dict:
    """{окружение: [{сервис: версия}, ...]} — версии из ветки ФП, зависимости из main gitops-main/gitops-prod."""
    base = os.path.join(branch_dir, AS, FS)
    versions = {}
    for svc in sorted(os.listdir(base)):
        rel = os.path.join(base, svc, "release.yaml")
        if os.path.isfile(rel):
            versions[svc] = read_yaml(rel)["main"]["container"]["version"]
    deps = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, url in (("main", main_repo), ("prod", prod_repo)):
            d = os.path.join(tmp, name)
            git("clone", "-q", "--depth", "1", "--branch", "main", auth_url(url), d)
            deps.update(env_dependencies(d))
    plan = {}
    for env, env_deps in deps.items():
        services = [s for s in versions if s in env_deps]
        waves = build_waves(services, {s: env_deps[s] for s in services})
        plan[env] = [{s: versions[s] for s in wave} for wave in waves]
    return plan


def plan_doc(plan: dict) -> str:
    order = {"dev": 0, "test": 1, "uat": 2, "prod": 9}
    lines = [
        f"# План выкатки ФП {AS}/{FS} по волнам. Генерирует Jenkins из deploy.dependsOn в values окружений —",
        "# руками не править. Kargo выкатывает волны по очереди: следующая начинается, когда сервисы",
        "# предыдущей выкатились с этой версией и готовы.",
    ]
    for env in sorted(plan, key=lambda e: (order.get(e, 5), e)):
        lines.append(f"{env}:")
        for i, wave in enumerate(plan[env], 1):
            items = ", ".join(f"{s}: {v}" for s, v in wave.items())
            lines.append(f"  - {{ {items} }}   # волна {i}")
    return "\n".join(lines) + "\n"


# Сколько волн умеет стадия Kargo (строки wave1..waveN в kargo/<ФП>/stages.yaml)
MAX_WAVES = int(os.getenv("MAX_WAVES", "3"))


def write_plan(branch_dir: str, main_repo: str, prod_repo: str) -> None:
    plan = compute_plan(branch_dir, main_repo, prod_repo)
    too_long = {env: len(w) for env, w in plan.items() if len(w) > MAX_WAVES}
    if too_long:
        raise SystemExit(f"Волн больше, чем шагов wave в стадиях Kargo ({MAX_WAVES}): {too_long}. "
                         "Добавьте строки wave в kargo/<ФП>/stages.yaml и поднимите MAX_WAVES")
    path = os.path.join(branch_dir, AS, FS, "release-plan.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(plan_doc(plan))
    log("План выкатки (волны):")
    for env, waves in plan.items():
        log(f"  {env}: " + "  →  ".join("[" + ", ".join(w) + "]" for w in waves))


def cmd_plan(a) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "gitops")
        clone(a.repo, FP_BRANCH, repo)
        log(plan_doc(compute_plan(repo, a.repo, a.prod_repo)))
    return 0


# ---------------------------------------------------------------- DAST (эмуляция)
def cmd_dast(a) -> int:
    repos = [r.strip() for r in a.repos.split(",") if r.strip()]
    fail = {r.strip() for r in a.fail_repos.split(",") if r.strip()}
    log(f"DAST (эмуляция) окружение={a.environment} релиз={a.release}")
    bad = []
    for r in repos:
        time.sleep(1)
        failed = any(f in r for f in fail)
        log(f"  {'✖' if failed else '✔'} {r}" + ("  SIM-DAST-501 XSS в форме поиска" if failed else ""))
        if failed:
            bad.append(r)
    write_json(a.out, {"environment": a.environment, "release": a.release, "repos": repos, "failed": bad,
                       "status": "FAILED" if bad else "PASSED", "emulated": True})
    log(f"DAST: {'FAILED' if bad else 'PASSED'}")
    return 1 if bad else 0


# ---------------------------------------------------------------- CLI
def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("images"); s.add_argument("--services", required=True); s.add_argument("--version", required=True)
    s.add_argument("--out", required=True); s.add_argument("--offline", action="store_true"); s.set_defaults(fn=cmd_images)

    for name, fn in (("sca", cmd_sca), ("sast", cmd_sast)):
        s = sub.add_parser(name); s.add_argument("--images", required=True)
        s.add_argument("--profile", choices=list(LEVELS), default="clean"); s.add_argument("--out", required=True); s.set_defaults(fn=fn)

    s = sub.add_parser("gate"); s.add_argument("--sca", required=True); s.add_argument("--sast", required=True)
    s.add_argument("--policy", required=True); s.add_argument("--out", required=True); s.set_defaults(fn=cmd_gate)

    s = sub.add_parser("release"); s.add_argument("--images", required=True); s.add_argument("--gate", required=True)
    s.add_argument("--version", required=True); s.add_argument("--task", required=True); s.add_argument("--build", required=True)
    s.add_argument("--repo", default=GITOPS_REPO); s.add_argument("--prod-repo", default=GITOPS_PROD_REPO)
    s.add_argument("--out", required=True); s.set_defaults(fn=cmd_release)

    s = sub.add_parser("plan"); s.add_argument("--repo", default=GITOPS_REPO); s.add_argument("--prod-repo", default=GITOPS_PROD_REPO)
    s.set_defaults(fn=cmd_plan)

    s = sub.add_parser("exclude"); s.add_argument("--mode", choices=["planned", "urgent", "clear"], required=True)
    s.add_argument("--service", required=True); s.add_argument("--task", required=True); s.add_argument("--reason", default="")
    s.add_argument("--repo", default=GITOPS_REPO); s.add_argument("--prod-repo", default=GITOPS_PROD_REPO); s.set_defaults(fn=cmd_exclude)

    s = sub.add_parser("dast"); s.add_argument("--repos", required=True); s.add_argument("--environment", default="")
    s.add_argument("--release", default=""); s.add_argument("--fail-repos", default=""); s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_dast)

    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
