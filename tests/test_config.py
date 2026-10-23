"""Bot settings (.env parsing lives in the bot, not in the library)."""

import os
from decimal import Decimal

import pytest

from bot.settings import Settings, parse_env_file
from fragment_web_api.exceptions import ConfigError
from fragment_web_api.ton import mnemonic

TWELVE = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith(("FRAGMENT_", "TON_", "TONAPI_", "BOT_")):
            monkeypatch.delenv(k)


def test_parse_env_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# comment\nexport A=1\nB = 'two words'\nC=\"x=y\"\nD=val # trailing\n\nE=\n", encoding="utf-8")
    assert parse_env_file(p) == {"A": "1", "B": "two words", "C": "x=y", "D": "val", "E": ""}


def test_inline_values(tmp_path):
    (tmp_path / "cookie.json").write_text('{"stel_ssid": "a", "stel_token": "b"}')
    (tmp_path / ".env").write_text(
        f"FRAGMENT_COOKIES_FILE=cookie.json\nTON_MNEMONIC={TWELVE}\nTONAPI_KEY=KEY123\n"
        "BOT_TOKEN=123:abc\nBOT_ADMIN_IDS=1, 2\nFRAGMENT_MAX_PURCHASE_TON=25\nFRAGMENT_ALLOWED_DESTINATIONS=any\n"
    )
    s = Settings.load(tmp_path / ".env")
    assert s.mnemonic == TWELVE and s.tonapi_key == "KEY123" and s.bot_token == "123:abc"
    assert s.admin_ids == {1, 2} and s.max_purchase_ton == Decimal("25")
    assert s.cookies_file == tmp_path / "cookie.json"
    for secret in ("abandon", "KEY123", "123:abc", "stel_ssid"):
        assert secret not in repr(s)
    f = s.build_fragment()
    assert f.wallet is not None and f.wallet.VERSION == "v5r1"
    assert f.safety.allowed_destinations is None and f.safety.max_amount_ton == Decimal("25")


def test_values_from_files(tmp_path):
    words = " ".join(mnemonic.generate())
    (tmp_path / "seed.txt").write_text(words + "\n")
    (tmp_path / "key").write_text("KEY\n")
    (tmp_path / ".env").write_text(
        "FRAGMENT_COOKIES=stel_ssid=a; stel_token=b\nTON_MNEMONIC_FILE=seed.txt\nTONAPI_KEY_FILE=key\n")
    s = Settings.load(tmp_path / ".env")
    assert s.mnemonic == words and s.tonapi_key == "KEY" and s.cookies_file is None
    assert s.build_fragment().wallet is not None


def test_value_written_into_file_key_is_explained(tmp_path):
    (tmp_path / ".env").write_text(
        "FRAGMENT_COOKIES=stel_ssid=a; stel_token=b\nTONAPI_KEY_FILE=AE" + "X" * 60 + "\n")
    with pytest.raises(ConfigError, match="TONAPI_KEY=значение"):
        Settings.load(tmp_path / ".env")


def test_missing_seed_is_read_only(tmp_path):
    (tmp_path / ".env").write_text("FRAGMENT_COOKIES=stel_ssid=a; stel_token=b\n")
    f = Settings.load(tmp_path / ".env").build_fragment()
    assert f.wallet is None and f.tonapi is None


def test_cookies_required(tmp_path):
    (tmp_path / ".env").write_text("TON_NETWORK=mainnet\n")
    with pytest.raises(ConfigError, match="FRAGMENT_COOKIES"):
        Settings.load(tmp_path / ".env")


def test_env_vars_override_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("FRAGMENT_COOKIES=stel_ssid=a; stel_token=b\nTON_WALLET_VERSION=v4r2\n")
    monkeypatch.setenv("TON_WALLET_VERSION", "v5r1")
    assert Settings.load(tmp_path / ".env").wallet_version == "v5r1"


def test_save_rotated_cookies(tmp_path):
    (tmp_path / "cookie.json").write_text('{"stel_ssid": "a", "stel_token": "b"}')
    (tmp_path / ".env").write_text("FRAGMENT_COOKIES_FILE=cookie.json\n")
    s = Settings.load(tmp_path / ".env")
    s.save_cookies({"stel_ssid": "a", "stel_token": "NEW"})
    assert '"NEW"' in (tmp_path / "cookie.json").read_text()
