# jenkins — релизный пайплайн стенда

Jenkins разворачивается Argo CD из [`gitops-infra/components/jenkins`](https://github.com/PonamaryovMV/gitops-infra/tree/main/components/jenkins).
Джоба `gitops-stand/app-release` создаётся через JCasC и берёт [`Jenkinsfile`](Jenkinsfile) из этого репозитория.

```
Параметры → Checkout gitops-main → Тесты → SCA (эмуляция) → Quality Gate → Publish
                                                                              │
                                     GitHub Actions (build.yaml) ◀────────────┘
                                              │
                                     ghcr.io/ponamaryovmv/<app>:<VERSION> ─▶ Kargo ─▶ dev → stage → prod
```

| Параметр | Что делает |
|---|---|
| `APP` | `hello-api` / `color-web` |
| `VERSION` | версия образа `X.Y.Z` |
| `SCA_PROFILE` | эмулируемый результат SCA: `clean`, `low`, `medium` — QG пройден; `high`, `critical` — нет |
| `PUBLISH` | после QG запустить сборку образа в GitHub Actions |

## Quality Gate

Политика — [`qg/policy.json`](qg/policy.json): блокирует релиз при любой `critical`/`high` и при `medium > 3`.

| Файл | Роль |
|---|---|
| `qg/smoke_test.py` | компиляция + запуск `app.py` + проверка `/version`, `/health`, `/ready` |
| `qg/sca_scan.py` | **эмуляция** SCA: состав по импортам и базовому образу, уязвимости `SIM-*` из каталога по профилю |
| `qg/quality_gate.py` | сравнивает сводку отчёта с лимитами, код выхода 1 → стадия падает |
| `qg/dispatch_build.py` | `workflow_dispatch` для `gitops-main/build.yaml` |

Отчёты (`reports/tests.json`, `sca.json`, `quality-gate.json`) архивируются в каждой сборке.
Формат отчёта SCA близок к реальным сканерам — эмулятор можно заменить настоящим (Trivy, Grype, Dependency-Track),
не трогая Quality Gate.

## Токен

Стадия `Publish` использует credential `github-token` (JCasC берёт его из секрета `jenkins/jenkins-github`,
который создаёт `scripts/windows/up.ps1` из `GITHUB_TOKEN`). Для запуска workflow токену нужны права:
classic — scope **`repo`**; fine-grained — **Actions: Read and write** на `gitops-main`.

## Сценарии

- `SCA_PROFILE=clean`, `PUBLISH=true` — образ собирается, Kargo везёт его в dev → stage.
- `SCA_PROFILE=high` — сборка падает на Quality Gate, образ не публикуется, Kargo ничего не видит.
