"""ConfigStore — encrypted-at-rest persistence for onboarding config.

Credentials entered in the Web UI are written to an encrypted file under the
config dir (``~/.apex`` by default, override with ``APEX_CONFIG_DIR``). Encryption
uses Fernet (AES-128-CBC + HMAC) from the ``cryptography`` package.

Master-key resolution order:

1. ``APEX_MASTER_KEY`` env var (a urlsafe-base64 Fernet key) — use this on a VPS so
   the key lives in the environment, not on disk.
2. ``<config_dir>/master.key`` — generated on first save, ``chmod 600``.

Design rules:

* **Never** write secrets in plaintext. If ``cryptography`` is unavailable,
  :meth:`save` raises — it does not silently downgrade.
* Reading degrades gracefully: a missing file / missing library / bad key yields
  "unconfigured" rather than crashing, so the app always reaches the onboarding UI.
* The store knows nothing about :mod:`apex.config` (no import cycle); it just
  round-trips a plain ``dict``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

SCHEMA_VERSION = 1
_SECRET_FIELDS = ("password", "api_key")   # masked in redacted views


def _config_dir() -> Path:
    override = os.getenv("APEX_CONFIG_DIR")
    base = Path(override) if override else Path.home() / ".apex"
    return base


def _try_import_fernet():  # type: ignore[no-untyped-def]
    try:
        from cryptography.fernet import Fernet  # noqa: WPS433 (local import by design)

        return Fernet
    except Exception:  # pragma: no cover - exercised only when lib absent
        return None


class ConfigStore:
    """Encrypted key/value store for the onboarding payload."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self.dir = Path(config_dir) if config_dir else _config_dir()
        self.config_path = self.dir / "runtime.json.enc"
        self.key_path = self.dir / "master.key"

    # ── key management ────────────────────────────────────────────────
    def _fernet(self, *, create: bool = False):  # type: ignore[no-untyped-def]
        """Return a Fernet instance, or ``None`` if encryption is unavailable."""
        Fernet = _try_import_fernet()
        if Fernet is None:
            return None

        env_key = os.getenv("APEX_MASTER_KEY", "").strip()
        if env_key:
            try:
                return Fernet(env_key.encode())
            except Exception:
                logger.error("APEX_MASTER_KEY is not a valid Fernet key — ignoring it.")

        if self.key_path.exists():
            return Fernet(self.key_path.read_bytes().strip())

        if not create:
            return None

        # First save: generate and persist a master key with tight permissions.
        self.dir.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        self.key_path.write_bytes(key)
        _restrict(self.key_path)
        logger.info("Generated new Apex master key at {}", self.key_path)
        return Fernet(key)

    # ── public API ────────────────────────────────────────────────────
    def is_configured(self) -> bool:
        """True when a decryptable config with usable settings exists on disk."""
        data = self.load()
        if not data:
            return False
        ig = data.get("ig", {})
        risk = data.get("risk", {})
        # Configured = either real IG creds OR an explicit paper-mode risk profile.
        has_ig = bool(ig.get("username") and ig.get("password") and ig.get("api_key"))
        has_profile = bool(risk.get("profile"))
        return has_ig or has_profile

    def load(self) -> dict[str, Any] | None:
        """Decrypt and return the stored config, or ``None`` if absent/unreadable."""
        if not self.config_path.exists():
            return None
        fernet = self._fernet(create=False)
        if fernet is None:
            logger.warning("Encrypted config present but no key/cryptography — treating as unconfigured.")
            return None
        try:
            raw = fernet.decrypt(self.config_path.read_bytes())
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:  # bad key, tampered file, corrupt JSON
            logger.error("Could not decrypt runtime config: {}", exc)
            return None

    def save(self, data: dict[str, Any]) -> None:
        """Encrypt and persist the config. Raises if encryption is unavailable."""
        fernet = self._fernet(create=True)
        if fernet is None:
            raise RuntimeError(
                "Cannot persist credentials securely: install `cryptography` "
                "(pip install cryptography). Refusing to write secrets in plaintext."
            )
        payload = {"version": SCHEMA_VERSION, **data}
        token = fernet.encrypt(json.dumps(payload).encode("utf-8"))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_bytes(token)
        _restrict(self.config_path)
        logger.info("Saved encrypted runtime config to {}", self.config_path)

    def redacted(self) -> dict[str, Any]:
        """Return the config with secret fields masked (safe to log / send to UI)."""
        data = self.load() or {}
        return _mask(data)

    def clear(self) -> None:
        """Delete the persisted config (used by a 'reset onboarding' action)."""
        try:
            self.config_path.unlink(missing_ok=True)
            logger.info("Cleared runtime config.")
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to clear runtime config: {}", exc)


def _restrict(path: Path) -> None:
    """Best-effort chmod 600 (no-op / ignored on Windows ACL filesystems)."""
    try:
        path.chmod(0o600)
    except Exception:  # pragma: no cover - Windows / restricted FS
        pass


def _mask(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            out[key] = _mask(value)
        elif key in _SECRET_FIELDS and isinstance(value, str) and value:
            out[key] = "••••" + value[-4:] if len(value) >= 4 else "••••"
        else:
            out[key] = value
    return out


# Process-wide singleton.
STORE = ConfigStore()
