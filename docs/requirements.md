# Где реализованы требования задания

| Требование | Реализация | Как проверить |
|---|---|---|
| Kubernetes или Minikube | `deploy/base`, `deploy/local` | Команды запуска в README |
| Открытая instruct-модель | Qwen2.5-0.5B-Instruct, commit SHA в `model.env` | Локальный snapshot и ответ API |
| Только CPU, vLLM от 0.27.0 | CPU-образ v0.27.0, `VLLM_TARGET_DEVICE=cpu`, CPU-версия torch в lock | Сборка и проверка внутри образа |
| Собственный Dockerfile | Корневой `Dockerfile` | `docker build` |
| Процесс без root | `USER 10001:10001`, pod securityContext | Проверка UID внутри контейнера |
| Все Python-пакеты закреплены | `requirements.txt`, `verify_lock.py`, digest базы | Сверка lock при сборке |
| Нет промптов и ответов в stdout/stderr | `inference/logging.json`, pipe аудита, DEVNULL | Unit tests и smoke test с `--check-logs` |
| Факт обращения логируется | `inference/audit.py` | Событие `request_completed` |
| Веса сохраняются в PVC | `deploy/base/pvc.yaml`, `tools/cache_model.py` | Рестарт с `model_cache_hit` |
| При готовом кэше сеть не используется | Проверка snapshot до создания HTTP-клиента | Unit test; отдельно проверка NetworkPolicy |
| HF token и API token через Secret | `tools/create_secrets.py`, ссылки в Deployment | Доступ к токенам разделён между контейнерами |
| Параметры через ConfigMap | Генератор Kustomize, `serve.yaml`, `model.env` | Изменение конфигурации без сборки образа |
| README с запуском | Корневой README | Пошаговое выполнение команд |
| Бонус Kustomize | `deploy/local/kustomization.yaml` | `kubectl apply -k deploy/local` |
| Бонус initContainer | `containers/downloader.Dockerfile`, Deployment | Отдельный rootless-загрузчик |
| Бонус нагрузочного теста | `tools/benchmark/run.py` и разбор настройки в README | Скрипт подготовлен; реальные замеры ещё не выполнены |

Статус реально выполненных проверок находится в `reports/validation.md`.
Архив содержит подготовленный проект; для сдачи по условию нужна ссылка
на размещённый репозиторий.
