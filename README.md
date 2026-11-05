# Инференс Qwen на CPU в Kubernetes

Ершов Илья  
Команда исследования технологий машинного обучения

Для задания я выбрал `Qwen/Qwen2.5-0.5B-Instruct` и vLLM `0.27.0` в CPU-образе.
Модель небольшая, поэтому с ней проще проверить весь цикл на локальном кластере:
скачать веса, сохранить их после перезапуска и открыть API с авторизацией.
GPU для этого решения не нужен.

Я разделил загрузку и инференс. Сначала initContainer проверяет модель в PVC и
при необходимости скачивает её. Затем сервер запускает vLLM с локальным путём.
Клиент получает ответ обычным способом, а в серверный журнал попадают только
события обращения: маршрут, статус и длительность.

## Как устроен проект

```text
Dockerfile                         CPU-сервер, запуск от UID 10001
requirements.txt                   полный lock Python-пакетов сервера
containers/
  downloader.Dockerfile            отдельный образ загрузчика, UID 10001
  requirements.downloader.txt      lock пакетов загрузчика
inference/
  server.py                        запуск vLLM и проверка событий аудита
  config.py                        допустимые параметры инференса
  audit.py                         ASGI middleware без записи содержимого
  logging.json                     отключение обычных текстовых логов
tools/
  cache_model.py                   загрузка и проверка модели
  verify_lock.py                   сверка установленного окружения с lock
  create_secrets.py                создание Secret через stdin kubectl
  smoke_test.py                    проверка API и живого журнала
  chat.py                          небольшой клиент для ручной проверки
  benchmark/run.py                 замеры коротких и длинных запросов
deploy/
  base/                            Deployment, Service, PVC, ConfigMap, Namespace
  local/                           точка входа Kustomize
  offline/                         запрет исходящей сети после загрузки модели
tests/                             локальные проверки кэша, настроек и приватности
docs/                              объяснение решений и проверка требований
reports/                           сведения о выполненных проверках
```

## Запуск на локальной машине

Нужны Docker с Linux containers, Minikube, kubectl с Kustomize и Python 3.10+
для вспомогательных скриптов. Образы рассчитаны на Linux amd64.
Для этой конфигурации я закладываю 6 CPU и 8 GiB памяти кластеру, а также
свободное место под образы и PVC. Это стартовый бюджет, а не результат замера.
На Windows команды Docker и Minikube выполняются через Docker Desktop.

В кластере должен быть default StorageClass, способный выделить PVC на 5 GiB
и предоставить запись пользователю из `fsGroup: 10001`.
Первый запуск требует доступа к Docker registry и Hugging Face.
Все команды ниже выполняются из корня проекта.

### Собрать образы и подготовить кластер

```bash
docker build --platform linux/amd64 -t ershov-vllm-cpu:1.0.0 -f Dockerfile .
docker build --platform linux/amd64 -t ershov-model-loader:1.0.0 -f containers/downloader.Dockerfile .
minikube start --driver=docker --cpus=6 --memory=8192
minikube image load ershov-vllm-cpu:1.0.0
minikube image load ershov-model-loader:1.0.0
kubectl config current-context
```

Базовые образы закреплены по digest. Во время сборки `verify_lock.py` сравнивает
все установленные Python-пакеты с lock-файлом, включая транзитивные зависимости.
Лишний пакет, отсутствие пакета или другая версия останавливают сборку.
У сервера дополнительно выполняется `pip check`.
Я не устанавливаю зависимости повторно поверх CPU-образа: lock описывает именно
унаследованное окружение. При обновлении образа нужно обновить digest и lock вместе.

### Создать секреты и запустить сервер

```bash
kubectl apply -f deploy/base/namespace.yaml
python tools/create_secrets.py
kubectl apply -k deploy/local
kubectl -n llm-cpu rollout status deployment/vllm-cpu --timeout=1200s
kubectl -n llm-cpu port-forward service/vllm 18001:8000
```

`create_secrets.py` скрыто запрашивает токены. Для открытой Qwen поле HF token
можно оставить пустым. Если API token не введён, скрипт создаёт случайный.
Для закрытой модели нужен HF token с доступом и принятая лицензия модели.
Можно заранее задать `HF_TOKEN` и `API_TOKEN` в окружении.

HF token получает только initContainer, API token — только сервер.
Токены не передаются аргументами командной строки и не записываются в файлы проекта.
В общем кластере дополнительно нужны RBAC и шифрование Secret в etcd:
сам формат Secret не обеспечивает шифрование. Для удалённого доступа понадобится TLS.

### Проверить API

Окно с `port-forward` должно оставаться открытым. В другом терминале Bash:

```bash
export API_TOKEN="$(kubectl -n llm-cpu get secret api-token -o jsonpath='{.data.token}' | base64 -d)"
python tools/smoke_test.py --base-url http://127.0.0.1:18001 --check-logs
python tools/chat.py
```

В PowerShell вместо `export`:

```powershell
$encoded = kubectl -n llm-cpu get secret api-token -o jsonpath='{.data.token}'
$env:API_TOKEN = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
python tools/smoke_test.py --base-url http://127.0.0.1:18001 --check-logs
python tools/chat.py
```

Smoke test проверяет отказ без токена, генерацию с токеном, ошибочный запрос и
отсутствие контрольного промпта, ответа и API token в живых логах.
Клиент `chat.py` выводит ответ в своём терминале; это не серверный журнал.

## Что происходит с весами после рестарта

Ревизия модели закреплена commit SHA в `deploy/base/model.env`.
Загрузчик сначала проверяет локальный `.complete.json` и SHA-256 файлов.
При исправном кэше он завершает работу с `model_cache_hit`, не создавая сетевого клиента.
При первой загрузке скачивает файлы во временный каталог, сверяет доступные
LFS-хеши и публикует готовый snapshot переименованием. Блокировка не даёт двум
загрузчикам одновременно менять кэш.

Если кэш повреждён или в нём другая ревизия, загрузчик останавливается.
Так ошибка не маскируется новым скачиванием. Для смены модели нужно выделить
другой PVC либо явно освободить старый, понимая, что веса придётся скачать заново.

```bash
kubectl -n llm-cpu rollout restart deployment/vllm-cpu
kubectl -n llm-cpu rollout status deployment/vllm-cpu --timeout=1200s
kubectl -n llm-cpu logs deployment/vllm-cpu -c download-model
```

После рестарта с исправным PVC ожидается `model_cache_hit`.
Сервер монтирует веса только для чтения, получает `HF_HUB_OFFLINE=1` и
`TRANSFORMERS_OFFLINE=1`. HF token в его окружении отсутствует.

Для отдельной проверки без исходящей сети после первой загрузки:

```bash
kubectl apply -f deploy/offline/networkpolicy.yaml
kubectl -n llm-cpu rollout restart deployment/vllm-cpu
```

Эта проверка работает только с CNI, который исполняет NetworkPolicy.
Перед скачиванием новой модели политику нужно убрать.

## Какие параметры я оставил настраиваемыми

В `deploy/base/serve.yaml` находятся dtype, длина контекста, размеры батча и настройки
кэширования. В `model.env` — модель, ревизия, OpenMP и размер CPU KV cache.
После изменения файлов достаточно выполнить `kubectl apply -k deploy/local`:
Kustomize изменит имя ConfigMap, и Deployment получит новый pod.

Начальный профиль: `float32`, контекст 1024 токена, одна последовательность,
батч 256 токенов, chunked prefill включён. KV cache — 1 GiB, OpenMP — 4 потока.
Длина контекста включает и вход, и запрашиваемый ответ.
Это осторожные настройки для локального запуска; их стоит подбирать под свой CPU.

Через YAML нельзя подменить middleware, включить запись промптов или снять
авторизацию. Сервер принимает только небольшой список параметров и проверяет
их типы. При пустом API token запуск прекращается.

## Нагрузочный тест

После запуска API и smoke test:

```bash
python tools/benchmark/run.py --requests 12 --concurrency 2 --output-tokens 32 --output reports/local
```

Скрипт отдельно прогревает короткий и длинный сценарии. TTFT считается до первого
непустого текстового фрагмента, latency — до завершения потока, throughput — по
выходным токенам и успешным запросам за полное время сценария.
Число токенов берётся из `usage` API. Запросы и ответы в отчёт не сохраняются.
На выходе получаются `results.json` и `results.md`; ошибки учитываются отдельно.

| Сценарий | TTFT p50 / p95 | Latency p50 / p95 | Выходных токенов/с | Запросов/с |
|---|---|---|---|---|
| Короткий промпт | Не измерено | Не измерено | Не измерено | Не измерено |
| Длинный промпт | Не измерено | Не измерено | Не измерено | Не измерено |

Эту таблицу нужно заполнить результатами собственного запуска на стенде.
Бонус с нагрузочным тестированием пока подготовлен как воспроизводимый сценарий;
численных результатов работающего сервера в этом варианте нет.
Текущее состояние проверок описано в `reports/validation.md`.

### Как я бы повышал throughput

При большом потоке коротких запросов я сначала увеличивал бы `max-num-seqs`
с 1 до 2 и 4, затем подбирал `max-num-batched-tokens`. Это даёт планировщику
возможность собирать несколько запросов в батч. После каждого шага я сравнивал бы
throughput с p95 задержки: рост очереди сам по себе улучшением не является.
Для CPU также проверил бы число OpenMP-потоков и доступные ядра.

Если запросов меньше, но контекст большой, я увеличил бы `max-model-len` до
нужного размера и пересчитал бюджет памяти для KV cache. Chunked prefill оставил бы
включённым и сравнил несколько размеров батча, например 256, 512 и 1024.
Большой батч может ускорить обработку входа, но требует замера задержек остальных
запросов. Prefix caching я проверял бы при общих префиксах; для независимых текстов
его польза заранее не очевидна. Числа из GPU-рекомендаций я бы не переносил на CPU
без эксперимента.

В документации vLLM описаны [параметры CPU](https://docs.vllm.ai/en/stable/getting_started/installation/cpu/)
и [работа chunked prefill](https://docs.vllm.ai/en/stable/configuration/optimization/).
Эти страницы обновляются; проект закреплён на версии `0.27.0`.

## Проверки и сдача

Локальные тесты не требуют vLLM и запускаются стандартным Python:

```bash
python -m unittest discover -s tests -v
```

Перед запуском в кластере можно проверить развёрнутые манифесты:

```bash
kubectl kustomize deploy/local
kubectl apply -k deploy/local --dry-run=server
```

По условию задания сдаётся ссылка на репозиторий. В репозиторий нужно положить
содержимое этой папки. Файл со ссылкой следует назвать
«Ершов И. Команда исследования технологий машинного обучения» и отправить способом,
указанным в задании. Сами токены и каталог `reports/local` в Git не добавляются.
