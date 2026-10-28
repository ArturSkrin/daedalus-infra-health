# Daedalus в проде: как это работает

Живой документ. Каждое изменение в устройстве или развёртывании записывается сюда, а в конец добавляется строка в «Журнал изменений».

## Цель

Один экран, на котором видно, всё ли в порядке со всеми VPS: сайты в docker compose, базы, бэкапы. На экране не сырые метрики, а готовое решение: **ALL CLEAR / SCHEDULE / ACT NOW / BLIND** и причина.

## Схема

### Сейчас: проба на одном сервере (`eastern-green`)

```
 eastern-green
 ┌──────────────────────────────────────────────────────────────────────┐
 │ сервисы (compose-проекты: optima-asset-web …)                        │
 │      ▼                                                               │
 │ Docker daemon ── /var/run/docker.sock                                │
 │      ▼                                                               │
 │ docker-proxy        только GET /containers/*                         │
 │      ▼ tcp 2375 внутри compose-сети                                  │
 │ agent :9000         каждые 15 с: состояние контейнеров + cgroup      │
 │      ▼ http://agent:9000  (наружу 127.0.0.1:9000)                    │
 │ backend :8000       вердикт, журнал (опрос агента, кэш 20 с)         │
 │      ▼ /api                                                          │
 │ frontend nginx      127.0.0.1:8080                                   │
 └──────────────────────────────────────────────────────────────────────┘
      ▲ ssh -L 8080:127.0.0.1:8080
   браузер → http://localhost:8080
```

От падения контейнера до красного экрана проходит до 1,5 минуты: 2 цикла агента по 15 с, кэш backend 20 с, опрос фронта 30 с.

### Куда идём

```
 VPS-1..N:  сервисы → docker-proxy → agent :9000 (только на wg-интерфейсе)
                                         ▲  WireGuard (центр сам ходит к агентам: pull)
 Центр (eastern-green):  backend → опрашивает всех агентов, /api/fleet, журнал, ntfy-алерты
                            │  наружу только исходящие: ProtonVPN, внутри него wg-туннель
                            ▼
 Сервер фронта:  frontend nginx → пользователи мониторинга (Cloudflare Access)
```

Центр не принимает входящих соединений. Модель pull это позволяет: центр сам ходит и к агентам, и к серверу фронта.

## Компоненты

| Компонент | Код | Что делает |
|---|---|---|
| agent | `adapter/` (`docker_source.py`, `collector.py`, `shim.py`) | Находит все контейнеры хоста через Docker API, читает их cgroup, открывает и закрывает инциденты, хранит историю за 24 ч. Отдаёт API в формате Triage (`/v2/agent/*`), плюс `/healthz` и `/debug/targets`. |
| docker-proxy | образ `tecnativa/docker-socket-proxy` | Единственный, кто видит `docker.sock`. Пропускает только `GET /containers/*`. |
| backend | `backend/` | Забирает данные агента (`live.py`) и считает вердикт: `bundle → engine → presentation`. Ведёт журнал изменений. |
| frontend | `frontend/` | React. Сам ничего не считает. Если `/api/health` отвечает `live: true`, включается live-режим. |

Compose-файлы:
- `docker-compose.yaml`: backend и frontend;
- `docker-compose.agent.yaml`: агент и docker-proxy, запускается сам по себе на любом хосте;
- `docker-compose.agent-local.yaml`: подключает backend к агенту на этом же хосте (проба на одном сервере).

## Как агент решает

- **Цель** — каждый контейнер. Имя `проект/сервис` из меток compose, для контейнера вне compose — его имя. Реплики сервиса сливаются, и о сервисе говорит худшая из них.
- **Готовность** определяется так:
  - `running` — готов. Исключение: healthcheck `unhealthy`.
  - `exited 0`, если политика рестарта `no` или `on-failure`, — готов: задача отработала (миграции, разовые задачи).
  - Остальное — не готов: exit ≠ 0, OOM, `restarting`, `paused`, `created`.
- **Tier**:
  - 1 (пользовательский путь): у контейнера есть опубликованный порт;
  - 2: всё остальное;
  - метка `daedalus.tier=N` задаёт уровень вручную.
- **Последствия**:
  - не готов контейнер tier 1 → ACT NOW;
  - не готов контейнер tier 2 → инцидент уровня warning → SCHEDULE.
- **Пропали из Docker** (удалены) — считаются упавшими. Через 24 ч без появления о них забываем, инциденты закрываются.
- **Docker-демон не отвечает** → BLIND: агент сообщает «нет связи», а не «всё упало».
- **Метка `daedalus.ignore=true`** исключает контейнер из наблюдения. Одноразовые контейнеры (`docker compose run`) пропускаются всегда.
- **Ресурсы.** PSI CPU/RAM/IO, `memory.current`/`memory.max` и OOM-kill из cgroup v2 хоста. Поля те же, что у `integrations/eve-tools/vitals.ts`.

## Конфигурация агента

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `AGENT_TENANT` | — (обязательна) | Имя хоста на экране (`ADAPTER_TENANT`) |
| `AGENT_BIND` | `127.0.0.1` | Адрес, на котором публикуется :9000. В проде это WireGuard-IP, **никогда** не `0.0.0.0`. |
| `DOCKER_SOCK` | `/var/run/docker.sock` | Сокет для docker-proxy. Для rootless Docker: `/run/user/<uid>/docker.sock`. |
| `ADAPTER_DISCOVER` | `docker` (задано в compose) | Включает автообнаружение |
| `ADAPTER_TARGETS` | пусто | JSON-список дополнительных целей: HTTP- и TCP-пробы, внешние зависимости |

## Развёртывание: проба на одном сервере

```bash
git clone -b feat/fleet-agent https://github.com/ArturSkrin/daedalus-infra-health.git /opt/daedalus
cd /opt/daedalus
TRACKER_PORT=127.0.0.1:8080 AGENT_TENANT=eastern-green \
  docker compose -f docker-compose.yaml -f docker-compose.agent.yaml -f docker-compose.agent-local.yaml up -d --build
curl -s http://127.0.0.1:9000/debug/targets          # что видит агент
```

Дашборд открывается с ноутбука через `ssh -L 8080:127.0.0.1:8080 deploy@<host>` по адресу `http://localhost:8080`.
Откат — та же команда с `down`. Агент только читает, поэтому сервисы хоста он не меняет.

## Безопасность

- Наружу не открыто ничего: агент и трекер слушают `127.0.0.1`.
- `docker.sock` есть только у docker-proxy. Агент может читать данные контейнеров, но не может их запускать, останавливать или выполнять в них команды.
- **Риск:** inspect контейнера содержит переменные окружения, а в них часто лежат секреты. Если агента взломают, их можно прочитать. Поэтому :9000 открывается только внутри WireGuard.
- Cgroup хоста смонтирован только на чтение.

## Разработка

- Dev-виртуалка в локалке. Код лежит в `/srv/claude-workspaces/daedalus`.
- Claude работает только через MCP:
  - `dev-files`: работа с файлами;
  - `dev-runner`: белый список команд `/usr/local/bin/claude-runner`. Через него запускаются `check` (ruff, pytest, сценарии), `test`, `contract`, `frontend`, git, `up`/`down`/`ps`/`logs` в rootless Docker.
- Push в GitHub делает владелец.

## Дальше

1. Проба на `eastern-green`: агент и трекер на одном хосте.
2. Второй сайт на другом сервере: агент там, WireGuard до центра, backend опрашивает несколько агентов, обзор парка `/api/fleet`.
3. Фронт отделяется на свой сервер. Центр выходит наружу через ProtonVPN и wg-туннель.
4. Алерты ntfy, проверки Neon (`SELECT 1`) и восстановления бэкапов, логи (Alloy → Loki), Ansible-роль для агента.
5. Последним шагом — домены: сайты, почта (MX/SPF/DKIM), сроки сертификатов.

## Журнал изменений

- **2026-10-16**: агент. Автообнаружение контейнеров через Docker API, cgroup, BLIND при молчащем демоне, `docker-compose.agent.yaml` с docker-proxy. 12 тестов (`tests/test_docker_discovery.py`).
- **2026-10-28**: `docker-compose.agent-local.yaml` для пробы на одном сервере. Создан этот документ.
