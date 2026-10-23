"""Run from the repository folder:

    python -m bot           start the bot
    python -m bot check     check settings: prices, wallet, balance, Fragment link (pays nothing)

Options: ``--env PATH`` (default ``.env``).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

try:
    import fragment_api  # noqa: F401  (installed with `pip install --no-deps ../fragment-web-api`)
except ImportError:  # not installed: use a clone of the library next to this repository
    for _name in ("fragment-web-api", "fragment-web-to-api"):
        _lib = Path(__file__).resolve().parents[2] / _name
        if (_lib / "fragment_api").is_dir():
            sys.path.insert(0, str(_lib))
            break

from fragment_api.exceptions import ConfigError, FragmentAPIError  # noqa: E402
from fragment_api.fragment.models import from_nano, to_nano  # noqa: E402
from fragment_api.ton import Address  # noqa: E402

from aiogram import Bot  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError  # noqa: E402
from aiogram.types import BotCommand  # noqa: E402
from aiogram.utils.token import TokenValidationError  # noqa: E402

from .messenger import AiogramMessenger  # noqa: E402
from .settings import Settings  # noqa: E402
from .shop import COMMANDS, build_dispatcher, build_service  # noqa: E402
from .text_check import check_texts  # noqa: E402
from .webhook import Route, start_webhook_server  # noqa: E402

log = logging.getLogger("bot")


def make_bot(settings: Settings) -> Bot:
    if not settings.bot_token:
        raise ConfigError("не задан токен бота: строка BOT_TOKEN=... в .env (токен от @BotFather)")
    try:
        # HTML formatting for every message the bot sends (bold, code, links in texts)
        return Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML,
                                                                    link_preview_is_disabled=True))
    except TokenValidationError:
        raise ConfigError("BOT_TOKEN имеет неверный формат (ожидается 123456789:AA...)") from None


async def run_bot(settings: Settings) -> None:
    bot = make_bot(settings)
    fragment = settings.build_fragment()
    service = build_service(settings, fragment, AiogramMessenger(bot))
    dp = build_dispatcher(service)
    background = webhook = None
    try:
        me = await bot.get_me()
        log.info("bot @%s started, admins: %s", me.username, sorted(settings.admin_ids) or "none")
        if not settings.admin_ids:
            log.warning("BOT_ADMIN_IDS is empty: purchases are disabled. Send /myid to the bot.")
        try:
            await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in COMMANDS])
        except (TelegramAPIError, TelegramNetworkError) as exc:
            log.warning("setMyCommands failed: %s", exc)
        log.info("shop: markup %s%%, 1$ = %s RUB, payments: %s", service.settings.markup_percent,
                 service.settings.usd_rub_rate, ", ".join(service.providers) or "none")
        routes = {}
        rollypay = service.providers.get("rollypay")
        if rollypay is not None:
            rollypay.return_url = f"https://t.me/{me.username}"  # back to the bot after paying
            if settings.rollypay_test:
                log.warning("RollyPay TEST mode: test payments are free but orders are bought with REAL TON; "
                            "RollyPay is shown to admins only")
            if settings.rollypay_mode == "webhook":
                routes["rollypay"] = Route(settings.webhook_path, settings.rollypay_signing_secret)
            else:
                log.info("RollyPay: checking payments every %.0f s", settings.rollypay_poll_interval)
        xrocket = service.providers.get("xrocket")
        if xrocket is not None:
            xrocket.return_url = f"https://t.me/{me.username}"
            if settings.xrocket_testnet:
                log.warning("xRocket TESTNET: testnet coins are free but orders are bought with REAL TON; "
                            "xRocket is shown to admins only")
            if settings.xrocket_mode == "webhook":
                routes["xrocket"] = Route(settings.xrocket_webhook_path, settings.xrocket_webhook_secret)
            else:
                log.info("xRocket: checking invoices every %.0f s", settings.xrocket_poll_interval)
        if routes:
            webhook = await start_webhook_server(service, host=settings.webhook_host, port=settings.webhook_port,
                                                 **routes)
        background = asyncio.create_task(service.run_background())
        await dp.start_polling(bot, handle_signals=False)
    finally:
        if background:
            background.cancel()
        if webhook:
            await webhook.cleanup()
        for provider in service.providers.values():
            await provider.aclose()
        service.storage.close()
        await fragment.aclose()
        await bot.session.close()


async def check(settings: Settings) -> int:
    ok = True
    print(f"Админы бота: {sorted(settings.admin_ids) or 'не заданы (BOT_ADMIN_IDS)'}")
    try:
        bot = make_bot(settings)
    except ConfigError as exc:
        print(f"Токен бота: {exc}")
        ok = False
    else:
        try:
            me = await bot.get_me()
            print(f"Токен бота: OK, бот @{me.username}")
        except (TelegramAPIError, TelegramNetworkError) as exc:
            print(f"Токен бота: ОШИБКА ({exc})")
            ok = False
        finally:
            await bot.session.close()
    async with settings.build_fragment() as f:
        try:
            print("Fragment: вход по cookie", "OK" if await f.client.is_logged_in() else "НЕ выполнен (обновите cookie)")
            p = await f.get_stars_price(50)
            print(f"Цена 50 Stars: {p.price_ton} TON (${p.price_usd})")
            session = await f.client.wallet_session()
            linked = Address.parse(session.address) if session and session.address else None
            print("Кошелёк, подключённый на Fragment:", linked.to_str(bounceable=False) if linked else "нет")
        except FragmentAPIError as exc:
            print(f"Fragment: ОШИБКА {type(exc).__name__}: {exc}")
            return 1
        if f.wallet is None:
            print("Seed: НЕ задан (TON_MNEMONIC) — покупки недоступны")
            return 1
        print(f"Кошелёк из seed ({f.wallet.VERSION}): {f.wallet_address}")
        match = linked is not None and linked == f.wallet.address
        print("Совпадает с кошельком на Fragment:", "ДА" if match else "НЕТ — покупки будут заблокированы")
        ok &= match
        if f.tonapi is None:
            print("Ключ tonapi: НЕ задан (TONAPI_KEY)")
            return 1
        try:
            acc = await f.tonapi.get_account(f.wallet.address)
            balance = int(acc.get("balance", 0))
            print(f"Статус кошелька: {acc.get('status')}, баланс: {balance / 1e9} TON")
        except FragmentAPIError as exc:
            print(f"tonapi: ОШИБКА {exc}")
            return 1
        need = to_nano(p.price_ton + f.safety.fee_reserve_ton)
        if balance < need:
            print(f"ВНИМАНИЕ: для покупки 50 Stars нужно около {from_nano(need)} TON — пополните кошелёк")
    print("\nИтог:", "настройки в порядке" if ok else "есть проблемы, см. выше")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m bot", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="run", choices=["run", "check"])
    ap.add_argument("--env", default=".env")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)  # one INFO line per update otherwise
    problems = check_texts()
    if problems:
        print("Ошибки в texts.py (исправьте и запустите снова):", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        return 2
    try:
        settings = Settings.load(args.env)
        if args.command == "check":
            return asyncio.run(check(settings))
        asyncio.run(run_bot(settings))
    except ConfigError as exc:
        print(f"Ошибка настройки: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
