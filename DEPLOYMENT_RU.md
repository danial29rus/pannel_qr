# Установка панели рядом с Витриной или отдельно

Панель можно установить на тот же VPS, где уже работает Витрина, на поддомен `panel.<домен-витрины>`. Caddy из стека Витрины остаётся единственным владельцем публичных портов 80/443 и TLS. У панели будут собственные API, PostgreSQL, Compose project и volume; с БД Витрины она не объединяется. Также сохранён вариант отдельного сервера с Nginx/Certbot.

Чистая установка имеет отдельную пустую базу. Это самостоятельная панель, не реплика и не failover Витрины. Фоновая сверка отключена по умолчанию; для приёма платежей включите worker после настройки подключений.

## Режим рядом с Витриной (рекомендуемый)

Витрина уже запускает Caddy в Docker и занимает 80/443. Не запускайте рядом системный Nginx/Certbot установщик панели: он конфликтует с этим ingress. Схема ниже подключает только API и frontend панели к общей Docker-сети `vitrina_proxy`; база остаётся в закрытой сети Compose панели.

1. Создайте DNS A-запись `panel.vitrina-studio.ru` (или `panel.<ваш-домен>`) на IP VPS. Если у поддомена есть AAAA, он также должен вести на этот VPS.
2. Обновите Витрину так, чтобы её `docker-compose.yml` и `Caddyfile` содержали поддержку `PANEL_ADDRESS` и сеть `vitrina_proxy` (они добавлены в этот проектный комплект интеграции). В `/opt/vitrina/.env` задайте `PANEL_ADDRESS=panel.vitrina-studio.ru` и `ACME_EMAIL=...`. В каталоге Витрины выполните `docker compose up -d --build caddy`; проверьте `docker network inspect vitrina_proxy`.
3. Разместите код панели отдельно, например `/opt/panel-vitrina`. Скопируйте `.env.production.example` в `.env.production`, установите права `chmod 600 .env.production` и задайте уникальные значения:

   ```env
   COMPOSE_PROJECT_NAME=panel-vitrina
   DEPLOY_MODE=caddy-shared
   PROXY_NETWORK=vitrina_proxy
   PANEL_DOMAIN=panel.vitrina-studio.ru
   POSTGRES_DB=panel_vitrina
   POSTGRES_USER=panel_vitrina
   API_BIND_PORT=18180
   PANEL_BIND_PORT=15174
   COMPOSE_PROFILES=processing
   ```

   Сгенерируйте новые `POSTGRES_PASSWORD`, `ADMIN_TOKEN`, `OPERATOR_TOKEN`, `VIEWER_TOKEN`, `PANEL_SESSION_SECRET` через `sh scripts/generate-secrets.sh` и внесите их в файл. `COMPOSE_PROJECT_NAME` и порты должны быть уникальны для каждого отдельного экземпляра на этом сервере. Не используйте значения из примера/другого инстанса.
4. Выполните `sudo bash scripts/install-production.sh`. В этом режиме установщик не создаёт Nginx-конфиги и не запускает Certbot. Он применит миграции, поднимет собственную БД/панель/worker и сообщит команду для перезапуска Caddy. Выполните в `/opt/vitrina`: `docker compose up -d caddy`.
5. Проверьте `https://panel.vitrina-studio.ru`, `https://panel.vitrina-studio.ru/ready` и логи `docker compose logs --tail=100 api worker`. Caddy получит сертификат автоматически. Не открывайте наружу порты PostgreSQL/API/frontend.

При обновлении Витрины не удаляйте внешний сетевой endpoint панели. Запускайте обновление штатным `./scripts/update.sh`; оно пересобирает Caddy, но сохраняет панель и её тома. При обновлении панели используйте команды Compose далее в этом документе. Никогда не выполняйте `down -v`.

Для нового проекта повторите шаги с отдельным каталогом панели, новым `COMPOSE_PROJECT_NAME`, БД/пользователем, секретами и свободными localhost-портами; домен задайте как `panel.<домен-проекта>`. Если на одном Caddy нужно обслуживать несколько панелей одновременно, каждому инстансу необходимы отдельные upstream aliases и отдельный Caddy site block; текущий шаблон панели подключает один инстанс `panel-api`/`panel-frontend`.

## Отдельный сервер с Nginx

Для самостоятельного сервера задайте `DEPLOY_MODE=standalone-nginx`; остальные шаги исходной установки применимы. В этом режиме панель сама устанавливает Nginx-конфиги и Certbot. Не используйте его на VPS, где Витрина уже владеет публичными портами 80/443.

## 1. Подготовить сервер и DNS

Для небольшой нагрузки можно начать с 2 vCPU, 4 ГБ RAM и 30 ГБ SSD; фактические ресурсы зависят от числа платежей и глубины истории.

Создайте A-запись `panel-trader.workkit-studio.ru`, указывающую на новый IP. Панель и API работают через этот домен. При необходимости можно отдельно указать API-домен в `API_DOMAIN` и создать для него A-запись. Если есть AAAA-записи, они также должны вести на новый сервер. Старые записи не меняйте. Для выпуска сертификата имена должны разрешаться публично.

Выполните на новом сервере под root:

```bash
apt-get update
apt-get install -y ca-certificates curl git nginx certbot python3-certbot-nginx gettext-base openssl python3
```

Установите Docker Engine и Compose plugin по [официальной инструкции для Ubuntu](https://docs.docker.com/engine/install/ubuntu/) с репозиторием Docker, затем проверьте:

```bash
docker version
docker compose version
systemctl enable --now docker nginx
```

В firewall провайдера разрешите SSH, TCP 80 и 443. Порты базы, API и внутреннего фронтенда наружу не открывайте: PostgreSQL не публикуется, API и фронт привязаны к `127.0.0.1`.

## 2. Скопировать код и задать независимые настройки

Скопируйте **эту исправленную версию** проекта в `/srv/clearpay-reserve` через Git или архив. Не переносите `.env`, `.env.production`, `.git`, `.venv`, `node_modules`, дампы и рабочие секреты. Локальные незакоммиченные изменения обычный `git clone` не заберёт.

```bash
cd /srv/clearpay-reserve
cp .env.production.example .env.production
chmod 600 .env.production
sh scripts/generate-secrets.sh
nano .env.production
```

Генератор выводит новые секреты и хеш пароля. Перенесите их в `.env.production`; установщик ещё раз запросит пароль и запишет его хеш. Сохраняйте одинарные кавычки вокруг `PANEL_ADMIN_PASSWORD_HASH`, чтобы символы `$` не интерпретировались оболочкой.

Замените:

- `PANEL_DOMAIN=panel-trader.workkit-studio.ru` — новый домен без `https://` и пути. `API_DOMAIN` можно оставить пустым: API и webhook работают через тот же домен. Для отдельного API-домена укажите его здесь.
- `ACME_EMAIL` — ваш email для сертификатов.
- `POSTGRES_PASSWORD`, три API-токена и `PANEL_SESSION_SECRET` — новыми случайными значениями.
- `COMPOSE_PROJECT_NAME=clearpay-reserve` — постоянное уникальное имя этой установки. От него зависит имя тома PostgreSQL; после запуска его не меняют.
- `BACKUP_DIR=/var/backups/clearpay-reserve` — отдельный каталог резервных копий.
- `COMPOSE_PROFILES=` — оставить пустым для резервной установки без фоновой обработки.

Пароль PostgreSQL используйте в hex, как выдаёт генератор: он включается в URL подключения. Файл `.env.production` должен быть совместим с shell; не вставляйте в него произвольные shell-команды.

## 3. Выполнить первую установку

```bash
cd /srv/clearpay-reserve
sudo bash scripts/install-production.sh
```

Установщик проверит параметры, запросит пароль панели, соберёт контейнеры, применит миграции к **своей** базе, дождётся `/ready`, создаст Nginx-конфигурации для указанных доменов и получит HTTPS-сертификаты. Существующий Nginx-host с тем же именем он не перезаписывает. Это скрипт первой установки, для обновлений используйте команды ниже.

Старые файлы `deploy/nginx/*.workkit-studio.ru.conf` оставлены как исторические примеры. Установщик использует только новые `*.conf.template` и значения из `.env.production`.

## 4. Проверить запуск

```bash
cd /srv/clearpay-reserve
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 api migrate
curl -fsS http://127.0.0.1:18180/ready
```

Если меняли `API_BIND_PORT`, используйте свой порт. Затем откройте `https://panel-trader.workkit-studio.ru` и войдите с логином `PANEL_ADMIN_USERNAME` и заданным паролем. Проверьте вход/выход, создание пользователя и проекта, фильтры журнала и выбор недели. Пустые отчёты на новой базе ожидаемы.

`/health` показывает, что API жив; `/ready` дополнительно проверяет доступность PostgreSQL. Docker healthcheck использует `/ready`. Healthcheck сам не перезапускает зависший процесс — статус необходимо контролировать мониторингом.

## 5. Подключать платёжные системы отдельно

Создайте нужных пользователей, проекты, подключения и маршруты в новой панели. Для проверки начните с `demo`. Создание подключения и маршрута само по себе не переносит историю со старого сервера.

Для резервного контура нужны отдельные ключи провайдеров, входящие токены и webhook-настройки. **Не заменяйте webhook основного магазина на резервный домен:** некоторые провайдеры допускают только один адрес уведомлений. Если отдельных настроек нет, сначала согласуйте схему переключения с провайдером.

Webhook нового подключения: `https://panel-trader.workkit-studio.ru/api/v1/webhooks/КОД_ПРОВАЙДЕРА`. Входящий QR API: `https://panel-trader.workkit-studio.ru/api/v1/transactions/qr`. Callback проекта указывает на получателя статусов вашей интеграции.

Чтобы включить фоновую проверку платежей и повторную доставку callback, задайте `COMPOSE_PROFILES=processing` в `.env.production` и выполните:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

Профиль управляет запуском worker ([документация Compose](https://docs.docker.com/compose/how-tos/profiles/)). После включения он обрабатывает открытые платежи **этой базы**. Если восстанавливаете дамп, в нём могут оказаться старые URL, ключи и незавершённые платежи — проверьте их до запуска worker и приёма запросов. Схема восстановления действующей базы и автоматического failover требует отдельной настройки.

Для остановки уже запущенного worker одной очистки `COMPOSE_PROFILES` недостаточно:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml stop worker
```

Затем очистите `COMPOSE_PROFILES`. Отключённый worker не блокирует создание платежей через API и обработку входящих webhook.

## 6. Бэкапы и обслуживание

```bash
cd /srv/clearpay-reserve
sh scripts/backup-postgres.sh
```

Скрипт создаёт закрытый для других пользователей атомарный PostgreSQL dump и удаляет только свои старые дампы. Настройте cron от root:

```cron
0 3 * * * /bin/sh /srv/clearpay-reserve/scripts/backup-postgres.sh >> /var/log/clearpay-reserve-backup.log 2>&1
```

Копируйте дампы за пределы сервера. Проверяйте `pg_restore --list` и пробное восстановление в отдельную тестовую базу: наличие файла ещё не доказывает восстановимость. Секреты храните отдельно от кода и бэкапов.

Для обновления именно резервной установки сначала сохраните дамп, затем обновите код и выполните:

```bash
cd /srv/clearpay-reserve
sh scripts/backup-postgres.sh
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

Не меняйте имя Compose-проекта и не выполняйте `down -v`: том содержит данные. При неудачной миграции не продолжайте запуск вручную, изучите `logs migrate`. Откат приложения после миграции нужно оценивать по совместимости схемы.

Смена пароля панели: `sudo bash scripts/reset-panel-password.sh`. Сертификаты: `certbot renew --dry-run`.

## Мобильная панель

На экранах до 900 px доступна постоянная нижняя навигация: обзор, платежи, пользователи, проекты и «Ещё». В «Ещё» находятся лимиты, подключения, поддержка, настройки и выход. Платежи, пользователи и маршруты превращаются в карточки; формы используют одну колонку, поля не вызывают увеличение масштаба на iPhone. Навигация учитывает нижнюю безопасную область экрана.

## Периоды и проверка кода

Неделя — понедельник 00:00 включительно до следующего понедельника 00:00 исключительно, по `Europe/Moscow`; воскресенье входит целиком. Это относится к недельным лимитам, отчётам и фильтрам. Ручные даты в журнале тоже трактуются по Москве. API требует timezone в датах, принимает `created_to` как исключающую границу и отклоняет обратные периоды. Отчёт ограничен 366 днями. Оборот считается по успешным платежам, сгруппированным по дате их создания; расчётная прибыль маршрутов использует текущие ставки.

```bash
python3 -m venv .venv
.venv/bin/pip install -c requirements.lock -e '.[dev]'
.venv/bin/python -m pytest -q
cd frontend
npm ci
node --test src/periods.test.js
npm run build
```

Интеграционный тест `tests/test_postgres_reporting.py` включается через `TEST_DATABASE_URL` и запускается только на отдельной мигрированной тестовой PostgreSQL. Он проверяет SQL, границы недель, суммы, статусы, поиск и API-валидацию, откатывая свои записи. Не используйте рабочую базу для тестов.
