"""ConfigStore tests — encrypted-at-rest round-trip + redaction + gating."""

from __future__ import annotations

import pytest

from apex.onboarding.store import ConfigStore

# The store persists secrets only when `cryptography` is available.
pytest.importorskip("cryptography")


def _payload() -> dict:
    return {
        "ig": {"acc_type": "DEMO", "username": "alex", "password": "s3cret!", "api_key": "ABC123KEY", "account_id": ""},
        "anthropic": {"api_key": "sk-ant-abcd1234", "model": "claude-sonnet-4-6"},
        "risk": {"profile": "prop_ftmo", "starting_equity": 100000, "account_currency": "GBP",
                 "active_markets": ["US500", "EURUSD"], "daily_target_pct": 0.5, "trading_enabled": False},
    }


def test_unconfigured_when_empty(tmp_path):
    store = ConfigStore(tmp_path / "cfg")
    assert store.is_configured() is False
    assert store.load() is None


def test_save_load_roundtrip(tmp_path):
    store = ConfigStore(tmp_path / "cfg")
    store.save(_payload())

    assert store.is_configured() is True
    loaded = store.load()
    assert loaded is not None
    assert loaded["ig"]["username"] == "alex"
    assert loaded["ig"]["password"] == "s3cret!"
    assert loaded["anthropic"]["api_key"] == "sk-ant-abcd1234"
    assert loaded["risk"]["profile"] == "prop_ftmo"


def test_encrypted_on_disk(tmp_path):
    store = ConfigStore(tmp_path / "cfg")
    store.save(_payload())
    raw = store.config_path.read_bytes()
    # Secrets must never appear in plaintext in the persisted file.
    assert b"s3cret!" not in raw
    assert b"sk-ant-abcd1234" not in raw


def test_redacted_masks_secrets(tmp_path):
    store = ConfigStore(tmp_path / "cfg")
    store.save(_payload())
    red = store.redacted()
    assert red["ig"]["password"].startswith("••••")
    assert red["ig"]["api_key"].endswith("3KEY")
    assert "s3cret!" not in str(red)


def test_paper_mode_counts_as_configured(tmp_path):
    """Blank IG creds but a chosen profile = explicit PAPER mode = configured."""
    store = ConfigStore(tmp_path / "cfg")
    store.save({
        "ig": {"acc_type": "DEMO", "username": "", "password": "", "api_key": "", "account_id": ""},
        "anthropic": {"api_key": "", "model": "claude-sonnet-4-6"},
        "risk": {"profile": "prop_ftmo", "active_markets": ["US500"]},
    })
    assert store.is_configured() is True


def test_clear(tmp_path):
    store = ConfigStore(tmp_path / "cfg")
    store.save(_payload())
    store.clear()
    assert store.is_configured() is False
