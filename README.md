# telegram-shop-on-fragment-web-api

**[English](#english)** · **[Русский](#русский)** · **[Donate](#donate)** 

---

<a id="english"></a>

## English

A Telegram shop bot that sells **Telegram Stars** and **Telegram Premium** to any Telegram user.
It takes the price from Fragment, adds your markup and shows it in USD and RUB. The customer pays
through a payment provider, and the bot then buys the item on [fragment.com](https://fragment.com)
from **your TON wallet** in USDT (TON network) or TON. The bot works with Fragment through the
**fragment-web-api** library, a separate repository.

> **Unofficial project**, not affiliated with Telegram or Fragment.
> The bot's interface is in **Russian**. All texts are in `bot/texts.py` and can be translated.

### Features

- Menu on the keyboard at the bottom: buy Stars (Fragment packages or a custom amount within the limits),
  buy Premium (3/6/12 months), my orders, info.
- Purchase for yourself or for any `@username`. The recipient is checked on Fragment right away.
- Order statuses: awaiting payment → paid → completed / expired / error. Each order has a sequential
  number and a random code.
- Payment providers: currently **RollyPay** (card / SBP, RUB) and **xRocket** (crypto via @xRocket). Each
  works in polling or webhook mode. A new provider is added as one class.
- Admin panel (`/admin`): orders and search, manual status changes, "run purchase" button, markup %,
  USD rate, Stars limits, xRocket fee, "Info" text, wallet balances.
- Anti-fraud:
  - one order, one invoice;
  - the item is delivered only on the "awaiting payment" → "paid" transition confirmed by the provider;
  - a new invoice is rejected if it is already paid or belongs to another order;
  - an order is bought at most once; a purchase interrupted by a restart is not repeated;
  - the purchase stops if the Fragment price grew by more than 5 %;
  - a customer can have at most 5 unpaid, expired or failed orders in 24 hours.
- Customers never see technical errors. The server log gets the time, user, order and error text.
- Admins are notified about errors only.

### What you need

- Python 3.10+.
- The **fragment-web-api** library.
- Fragment cookies, the seed phrase of the TON wallet connected on Fragment, a tonapi.io key and a
  Telegram bot token. Where to get each value: [config_examples/README.md](config_examples/README.md).
- Funds on the wallet: USDT (TON network) for purchases and a little TON for gas.
- Payment provider keys: RollyPay and/or xRocket.

### Installation

Clone both repositories **side by side**:

```
some-folder/
  fragment-web-api/                     (the library)
  telegram-shop-on-fragment-web-api/    (this bot)
```

```bash
cd telegram-shop-on-fragment-web-api
python -m venv .venv
# Windows: .venv\Scripts\python   Linux/macOS: .venv/bin/python
.venv/bin/python -m pip install --require-hashes -r requirements.txt
```

The bot finds the library in `../fragment-web-api` by itself. Instead, you can install it into the
environment, for example on a server: `pip install --no-deps ../fragment-web-api`. The library's pinned
dependencies are already in `requirements.txt`.

### Configuration

Copy `.env.example` to `.env` and fill it in. The minimum:

```ini
FRAGMENT_COOKIES_FILE=cookie.json
TON_MNEMONIC=word1 word2 ... word24
TONAPI_KEY=AE...
BOT_TOKEN=123456:ABC...
BOT_ADMIN_IDS=your_telegram_id
```

Any secret can be written directly (`TONAPI_KEY=...`) or kept in a separate file (`TONAPI_KEY_FILE=...`).
`.env`, cookie and seed files and the order database `bot.db` are excluded from git. All options are
described in `.env.example`. Your Telegram id: start the bot and send it `/myid`.

### Running

```bash
.venv/bin/python -m bot check   # checks the token, Fragment login, prices, wallet, balance (buys nothing)
.venv/bin/python -m bot         # start the bot; stop with Ctrl+C
```

Commands: `/start` (menu), `/info`, `/myid`, `/admin` (admins only, not shown in the menu).

### How the bot pays Fragment

By default the bot pays Fragment **in USDT on the TON network** (`FRAGMENT_PAYMENT_METHOD=usdt_ton`),
`ton` pays in TON. Shop prices are based on Fragment's USD price, so with USDT the TON exchange rate
does not affect your cost. Limits per purchase: `FRAGMENT_MAX_PURCHASE_USDT` and
`FRAGMENT_MAX_PURCHASE_TON` (100 each). The library's safety checks (allowed addresses, amounts,
your own wallet) always apply.

### Payment providers

| Provider | Enabled by | Customer pays |
|---|---|---|
| RollyPay | `ROLLYPAY_API` | RUB, card / SBP |
| xRocket | `XROCKET_API` | crypto in @xRocket (`XROCKET_CURRENCY`, USDT by default) + a fixed fee |

- **polling** (default): every 30 seconds the bot asks the provider about unpaid invoices.
- **webhook**: the provider notifies the bot about the payment. You need a public HTTPS address (a server
  with a domain, for example nginx + Let's Encrypt) that forwards requests to the bot's `WEBHOOK_PORT`.
  The signature is verified, and the payment status is re-checked through the provider's API anyway.

To add a provider, subclass `PaymentProvider` in `bot/payments/` (methods `create_invoice`,
`get_status`, `cancel`) and register it in `REGISTRY` in `bot/payments/__init__.py`.

### Texts

All messages, buttons, statuses and admin texts are in **`bot/texts.py`**. The bot replaces placeholders
like `{number}` with data: do not rename them. Formatting is Telegram HTML. If a text is broken, the bot
does not start and tells you which text and what is wrong. The "Info" text is easier to change in `/admin`.

### Project layout

```
bot/
  __main__.py      start / check
  settings.py      reads .env, passes the secrets to the library
  shop.py          builds providers, service, dispatcher
  services.py      order lifecycle, anti-fraud, purchase
  storage.py       SQLite (orders, history, settings, payments)
  handlers/        customer, admin panel, bottom menu
  payments/        base.py, rollypay.py, xrocket.py
  webhook.py       webhook server (aiohttp)
  texts.py         all texts
config_examples/   example secret files (fake values)
tests/             offline tests
```

### License

[The Unlicense](LICENSE): the code is released into the **public domain**. Anyone may copy, modify,
use, sell and distribute it for any purpose without any conditions, not even attribution.

The code was written with the help of an AI model (Claude, Anthropic) under human direction. It is
provided **as is, without any warranty**. Check it yourself before you trust it with real money.

---

<a id="русский"></a>

## Русский

Telegram-бот-магазин, который продаёт **Telegram Stars** и **Telegram Premium** любому пользователю
Telegram. Он берёт цену с Fragment, добавляет вашу наценку и показывает её в долларах и рублях.
Клиент платит через платёжную систему, а бот затем покупает товар на [fragment.com](https://fragment.com)
с **вашего TON-кошелька** в USDT (сеть TON) или TON. С Fragment бот работает через библиотеку
**fragment-web-api**, это отдельный репозиторий.

> **Неофициальный проект**, не связан с Telegram и Fragment.
> Интерфейс бота на **русском**. Все тексты лежат в `bot/texts.py`, их можно перевести.

### Возможности

- Меню на клавиатуре внизу: купить Stars (пакеты Fragment или своё количество в пределах лимита),
  купить Premium (3/6/12 месяцев), мои заказы, информация.
- Покупка себе или любому `@username`. Получатель сразу проверяется на Fragment.
- Статусы заказа: ожидает оплаты → оплачен → завершён / истёк / ошибка. У каждого заказа порядковый
  номер и случайный код.
- Платёжки: на данный момент **RollyPay** (карта / СБП, рубли) и **xRocket** (криптовалюта через @xRocket). Каждая
  работает в режиме опроса или вебхука. Новая платёжка добавляется одним классом.
- Админка (`/admin`): заказы и поиск, ручная смена статуса, кнопка «выполнить покупку», наценка в %,
  курс доллара, лимиты Stars, комиссия xRocket, текст «Информация», балансы кошелька.
- Антифрод:
  - один заказ — один счёт;
  - товар выдаётся только при переходе «ожидает оплаты» → «оплачен», подтверждённом платёжкой;
  - новый счёт отклоняется, если он уже оплачен или принадлежит другому заказу;
  - заказ покупается не больше одного раза, покупка, прерванная перезапуском, не повторяется;
  - покупка останавливается, если цена на Fragment выросла больше чем на 5 %;
  - у клиента не больше 5 неоплаченных, истёкших или ошибочных заказов за 24 часа.
- Клиент никогда не видит технических ошибок. В лог сервера пишутся время, пользователь, заказ и
  текст ошибки.
- Админам приходят уведомления только об ошибках.

### Что понадобится

- Python 3.10+.
- Библиотека **fragment-web-api**.
- Cookie Fragment, seed-фраза TON-кошелька, подключённого на Fragment, ключ tonapi.io и токен
  Telegram-бота. Где взять каждое значение: [config_examples/README.md](config_examples/README.md).
- Средства на кошельке: USDT (сеть TON) на покупки и немного TON на газ.
- Ключи платёжек: RollyPay и/или xRocket.

### Установка

Склонируйте оба репозитория **рядом**:

```
какая-то-папка/
  fragment-web-api/                     (библиотека)
  telegram-shop-on-fragment-web-api/    (этот бот)
```

```bash
cd telegram-shop-on-fragment-web-api
python -m venv .venv
# Windows: .venv\Scripts\python   Linux/macOS: .venv/bin/python
.venv/bin/python -m pip install --require-hashes -r requirements.txt
```

Бот сам находит библиотеку в `../fragment-web-api`. Вместо этого её можно установить в окружение,
например на сервере: `pip install --no-deps ../fragment-web-api`. Закреплённые зависимости
библиотеки уже есть в `requirements.txt`.

### Настройка

Скопируйте `.env.example` в `.env` и заполните. Минимум:

```ini
FRAGMENT_COOKIES_FILE=cookie.json
TON_MNEMONIC=слово1 слово2 ... слово24
TONAPI_KEY=AE...
BOT_TOKEN=123456:ABC...
BOT_ADMIN_IDS=ваш_telegram_id
```

Любой секрет можно вписать прямо (`TONAPI_KEY=...`) или вынести в отдельный файл (`TONAPI_KEY_FILE=...`).
`.env`, файлы cookie и seed и база заказов `bot.db` исключены из git. Все параметры описаны
в `.env.example`. Свой Telegram id: запустите бота и отправьте ему `/myid`.

### Запуск

```bash
.venv/bin/python -m bot check   # проверка токена, входа на Fragment, цен, кошелька, баланса (ничего не покупает)
.venv/bin/python -m bot         # запуск бота; остановка — Ctrl+C
```

Команды: `/start` (меню), `/info`, `/myid`, `/admin` (только для админов, в меню не показывается).

### Чем бот платит Fragment

По умолчанию бот платит Fragment **в USDT в сети TON** (`FRAGMENT_PAYMENT_METHOD=usdt_ton`), `ton` —
в TON. Цены магазина считаются от цены Fragment в долларах, поэтому при оплате в USDT курс TON
не влияет на себестоимость. Лимиты одной покупки: `FRAGMENT_MAX_PURCHASE_USDT` и
`FRAGMENT_MAX_PURCHASE_TON` (по 100). Проверки безопасности библиотеки (разрешённые адреса, суммы,
свой кошелёк) действуют всегда.

### Платёжки

| Платёжка | Включается | Клиент платит | Примечания |
|---|---|---|---|
| RollyPay | `ROLLYPAY_API` | рубли, карта / СБП |
| xRocket | `XROCKET_API` | криптовалюта в @xRocket (`XROCKET_CURRENCY`, по умолчанию USDT) + фиксированная комиссия |

- **polling** (по умолчанию): бот раз в 30 секунд спрашивает платёжку о неоплаченных счетах.
- **webhook**: платёжка сама сообщает боту об оплате. Нужен публичный HTTPS-адрес (сервер с доменом,
  например nginx + Let's Encrypt), который перенаправляет запросы на `WEBHOOK_PORT` бота. Подпись
  проверяется, а статус платежа всё равно перепроверяется через API платёжки.

Чтобы добавить платёжку, создайте наследника `PaymentProvider` в `bot/payments/` (методы
`create_invoice`, `get_status`, `cancel`) и зарегистрируйте его в `REGISTRY` в `bot/payments/__init__.py`.

### Тексты

Все сообщения, кнопки, статусы и тексты админки лежат в **`bot/texts.py`**. Метки вроде `{number}`
бот заменяет данными: не переименовывайте их. Форматирование — HTML Telegram. Если текст сломан,
бот не запустится и напишет, в каком тексте и что не так. Текст «Информация» удобнее менять в `/admin`.

### Структура

```
bot/
  __main__.py      запуск / проверка
  settings.py      читает .env, передаёт секреты библиотеке
  shop.py          собирает платёжки, сервис, диспетчер
  services.py      жизненный цикл заказа, антифрод, покупка
  storage.py       SQLite (заказы, история, настройки, платежи)
  handlers/        клиент, админка, нижнее меню
  payments/        base.py, rollypay.py, xrocket.py
  webhook.py       сервер вебхуков (aiohttp)
  texts.py         все тексты
config_examples/   образцы файлов с секретами (фиктивные значения)
tests/             офлайн-тесты
```

### Лицензия

[The Unlicense](LICENSE): код передан в **общественное достояние**. Любой может копировать, изменять,
использовать, продавать и распространять его для любых целей без каких-либо условий, даже без
указания автора.

Код написан с помощью нейросети (Claude, Anthropic) под руководством человека. Он предоставляется
**как есть, без каких-либо гарантий**. Перед тем как доверять ему настоящие деньги, проверьте его сами.

---

<a id="donate"></a>

## Donate 

USDT-TON
UQAofMXUIsd3tYANrkQ5qTHc0BdMSwNw8ZkocQgZhWVFt3BI
