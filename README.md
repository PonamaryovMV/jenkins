# jenkins — пайплайны релиза ФП qa/at

Jenkins разворачивается Argo CD из [gitops-infra/components/jenkins](https://github.com/PonamaryovMV/gitops-infra/tree/main/components/jenkins),
джобы создаются JCasC в папке **qa-at**. UI: http://jenkins.

Контроллер — свой образ `ghcr.io/ponamaryovmv/jenkins-controller:2.580.2-jdk25` ([controller/](controller)):
плагины ([controller/plugins.txt](controller/plugins.txt)) уже внутри, при старте Jenkins в интернет за ними не ходит.
Новый плагин: добавить строку в `plugins.txt` → push → workflow `controller-image` пересоберёт образ.
Пакеты `jenkins-controller` и `jenkins-agent-python` в ghcr должны быть **public**.

Jenkins только пишет в git. В Kargo он не ходит — наоборот, Kargo вызывает Jenkins (DAST) и ждёт статус.

| Джоба | Что делает | Пишет в |
|---|---|---|
| **BuildRelease** | образы в registry → SCA (список образов) → SAST (список репозиториев) → Quality Gate → **один коммит** `release.yaml` всех выбранных сервисов | `gitops-main`, ветка ФП `qa-at` |
| **ExcludeService** | исключение сервиса из релиза, без сборки | `planned` → ветка `qa-at`; `urgent` / `clear` → `gitops-prod` |
| **DAST** | эмуляция DAST по списку репозиториев; запускает Kargo (верификация `uat`) | — |

Сборки нет: образы `release-1-101`, `release-2-102`, `release-3-103` уже в ghcr. SCA, SAST и DAST — эмуляция
([scripts/release_tool.py](scripts/release_tool.py)), политика Quality Gate — [scripts/policy.json](scripts/policy.json):
релиз блокируется при любой `critical`/`high` и при `medium > 3`.

## Параметры

**BuildRelease**: `TASK`, `VERSION` (тег), `SERVICES` (`mgmt,core,api`), `SCA_PROFILE` и `SAST_PROFILE`
(`clean`/`low`/`medium` проходят, `high`/`critical` — нет).

**ExcludeService**: `SERVICE`, `MODE`, `TASK`, `REASON`.

| MODE | Когда | Что дальше |
|---|---|---|
| `planned` | есть время на цикл uat | в ветке `qa-at` файл сервиса = версия PROD (если релиз уже в PROD — предыдущая) → новый Freight → uat → prod |
| `urgent` | инцидент в PROD | запись в `gitops-prod/qa/at/release-exclude.yaml` → повторный Promote текущего Freight в prod: сервис вернётся к версии до релиза |
| `clear` | исправление готово | снять срочное исключение |

**DAST**: `REPOS`, `ENVIRONMENT`, `RELEASE` (передаёт Kargo), `FAIL_REPOS` — эмуляция провала:
поставьте значение по умолчанию `qa-at-core` в Configure, и следующий DAST от Kargo упадёт.

## Учётки и токены

- `github-token` — GitHub PAT из `scripts/.env` (`GITHUB_TOKEN`), нужен scope `repo`: запись в `gitops-main` и `gitops-prod`.
- пользователь `kargo` — им Kargo запускает DAST; пароль в секрете `jenkins-kargo` (создаёт `up.ps1`).
