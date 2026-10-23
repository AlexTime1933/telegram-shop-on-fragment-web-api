# Where to get the values for `.env` / Где взять значения для `.env`

**[English](#english)** · **[Русский](#русский)**

<a id="english"></a>

## English

All settings live in `.env` (template: `.env.example`). Any secret can be written **directly in `.env`**
(`TONAPI_KEY=...`) or kept **in a separate file** (`TONAPI_KEY_FILE=tonconsole_api`). The files in this
folder are examples of the second way, with fake values. `.env` and real secret files are git-ignored.

| Line in `.env` | What it is | Where to get it | Example file |
|---|---|---|---|
| `FRAGMENT_COOKIES_FILE=cookie.json` | fragment.com cookies | Log in to fragment.com with Telegram and connect your Tonkeeper wallet. Then in the browser F12 → Application → Cookies → `https://fragment.com`, copy `stel_ssid`, `stel_token`, `stel_ton_token`, `stel_dt` | `cookie.example.json` |
| `TON_MNEMONIC=...` | seed phrase of the wallet connected on Fragment: 12 or 24 words separated by spaces | Tonkeeper → Settings → Backup. **This is the key to your money, never show it to anyone** | `seed.example.txt` |
| `TONAPI_KEY=...` | tonapi.io API key | tonconsole.com → log in → Dev Tools / TonAPI → create a key | `tonconsole_api.example` |
| `BOT_TOKEN=...` | Telegram bot token | Message @BotFather in Telegram → `/newbot` → copy the token | `bot_token.example` |
| `BOT_ADMIN_IDS=...` | Telegram ids of the shop admins | Start the bot and send it `/myid` | — |

When you use a file instead of a value, add the `_FILE` suffix: `TON_MNEMONIC_FILE=seed.txt`.
If you mix them up (a value in a `_FILE` line), the bot tells you at start.

<a id="русский"></a>

## Русский

Все настройки лежат в `.env` (шаблон: `.env.example`). Любой секрет можно вписать **прямо в `.env`**
(`TONAPI_KEY=...`) или вынести **в отдельный файл** (`TONAPI_KEY_FILE=tonconsole_api`). Файлы в этой
папке — образцы второго варианта с фиктивными значениями. `.env` и настоящие файлы с секретами
исключены из git.

| Строка в `.env` | Что это | Где взять | Образец файла |
|---|---|---|---|
| `FRAGMENT_COOKIES_FILE=cookie.json` | cookie сайта fragment.com | Войти на fragment.com через Telegram и подключить кошелёк Tonkeeper. Затем в браузере F12 → Application (Приложение) → Cookies → `https://fragment.com` и скопировать `stel_ssid`, `stel_token`, `stel_ton_token`, `stel_dt` | `cookie.example.json` |
| `TON_MNEMONIC=...` | seed-фраза кошелька, подключённого на Fragment: 12 или 24 слова через пробел | Tonkeeper → Настройки → Резервная копия. **Это ключ от денег, никому не показывайте** | `seed.example.txt` |
| `TONAPI_KEY=...` | API-ключ tonapi.io | tonconsole.com → войти → Dev Tools / TonAPI → создать ключ | `tonconsole_api.example` |
| `BOT_TOKEN=...` | токен Telegram-бота | В Telegram написать @BotFather → `/newbot` → скопировать токен | `bot_token.example` |
| `BOT_ADMIN_IDS=...` | Telegram id админов магазина | Запустить бота и отправить ему `/myid` | — |

Если используете файл, а не значение, пишите с суффиксом `_FILE`: `TON_MNEMONIC_FILE=seed.txt`.
Если перепутать (вписать само значение в строку с `_FILE`), бот подскажет при запуске.
