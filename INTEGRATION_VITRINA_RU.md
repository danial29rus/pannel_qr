# Интеграция партнёр → панель → Витрина

Целевой поток:

```text
Партнёр
  └─ UUID + сумма + Auth token + HMAC Secret key
       → QR-панель: проверяет запрос, лимиты и idempotency
       → выбирает email из загруженного пула
       → JSON API adapter вызывает Витрину с её отдельным Bearer token
       → Витрина создаёт MulenPay checkout
       → панель вызывает checkout URL + /sbp и извлекает direct NSPK QR URL
       ← панель отдаёт https://qr.nspk.ru/... партнёру
```

Партнёр не получает API token Витрины и не передаёт email покупателя. Его UUID становится ID платежа в панели и Витрине. При сетевом повторе панель использует тот же email и UUID; Витрина не создаёт второй платёж.

Направления обмена разные: партнёру передаются **наш create API URL и два ключа**, чтобы он отправил заказ в панель. От партнёра мы получаем **его callback/webhook URL** и сохраняем его в проекте. После создания платежа панель возвращает `pending` и ссылку; оплаченной операция становится только после того, как Витрина подтвердила оплату и панель отправила партнёру callback со `status=paid` и `paid=true`.

**Важно:** если сейчас на сервере развернута старая панель, новый URL `/external/{project_key}/payments` там ещё не существует. Сначала опубликуйте код этой интеграции в Git remote и обновите панель на сервере по шагу 1; только затем настраивайте provider и выдавайте партнёру ключи.

## 1. Развернуть обновлённую панель

Для установки панели рядом с уже работающей Витриной используйте режим `caddy-shared` из [`DEPLOYMENT_RU.md`](DEPLOYMENT_RU.md). Если панель уже запущена на старой версии, сначала отправьте новый код панели в Git remote. Затем на сервере обновите только checkout панели: не трогайте `.env.production`, текущую PostgreSQL базу и volume.

```bash
cd /opt/panel-vitrina
git pull --ff-only
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm migrate
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build api frontend worker
```

Профиль `processing` должен быть включён в `.env.production` (`COMPOSE_PROFILES=processing`), чтобы worker проверял статусы провайдера и доставлял callbacks. Проверьте:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 api worker
curl -fsS https://panel.vitrina-studio.ru/ready
```

Миграция `0011_external_payment_request` хранит UUID, сумму и выбранного пользователя до запроса к Витрине. Она выполняется командой `run --rm migrate` выше. Не удаляйте PostgreSQL volume и не запускайте `down -v`.

## 2. Добавить API Витрины как provider

В самой Витрине создайте отдельный API token для панели. На сервере Витрины:

```bash
openssl rand -hex 32
nano /opt/vitrina/.env
```

Добавьте токен в `PAYMENTS_API_TOKENS` как JSON-массив, не заменяя существующие действующие токены:

```env
PAYMENTS_API_TOKENS=["<существующий-токен>","<новый-токен-для-панели>"]
```

Примените изменение:

```bash
cd /opt/vitrina
docker compose up -d --force-recreate api worker
```

В панели откройте **«Провайдеры и подключения» → «Универсальное JSON API» → «Заполнить Витрину»**. Используйте настройки:

- API URL: `https://vitrina-studio.ru`
- Create path: `/api/v1/external/payments`
- Status path: `/api/v1/external/payments/{transaction_id}`
- Auth header: `Authorization`
- Auth scheme: `Bearer`
- Auth token: новый токен из `PAYMENTS_API_TOKENS`
- Provider Secret key: оставить пустым; API Витрины не использует второй секрет
- Request template, response paths, status mapping: оставить значения preset-а
- Включить **«Получать прямой NSPK URL из hosted checkout через endpoint провайдера `/sbp`»**
- Валюта: `RUB`; формат суммы: целые рубли

Нажмите **«Создать и подключить к проекту»**. Подключение сразу привязывается как маршрут выбранного проекта. Убедитесь, что маршрут активен и на нём выставлены нужные лимиты. Token Витрины хранится в панели как credential провайдера; его не передавайте партнёру.

Universal JSON API поддерживает типовую пару `POST create` + `GET status`, Bearer или настраиваемые header auth, request JSON template, JSON paths ответа и mapping удалённых статусов. Опция `/sbp` вызывает `GET <hosted_payment_url>/sbp` и принимает только `data.qrpayload`, начинающийся с `https://qr.nspk.ru/`. Если прямая NSPK-ссылка не получена после retries, панель сохраняет локальную транзакцию со статусом `failed`, запись попыток и событие ошибки, включает cooldown маршрута и отправляет партнёру failure callback. Hosted checkout URL как QR не возвращается.

## 3. Загрузить email

В панели откройте **«Пользователи» → «Импорт email»** и загрузите `.txt` или `.csv`. Убедитесь, что адреса созданы как активные пользователи с непустым email.

Пул общий на всю панель, а не отдельный для каждого проекта. Для нового UUID система случайно выбирает активного пользователя с email и сохраняет его в idempotency reservation до обращения к API Витрины. Email партнёру не возвращается. Один email может быть выбран для нескольких разных одновременно открытых UUID; эксклюзивной блокировки на весь период платежа нет.

При отсутствии активных email endpoint возвращает `503`. Витрина получает выбранный email. Если такой учётной записи в базе Витрины ещё нет, её внешний API может создать аккаунт на этот email.

## 4. Сгенерировать два ключа партнёра

Выберите проект **Vitrina**. На странице провайдеров в блоке **«Реквизиты интеграции партнёра»** нажмите **«Сгенерировать два ключа»**, затем **«Сохранить ключи»**:

- **Auth token** — входной токен проекта панели (`external_incoming_token`).
- **Secret key** — секрет проекта для HMAC запросов и подписания callbacks (`external_callback_secret`).

Панель покажет значения один раз после сохранения. Скопируйте их в менеджер секретов и передайте партнёру по защищённому каналу. При потере создайте новую пару и обновите настройки у партнёра. Эти ключи не связаны с API token Витрины и не являются `ADMIN_TOKEN`/`OPERATOR_TOKEN`/`VIEWER_TOKEN`.

Если вы пока видите старый экран настроек, соответствие полей на нём такое: **«URL для финальных статусов»** — webhook URL партнёра; **«Токен входящих заказов»** — Auth token; **«Секрет подписи callback»** — Secret key. На скриншоте также отображается старый incoming URL `/api/v1/external/vitrina-studio/orders`; он принимает контракт заказа с товаром/пользователем и не выбирает email так, как новый payment API. Для нужного потока после обновления панели используйте `/api/v1/external/vitrina-studio/payments`.

Для ручной генерации ключей на старом экране можно выполнить `openssl rand -hex 32` два раза и вставить разные значения в два поля. Не вставляйте туда Vitrina `PAYMENTS_API_TOKENS`.

Попросите партнёра сообщить его HTTPS webhook URL и укажите его в поле **Webhook URL партнёра** на странице провайдеров. То же поле доступно в **«Настройки» → «Внешняя площадка» → «URL для финальных статусов»**. Это адрес партнёра, на который **панель отправляет** итоговый статус. URL настраивается один раз на проект и используется для всех его платежей. Для описанного процесса webhook нужен; GET status endpoint остаётся резервной проверкой.

## 5. Дать партнёру API contract

Для проекта с системным ключом `vitrina-studio` базовый URL создания платежа:

```text
https://panel.vitrina-studio.ru/api/v1/external/vitrina-studio/payments
```

Проверка статуса:

```text
https://panel.vitrina-studio.ru/api/v1/external/vitrina-studio/payments/{transaction_id}
```

Если системный ключ проекта в панели отличается, замените `vitrina-studio` в обоих URL на значение `external_key` проекта. Успешный create возвращает прямую NSPK-ссылку; партнёр должен показывать/кодировать именно этот URL, а не hosted страницу MulenPay.

Заголовки create запроса:

```http
X-Platform-Token: <Auth token>
X-Platform-Timestamp: <Unix timestamp в секундах>
X-Platform-Signature: <hex HMAC-SHA256>
Content-Type: application/json
```

Тело запроса:

```json
{
  "transaction_id": "7d602eb7-6052-4ecb-a45c-2d36c787edc8",
  "amount_rub": 500,
  "description": "Заказ 123"
}
```

Требования к запросу:

- `transaction_id` — UUID, уникальный для заказа. Сгенерировать один раз и повторять неизменным при timeout/сетевой ошибке.
- `amount_rub` — целое число RUB в диапазоне 100–500000.
- Не передавать email: его выбирает панель.
- Для повторного создания с тем же UUID сумма должна совпадать; иначе вернётся `409`.
- Запросы должны идти по HTTPS и быть подписаны с актуальным timestamp (допустимое расхождение до 5 минут).

Подпись партнёр считает по точным bytes отправляемого JSON. `PATH` — path без схемы/домена и query string, например `/api/v1/external/vitrina-studio/payments`:

```text
body_hash = lowercase_hex(SHA256(raw_body))
canonical = timestamp + "." + METHOD + "." + PATH + "." + body_hash
signature = lowercase_hex(HMAC-SHA256(secret_key, UTF8(canonical)))
```

Python-пример для create:

```python
import hashlib
import hmac
import json
import time
import requests

url = "https://panel.vitrina-studio.ru/api/v1/external/vitrina-studio/payments"
path = "/api/v1/external/vitrina-studio/payments"
payload = {
    "transaction_id": "7d602eb7-6052-4ecb-a45c-2d36c787edc8",
    "amount_rub": 500,
    "description": "Заказ 123",
}
raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
timestamp = str(int(time.time()))
body_hash = hashlib.sha256(raw_body).hexdigest()
canonical = f"{timestamp}.POST.{path}.{body_hash}".encode()
signature = hmac.new(SECRET_KEY.encode(), canonical, hashlib.sha256).hexdigest()

response = requests.post(url, data=raw_body, headers={
    "Content-Type": "application/json",
    "X-Platform-Token": AUTH_TOKEN,
    "X-Platform-Timestamp": timestamp,
    "X-Platform-Signature": signature,
}, timeout=30)
response.raise_for_status()
payment = response.json()
```

Ответ create содержит `transaction_id`, `status`, `paid`, `amount_rub`, `payment_url`, `qr_url`, `expires_at`. Изначально ожидаются `status=pending` и `paid=false`. `payment_url` и `qr_url` MulenPay — hosted checkout; QR можно строить из `qr_url`, но это не прямая ссылка НСПК. Само получение ссылки не означает, что платеж уже успешен.

Status GET подписывается той же схемой, `METHOD=GET`, `PATH` включает UUID, `raw_body=b""`, поэтому `SHA256(raw_body)` считается от пустой строки. Ответы статуса: `pending`, `paid`, `failed`, `canceled`, `refunded`. Финальное `paid: true` возвращается только после подтверждения платежа; статус обновляется worker-ом панели по статусу Витрины.

Когда status worker панели увидит финальный статус от Витрины, панель отправит на Callback URL JSON:

```json
{
  "transaction_id": "7d602eb7-6052-4ecb-a45c-2d36c787edc8",
  "status": "paid",
  "paid": true,
  "amount_rub": 500,
  "currency": "RUB",
  "payment_url": "https://checkout.example/pay/123"
}
```

Для неуспешного завершения `status` будет `failed`, `canceled` или `refunded`; `paid` будет `false`. Партнёр должен считать заказ успешным только при `status == "paid"` и `paid == true`.

Callback подписан заголовками `X-Panel-Timestamp` и `X-Panel-Signature`. Подпись: `lowercase_hex(HMAC-SHA256(secret_key, UTF8(timestamp + ".") + raw_body))`. Партнёр должен проверить подпись и timestamp до обработки. Callback может прийти повторно; обработка должна быть идемпотентной по `transaction_id`. При временной ошибке панель повторяет доставку; GET status остаётся способом сверки.

Partner endpoint панели не отдаёт исходное hosted значение. При включённой настройке `/sbp` adapter запрашивает `GET <hosted_payment_url>/sbp`, извлекает `data.qrpayload` и возвращает партнёру только ссылку с точным префиксом `https://qr.nspk.ru/`. Если endpoint не вернул такой NSPK URL после повторных попыток, create возвращает сохранённую операцию со `status=failed` и пустыми URL; hosted checkout не подменяет QR.

## 6. Тестовый запрос и реальная проверка оплаты

В репозитории есть `scripts/test_partner_payment.py`. Он **симулирует клиент партнёра**: генерирует UUID, подписывает create/status запросы двумя partner keys, выводит payment/QR URL, при `--open` открывает direct NSPK URL и опрашивает status endpoint. Он не имитирует Витрину или банк: QR-ссылка создаётся реальной настроенной Витриной/MulenPay, а оплата по ней будет реальной.

Запускайте скрипт с компьютера, где есть Python 3 и доступ в интернет. Он запросит оба ключа скрытым вводом; значения не попадают в аргументы команды и не печатаются:

```bash
cd /путь/к/pannel_qr
python3 scripts/test_partner_payment.py --amount-rub 100 --open
```

Скрипт использует URL по умолчанию `https://panel.vitrina-studio.ru/api/v1/external/vitrina-studio/payments`. Если project `external_key` другой:

```bash
python3 scripts/test_partner_payment.py \
  --url https://panel.vitrina-studio.ru/api/v1/external/<external_key>/payments \
  --amount-rub 100 --open
```

Порядок теста:

1. Проверьте, что в панели выбран проект `Vitrina`, JSON API provider подключён к нему маршрутом, ограничения проекта выставлены и worker запущен.
2. Импортируйте несколько активных тестовых email. Не передавайте email скрипту: он не должен знать выбранный адрес.
3. Запустите скрипт и введите Auth token и Secret key из панели. Сразу сохраните напечатанный `Transaction UUID`.
4. Скрипт выведет `Status: pending`; обе ссылки должны начинаться с `https://qr.nspk.ru/`. Откройте QR URL и проверьте, что он ведёт на ожидаемую оплату.
5. Завершите тестовую оплату только если согласны провести реальный платёж на эту сумму. Если используете production-ключи, деньги будут списаны по правилам провайдера.
6. Скрипт продолжит опрашивать панель и должен показать `Status: paid (paid=True)`. Проверьте, что ваш callback endpoint получил подписанное уведомление, а партнёр пометил заказ успешным только после проверки подписи, `status=paid` и `paid=true`. Сверьте операцию в панели и в журнале Витрины; выбранный email партнёру не возвращается.
7. Для проверки повтора запустите скрипт с тем же `--transaction-id <UUID>` и той же суммой: должен вернуться тот же платёж/email. С другой суммой ожидается `409`.

Если create завершился сетевым timeout, **не генерируйте новый UUID**: запустите скрипт повторно с напечатанным UUID через `--transaction-id <UUID>`. Так проверяется idempotency на стороне партнёра → панели → Витрины. Если NSPK URL не получен после provider retries, панель сохранит транзакцию со статусом `failed`, вернёт `status=failed`, `paid=false` без payment URLs, включит route cooldown и отправит failure callback. Повтор с тем же UUID вернёт ту же failed операцию без нового вызова Витрины; для новой попытки после устранения причины нужен новый UUID. Чтобы проверить оплату без списания, нужен sandbox/test provider аккаунт Витрины.

### Диагностика ошибки 503 при извлечении QR

Если ранее панель ответила `503 Payment provider unavailable after retries`, но в логах есть `POST /api/v1/external/payments` Витрины с HTTP 200, создание в Витрине прошло, а direct QR не был получен на шаге MulenPay `/sbp`. После обновления панель сохраняет эту операцию как `failed`, а не откатывает запись. Повторные POST с тем же UUID — повторы одного идемпотентного заказа; не создавайте новый UUID вслепую.

Проверьте существующий Vitrina payment по UUID диагностическим скриптом. Он не создаёт и не оплачивает новый платёж; запросит Vitrina Bearer token, покажет статус и hostname checkout URL, затем проверит `<checkout_url>/sbp` без авторизации:

```bash
python3 scripts/diagnose_vitrina_payment.py c1810819-1705-413b-b0da-ac67a04d55c8
```

Ожидаемый результат `/sbp`: HTTP 200 и `data.qrpayload` с адресом `https://qr.nspk.ru/...`. Если endpoint вернёт другой статус/JSON или не вернёт `qrpayload`, проблема на стороне MulenPay checkout/метода `/sbp`; панель не выдаст hosted checkout как NSPK. Не публикуйте Vitrina Bearer token или полный checkout URL: в них могут быть секретные данные.

Если диагностический скрипт получил прямой NSPK URL, а partner payment сохранён со статусом `failed`, проверьте provider connection: флаг **«Получать прямой NSPK URL ... `/sbp`»** должен быть включён. У старого JSON API connection параметр может отсутствовать. Создайте новый connection через preset **«Заполнить Витрину»**, включите флаг, привяжите его к проекту и выключите старый маршрут. Тот же UUID останется идемпотентным и вернёт прежний `failed`; для новой попытки после cooldown партнёр должен создать новый UUID. Vitrina token оставьте тем же.

После успешной оплаты polling зависит от двух worker-ов (Витрины и панели), поэтому callback может прийти с задержкой в несколько интервалов проверки. Проверьте worker logs и журнал callback попыток, если статус не изменился. Не передавайте партнёру provider token Витрины, admin token панели или email-пул.
