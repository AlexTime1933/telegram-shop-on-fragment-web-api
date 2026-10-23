"""ВСЕ ТЕКСТЫ, КОТОРЫЕ БОТ ПОКАЗЫВАЕТ В TELEGRAM.

Как править:
* Меняйте текст внутри кавычек. Эмодзи можно менять и удалять.
* Метки в фигурных скобках, например {number}, бот заменяет на данные
  (номер заказа, сумму и т.д.). Их можно переставлять внутри текста,
  но нельзя переименовывать или удалять. Список меток указан над каждым текстом.
* Если нужна сама фигурная скобка, пишите её дважды: {{ или }}.
* Форматирование — HTML: <b>жирный</b>, <i>курсив</i>, <code>моноширинный</code>,
  <a href="https://...">ссылка</a>. Символы < > & в обычном тексте пишите как
  &lt; &gt; &amp; (в надписях на КНОПКАХ форматирование не работает, там можно как есть).
* Перенос строки — \\n. Длинный текст можно разбить на несколько строк в кавычках,
  они склеятся (см. примеры ниже).
* После правки перезапустите бота.

Текст раздела «Информация» меняется в админке (/admin); здесь — только значение
по умолчанию, пока админ его не изменил.
"""

# =====================================================================
#  КНОПКИ ГЛАВНОГО МЕНЮ (под сообщениями и внизу экрана)
#  Бот узнаёт нажатие нижней кнопки по её точному тексту, поэтому
#  меняйте надпись только здесь.
# =====================================================================
BTN_STARS = "⭐ Купить Stars"
BTN_PREMIUM = "💎 Купить Premium"
BTN_ORDERS = "📦 Мои заказы"
BTN_INFO = "ℹ️ Информация"

# =====================================================================
#  ОПИСАНИЯ КОМАНД (список в кнопке «Меню» слева от поля ввода)
# =====================================================================
CMD_START = "главное меню"
CMD_MYID = "ваш Telegram id"
CMD_INFO = "информация"

# =====================================================================
#  ДРУГИЕ КНОПКИ КЛИЕНТА
# =====================================================================
BTN_HOME = "🏠 В меню"
BTN_BACK = "⬅️ Назад"
BTN_CANCEL_INPUT = "⬅️ Отмена"
BTN_OTHER_AMOUNT = "✏️ Другое количество"
# метка: {username}
BTN_SELF = "🙋 Себе (@{username})"
# пакет Stars; метки: {quantity}, {usd}, {rub}
BTN_QUOTE_STARS = "{quantity} ⭐ — ${usd} / {rub} ₽"
# срок Premium; метки: {months}, {usd}, {rub}
BTN_QUOTE_PREMIUM = "{months} мес. — ${usd} / {rub} ₽"
# способ оплаты; метки: {title} (название платёжки), {amount}, {currency_sign}
BTN_PAYMENT_METHOD = "{title} — {amount} {currency_sign}"
BTN_GO_TO_PAYMENT = "💳 Перейти к оплате"
BTN_CANCEL_ORDER = "❌ Отменить заказ"
BTN_PAY = "💳 Оплатить"
# заказ в списке «Мои заказы» и в админке; метки: {id}, {icon}, {what}, {recipient}, {usd}
BTN_ORDER = "№{id} {icon} {what} @{recipient} ${usd}"
# {what} для Stars и Premium; метки: {quantity} / {months}
BTN_ORDER_WHAT_STARS = "{quantity}⭐"
BTN_ORDER_WHAT_PREMIUM = "Premium {months}м"

# =====================================================================
#  СТАТУСЫ ЗАКАЗА (первый символ — значок в списках заказов)
# =====================================================================
STATUS_AWAITING_PAYMENT = "⏳ ожидает оплаты"
STATUS_PAID = "💰 оплачен"
STATUS_COMPLETED = "✅ завершён"
STATUS_EXPIRED = "⌛ истёк"
STATUS_ERROR = "❌ ошибка"

# =====================================================================
#  НАЗВАНИЯ ТОВАРОВ
# =====================================================================
# метка: {quantity}
TITLE_STARS = "{quantity} ⭐ Stars"
# метка: {months}
TITLE_PREMIUM = "Telegram Premium на {months} мес."

# =====================================================================
#  ГЛАВНОЕ МЕНЮ
# =====================================================================
WELCOME = (
    "👋 Здравствуйте! Здесь можно купить <b>Telegram Stars</b> и <b>Telegram Premium</b> "
    "себе или любому пользователю Telegram.\n\nКнопки меню всегда доступны внизу экрана."
)
MENU = "Выберите, что хотите купить:"
# метка: {user_id}
MY_ID = "Ваш Telegram id: <code>{user_id}</code>"

# Раздел «Информация» по умолчанию (дальше меняется в /admin)
DEFAULT_INFO = (
    "<b>Как купить</b>\n"
    "1. Выберите Stars или Premium и количество.\n"
    "2. Укажите получателя: себя или @username другого пользователя.\n"
    "3. Выберите способ оплаты и оплатите.\n"
    "4. После подтверждения оплаты бот сам оформит покупку и пришлёт уведомление.\n\n"
    "Статус заказов — в разделе «Мои заказы»."
)

# =====================================================================
#  ПОКУПКА
# =====================================================================
CHOOSE_STARS = "⭐ <b>Telegram Stars</b>\nВыберите количество:"
CHOOSE_PREMIUM = "💎 <b>Telegram Premium</b>\nВыберите срок подписки:"
# метки: {min}, {max} — лимиты магазина (меняются в /admin)
ASK_QUANTITY = "Введите количество Stars (от {min} до {max}):"
# метки: {min}, {max}
BAD_QUANTITY = "Нужно целое число от {min} до {max}. Попробуйте ещё раз:"
ASK_RECIPIENT = "Кому отправить? Напишите @username получателя или нажмите «Себе»."
ASK_RECIPIENT_NO_SELF = "Кому отправить? Напишите @username получателя."
NO_OWN_USERNAME = "У вашего аккаунта нет username — введите получателя вручную"
# метка: {error}
RECIPIENT_FAILED = "❌ {error}\n\nВведите другого получателя или вернитесь в меню."

# =====================================================================
#  КАРТОЧКА ЗАКАЗА ДЛЯ КЛИЕНТА (строки собираются вместе)
# =====================================================================
# метка: {number} (например «№15 (AB3K-7XQ2)»)
ORDER_CARD_TITLE = "<b>Заказ {number}</b>"
# метки: {title}, {recipient}
ORDER_CARD_ITEM = "{title} → @{recipient}"
# метки: {usd}, {rub}
ORDER_CARD_PRICE = "Сумма: <b>${usd} / {rub} ₽</b>"
# метка: {status}
ORDER_CARD_STATUS = "Статус: {status}"
# метки: {amount}, {currency}
ORDER_CARD_INVOICE = "Счёт: {amount} {currency}"
# метка: {time} — когда заказ истечёт (вместе со ссылкой на оплату)
ORDER_CARD_PAY_UNTIL = "\nОплатите до {time}. После этого заказ будет отменён."
CHOOSE_PAYMENT = "\n\nВыберите способ оплаты:"
PAYMENT_UNAVAILABLE = "\n\n⚠️ Оплата временно недоступна. Попробуйте позже."
MY_ORDERS = "📦 <b>Ваши последние заказы</b>"
NO_ORDERS = "У вас пока нет заказов."

# =====================================================================
#  ОПЛАТА
# =====================================================================
# метка: {title}
PAYMENT_METHOD = "Способ оплаты: {title}"
# метки: {amount}, {currency}
PAYMENT_AMOUNT = "К оплате: <b>{amount} {currency}</b>"
PAYMENT_AUTO_CHECK = "Оплата проверяется автоматически: как только она поступит, бот пришлёт уведомление."

# Тестовая платёжка (видна только админам)

# RollyPay (СБП / карта)
ROLLYPAY_TITLE = "💳 СБП / карта"
# описание платежа на странице оплаты RollyPay; метки: {number}, {title}, {recipient}
ROLLYPAY_DESCRIPTION = "Заказ {number}: {title} для @{recipient}"
# xRocket (криптовалюта через @xRocket); метка: {currency} — валюта инвойса (USDT, ...)
XROCKET_TITLE = "🚀 Криптовалюта {currency} (xRocket)"
# описание инвойса в @xRocket; метки: {number}, {title}, {recipient}
XROCKET_DESCRIPTION = "Заказ {number}: {title} для @{recipient}"
XROCKET_INSTRUCTIONS = "Оплата проходит в Telegram-боте @xRocket: нажмите «Перейти к оплате» и подтвердите платёж."
XROCKET_TESTNET_INSTRUCTIONS = (
    "ТЕСТОВАЯ сеть xRocket (@xrocket_testnet_bot): монеты не настоящие, но после оплаты "
    "бот купит заказ на Fragment за настоящие TON."
)
ROLLYPAY_TEST_INSTRUCTIONS = (
    "ТЕСТОВЫЙ режим RollyPay: на странице оплаты нажмите «Симулировать успешную оплату». "
    "Деньги не списываются, но бот купит заказ на Fragment за настоящие TON."
)

# =====================================================================
#  ОШИБКИ, КОТОРЫЕ ВИДИТ КЛИЕНТ
# =====================================================================
# Любая техническая ошибка (платёжка, Fragment, сбой бота). Подробности клиенту не показываются,
# они пишутся в лог сервера: время, пользователь, номер заказа, текст ошибки.
ERR_GENERIC = "⚠️ Ошибка. Попробуйте позже или напишите в поддержку."
ERR_RECIPIENT = "Этот получатель не найден или не может получить подарок. Проверьте username."
ERR_QUANTITY = "Такое количество купить нельзя. Выберите другое."
# метки: {min}, {max}
ERR_STARS_LIMIT = "Количество Stars должно быть от {min} до {max}"
# Ограничение: не больше {limit} неоплаченных / истёкших / ошибочных заказов за 24 часа.
# метки: {limit}, {time} — когда снова можно оформить заказ
ERR_ORDER_LIMIT = (
    "⛔ За последние сутки у вас уже {limit} неоплаченных или незавершённых заказов. "
    "Новый заказ можно будет оформить после {time}."
)
ERR_ORDER_NOT_FOUND = "Заказ не найден"
# метка: {status}
ERR_ORDER_STATUS = "Заказ уже в статусе «{status}»"
ERR_PAYMENT_TIMEOUT = "Время на оплату истекло, оформите заказ заново"
ERR_METHOD_UNAVAILABLE = "Этот способ оплаты недоступен"
# у заказа уже есть счёт другого способа оплаты; метка: {method}
ERR_METHOD_LOCKED = "Для этого заказа уже выбран способ оплаты: {method}. Сменить его нельзя."

# =====================================================================
#  УВЕДОМЛЕНИЯ КЛИЕНТУ
# =====================================================================
# метки: {number}, {title}, {recipient}
# Единственное сообщение покупателю об успешном заказе (после оплаты и покупки на Fragment)
NOTIFY_COMPLETED = "✅ Заказ {number} оплачен и выполнен: {title} отправлены @{recipient}."
# метки: {number}, {reason}
NOTIFY_EXPIRED = "⌛ Заказ {number} истёк: {reason}."
# метка: {number}
NOTIFY_PROBLEM = "❗ С заказом {number} возникла проблема. Администратор уже уведомлён и свяжется с вами."

# =====================================================================
#  УВЕДОМЛЕНИЯ АДМИНАМ
# =====================================================================
# метки: {number}, {title}, {recipient}, {amount}, {currency}
# метки: {number}, {reason}
ADMIN_NOTIFY_ERROR = "❌ Ошибка заказа {number}: {reason}"
# оплачен счёт, который не является счётом заказа; метки: {number}, {provider}, {payment_id}
ADMIN_NOTIFY_DOUBLE_PAYMENT = (
    "⚠️ Заказ {number}: оплачен платёж {provider} {payment_id}, который не является счётом этого заказа. "
    "Заказ по нему не выполняется — проверьте и при необходимости верните деньги."
)
# оплата пришла после истечения заказа; метки: {number}, {provider}, {payment_id}
ADMIN_NOTIFY_LATE_PAYMENT = (
    "⚠️ Заказ {number}: оплата {provider} {payment_id} пришла после истечения заказа. "
    "Автоматически заказ НЕ выполняется. Решите вручную: выполнить его в админке "
    "(статус «оплачен» → «▶️ Выполнить покупку») или вернуть клиенту деньги."
)
# платёжка вернула при создании счёта уже оплаченную или чужую ссылку;
# метки: {number}, {provider}, {payment_id}, {reason}
ADMIN_NOTIFY_SUSPICIOUS_INVOICE = (
    "🚨 Заказ {number}: платёжка {provider} вернула подозрительный счёт {payment_id} ({reason}). "
    "Счёт отклонён, клиенту показана ошибка."
)
# возврат или чарджбэк после оплаты; метки: {number}, {provider}, {payment_id}
ADMIN_NOTIFY_REFUND = (
    "⚠️ По заказу {number} платёжка сообщила о возврате/чарджбэке (платёж {provider} {payment_id}). "
    "Деньги клиенту возвращены — проверьте заказ."
)

# =====================================================================
#  ПРИЧИНЫ (пишутся в историю заказа, видны в уведомлениях и админке)
# =====================================================================
REASON_TIMEOUT = "время на оплату истекло"
REASON_CANCELLED_BY_BUYER = "отменён покупателем"
# метка: {status} (ответ платёжки)
REASON_PROVIDER_STATUS = "платёжка вернула {status}"
REASON_PAID = "оплата подтверждена"
# метка: {other} — номер заказа, которому уже принадлежит этот счёт
REASON_INVOICE_REUSED = "этот счёт уже принадлежит заказу {other}"
# метка: {status} — статус нового счёта по ответу платёжки
REASON_INVOICE_NOT_NEW = "новый счёт уже в статусе {status}"
REASON_BOUGHT = "куплено на Fragment"
REASON_CREATED = "заказ создан"
REASON_MANUAL_STATUS = "изменено вручную"
REASON_MANUAL_FULFILL = "запуск покупки вручную"
# метки: {provider}, {payment_id}, {amount}, {currency}
REASON_INVOICE = "счёт {provider} {payment_id} на {amount} {currency}"
REASON_RESTART = (
    "покупка была прервана перезапуском бота; проверьте кошелёк, "
    "затем выполните заказ вручную или отметьте завершённым"
)
# метки: {now} и {paid} — цена в TON сейчас и при оплате
REASON_PRICE_DRIFT = "цена на Fragment выросла: {now} TON при оплаченных {paid} TON"
# метки: {now}, {paid} — цена Fragment в $ (оплата в USDT)
REASON_PRICE_DRIFT_USD = "цена на Fragment выросла: ${now} при оплаченных ${paid}"
# метка: {hash}
REASON_TX_TIMEOUT = "транзакция отправлена, но подтверждение не пришло; ПРОВЕРЬТЕ кошелёк перед повтором (hash {hash})"
# метка: {error}
REASON_NO_FUNDS = "не хватает средств на кошельке (USDT на покупку или TON на газ): {error}"
REASON_WALLET_LINK = "Fragment просит привязать кошелёк к аккаунту (сделайте в браузере)"
REASON_KYC = "Fragment требует верификацию (KYC)"
# метка: {error}
REASON_SAFETY = "проверка безопасности остановила платёж: {error}"
# метка: {error}
REASON_RECIPIENT = "получатель не подходит: {error}"
# метки: {kind} (тип ошибки), {error}
REASON_FRAGMENT = "{kind}: {error}"
REASON_INTERNAL = "внутренняя ошибка {kind}: {error}"

# =====================================================================
#  АДМИНКА: КНОПКИ
# =====================================================================
# метка: {count}
BTN_ADMIN_ALL_ORDERS = "📋 Все заказы ({count})"
# метки: {status}, {count}
BTN_ADMIN_STATUS_FILTER = "{status} ({count})"
BTN_ADMIN_FIND = "🔎 Найти заказ по номеру"
# метка: {value}
BTN_ADMIN_MARKUP = "📈 Наценка: {value}%"
# метка: {value}
BTN_ADMIN_RATE = "💱 Курс $: {value} ₽"
# метки: {min}, {max}
BTN_ADMIN_STARS_LIMITS = "⭐ Лимит Stars: {min}–{max}"
# метки: {value}, {currency}
BTN_ADMIN_XROCKET_FEE = "🚀 Комиссия xRocket: {value} {currency}"
BTN_ADMIN_INFO = "ℹ️ Текст «Информация»"
BTN_ADMIN_WALLET = "👛 Кошелёк"
BTN_ADMIN_HOME = "🛠 Админка"
BTN_ADMIN_PREV = "◀️"
BTN_ADMIN_NEXT = "▶️"
# метка: {status}
BTN_ADMIN_SET_STATUS = "→ {status}"
BTN_ADMIN_FULFILL = "▶️ Выполнить покупку на Fragment"
BTN_ADMIN_FULFILL_CONFIRM = "▶️ Выполнить"
BTN_ADMIN_REFRESH = "🔄 Обновить"
BTN_ADMIN_TO_LIST = "⬅️ К списку"
BTN_YES = "✅ Да"
BTN_NO = "↩️ Нет"

# =====================================================================
#  АДМИНКА: ЭКРАНЫ
# =====================================================================
# метки: {markup}, {rate}, {stars_min}, {stars_max}, {minutes}
ADMIN_HOME = (
    "🛠 <b>Админка</b>\n\n"
    "Наценка: <b>{markup}%</b>, курс доллара: <b>{rate} ₽</b>\n"
    "Stars в одном заказе: от <b>{stars_min}</b> до <b>{stars_max}</b>\n"
    "Время на оплату: {minutes} мин."
)
ADMIN_ORDERS_TITLE = "📋 <b>Заказы</b> (стр. {page})"
# метки: {status}, {page}
ADMIN_ORDERS_TITLE_STATUS = "📋 <b>Заказы: {status}</b> (стр. {page})"
ADMIN_NO_ORDERS = "\n\nЗаказов нет."
# метка: {status}
ADMIN_STATUS_CHANGED = "Статус: {status}"
# метки: {number}, {title}, {recipient}
ADMIN_FULFILL_CONFIRM = "Купить на Fragment заказ {number}? Будут потрачены средства с кошелька.\n{title} → @{recipient}"
ADMIN_FULFILL_WARNING = (
    "\n\n⚠️ По этому заказу уже отправлялась транзакция. Сначала убедитесь в кошельке, "
    "что она не прошла, иначе заплатите дважды."
)
ADMIN_FULFILLING = "Выполняю…"
# метка: {error}
ADMIN_ERROR = "❌ {error}"
ADMIN_FULFILL_ONLY_PAID = "Выполнить можно только оплаченный заказ или заказ с ошибкой"
ADMIN_STATUS_RACE = "Статус заказа изменился, обновите карточку"
ADMIN_ASK_ORDER = (
    "Введите номер заказа: порядковый (например <code>15</code>) или код "
    "(например <code>AB3K-7XQ2</code>):"
)
ADMIN_ORDER_NOT_FOUND = "Заказ не найден. Введите другой номер:"
# метка: {value}
ADMIN_ASK_MARKUP = (
    "Текущая наценка: <b>{value}%</b>\n"
    "Введите новую наценку в процентах (например <code>15</code> или <code>12.5</code>):"
)
# метка: {value}
ADMIN_MARKUP_SET = "✅ Наценка установлена: {value}%\n\n"
# метка: {value}
ADMIN_ASK_RATE = (
    "Текущий курс: <b>1 $ = {value} ₽</b>\n"
    "Введите новый курс в рублях за доллар (например <code>95.5</code>):"
)
# метка: {value}
ADMIN_RATE_SET = "✅ Курс установлен: 1 $ = {value} ₽\n\n"
# метки: {min}, {max}
ADMIN_ASK_STARS_LIMITS = (
    "Сейчас можно купить от <b>{min}</b> до <b>{max}</b> Stars в одном заказе.\n"
    "Введите новый минимум и максимум через пробел или дефис (например <code>100 10000</code>).\n"
    "Кнопки пакетов вне этих границ скрываются из меню."
)
# метки: {min}, {max}
ADMIN_STARS_LIMITS_SET = "✅ Лимит Stars: от {min} до {max}\n\n"
# метки: {min}, {max} — пределы самого Fragment
ERR_STARS_LIMITS_RANGE = "минимум и максимум должны быть от {min} до {max}, минимум не больше максимума"
ERR_STARS_LIMITS_FORMAT = "нужно два целых числа: минимум и максимум"
# метка: {error}
ADMIN_BAD_VALUE = "Не получилось: {error}. Введите ещё раз:"
ADMIN_NEED_NUMBER = "нужно число"
ERR_MARKUP_RANGE = "наценка должна быть от 0 до 500 %"
ERR_RATE_RANGE = "курс должен быть от 1 до 10000 ₽"
ERR_FEE_RANGE = "комиссия должна быть от 0 до 1000"
# метки: {value}, {currency}
ADMIN_ASK_XROCKET_FEE = (
    "Текущая комиссия xRocket: <b>{value} {currency}</b>\n"
    "Она добавляется к цене каждого нового счёта xRocket. Введите новую комиссию в {currency} "
    "(например <code>0.5</code>, <code>0</code> — без комиссии):"
)
# метки: {value}, {currency}
ADMIN_XROCKET_FEE_SET = "✅ Комиссия xRocket: {value} {currency}\n\n"
# метка: {text} (текущий текст «Информации»)
ADMIN_INFO_CURRENT = "Сейчас в разделе «Информация»:\n\n{text}"
ADMIN_ASK_INFO = (
    "Пришлите новый текст одним сообщением. Форматирование Telegram (жирный, курсив, "
    "ссылки) сохранится."
)
# метка: {error}
ADMIN_BAD_INFO = "Не получилось: {error}. Пришлите другой текст:"
ERR_INFO_EMPTY = "текст не может быть пустым"
ERR_INFO_TOO_LONG = "слишком длинный текст (максимум 3500 символов)"
ADMIN_INFO_SET = "✅ Текст «Информация» обновлён. Так его увидят клиенты:"

# Кошелёк
ADMIN_WALLET_TITLE = "👛 <b>Кошелёк</b>"
ADMIN_WALLET_NO_SEED = "Seed не настроен (TON_MNEMONIC в .env)"
# метки: {version}, {address}
ADMIN_WALLET_ADDRESS = "Адрес ({version}): <code>{address}</code>"
# метка: {ton}
ADMIN_WALLET_BALANCE = "Баланс: <b>{ton} TON</b>"
# метка: {usdt}
ADMIN_WALLET_USDT = "USDT (сеть TON): <b>{usdt}</b>"
# метка: {method}
ADMIN_WALLET_PAY_METHOD = "Оплата Fragment: <b>{method}</b>"
ADMIN_PAY_METHOD_USDT = "USDT (TON)"
ADMIN_PAY_METHOD_TON = "TON"
# метка: {error}
ADMIN_WALLET_BALANCE_ERROR = "Баланс: ошибка ({error})"
ADMIN_WALLET_LINKED = "Привязан к Fragment: ✅ да"
ADMIN_WALLET_NOT_LINKED = "Привязан к Fragment: ❌ нет"
# метка: {error}
ADMIN_WALLET_FRAGMENT_ERROR = "Fragment: ошибка ({error})"

# =====================================================================
#  АДМИНКА: КАРТОЧКА ЗАКАЗА (строки собираются вместе)
# =====================================================================
# метки: {number}, {status}
ADMIN_CARD_TITLE = "<b>Заказ {number}</b> — {status}"
# метка: {buyer_id}
ADMIN_CARD_BUYER = "Покупатель: <code>{buyer_id}</code>"
# метка: {username} — добавляется после покупателя, если у него есть username
ADMIN_CARD_BUYER_USERNAME = " @{username}"
# метки: {created}, {updated}
ADMIN_CARD_DATES = "Создан: {created}, обновлён: {updated}"
# метки: {ton}, {usd}
ADMIN_CARD_FRAGMENT = "Fragment: {ton} TON (${usd})"
# метки: {markup}, {rate}, {usd}, {rub}
ADMIN_CARD_PRICING = "Наценка {markup}%, курс {rate} ₽ → <b>${usd} / {rub} ₽</b>"
# метки: {provider}, {payment_id}
ADMIN_CARD_PAYMENT = "Оплата: {provider} {payment_id}"
# метки: {amount}, {currency} — добавляется к строке оплаты, если счёт выставлен
ADMIN_CARD_PAYMENT_AMOUNT = ", {amount} {currency}"
# метки: {paid}, {completed}
ADMIN_CARD_PAID = "Оплачен: {paid}, завершён: {completed}"
# метка: {req_id}
ADMIN_CARD_FRAGMENT_ORDER = "Заказ Fragment: <code>{req_id}</code>"
# метка: {hash}
ADMIN_CARD_HASH = "Hash сообщения: <code>{hash}</code>"
# метка: {error}
ADMIN_CARD_ERROR = "\n❗ {error}"
ADMIN_CARD_HISTORY = "\n<b>История</b>"
# формат даты и времени (коды Python strftime) и замена для пустой даты
DATETIME_FORMAT = "%d.%m.%Y %H:%M"
NO_VALUE = "—"
