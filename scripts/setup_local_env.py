#!/usr/bin/env python
"""One-shot local config provisioner — run by start.bat before launch.

Goal: the user runs start.bat and the Web UI *just works* — they can log in and
the onboarding wizard can reach the local state server, with zero manual env edits.

What it guarantees:

* ``dashboard/.env.local`` has  AUTH_SECRET, AUTH_TRUST_HOST, DASHBOARD_USERNAME,
  DASHBOARD_PASSWORD (plaintext, hash blanked), VPS_URL=http://localhost:8080, and
  a VPS_SECRET that MATCHES the algo's.
* Root ``.env`` has the same VPS_SECRET, and any leftover template placeholders for
  IG / Anthropic keys are blanked so the system boots UNCONFIGURED into the UI
  onboarding state (instead of trying to trade with "your_ig_username").

It also makes a best-effort attempt to reuse credentials already configured on
Vercel (so the local login matches the hosted one) — but always falls back to safe
local defaults if Vercel isn't reachable. Existing real values are never clobbered.
"""

from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
LOCAL = ROOT / "dashboard" / ".env.local"
LOCAL_EXAMPLE = ROOT / "dashboard" / ".env.example"

# Values that mean "not really configured" — safe to overwrite/blank.
PLACEHOLDERS = {
    "", "your_ig_username", "your_ig_password", "your_ig_api_key",
    "sk-ant-...", "change-me", "change-me-to-a-long-random-string",
    "change-me-to-match-the-algo-VPS_SECRET", "replace-with-a-long-random-string",
}


def parse(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip()  # drop inline comments
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]  # strip surrounding quotes (vercel env pull quotes values)
        data[key.strip()] = value
    return data


def upsert(path: Path, updates: dict[str, str]) -> None:
    """Replace each key's line in place; append any that are missing. Preserves the rest."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    done: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) in updates:
            key = m.group(1)
            out.append(f"{key}={updates[key]}")
            done.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in done:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def real(*candidates: str | None) -> str:
    """First candidate that isn't a known placeholder/blank."""
    for c in candidates:
        if c and c.strip() and c.strip() not in PLACEHOLDERS:
            return c.strip()
    return ""


def try_vercel_pull() -> dict[str, str]:
    """Best-effort: pull production env from the linked Vercel project. Never raises."""
    if not (ROOT / "dashboard" / ".vercel").exists():
        return {}
    tmp = ROOT / "dashboard" / ".env.vercel.tmp"
    try:
        subprocess.run(
            ["vercel", "env", "pull", tmp.name, "--environment=production", "--yes"],
            cwd=str(ROOT / "dashboard"),
            capture_output=True, text=True, timeout=90, shell=True,
        )
        if tmp.exists():
            data = parse(tmp)
            return data
    except Exception:
        pass
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
    return {}


def main() -> None:
    # Ensure both files exist (seed from the committed examples).
    if not ENV.exists() and ENV_EXAMPLE.exists():
        shutil.copyfile(ENV_EXAMPLE, ENV)
    if not LOCAL.exists() and LOCAL_EXAMPLE.exists():
        shutil.copyfile(LOCAL_EXAMPLE, LOCAL)

    root = parse(ENV)
    local = parse(LOCAL)

    # Pull from Vercel if the login isn't set yet OR cloud-relay (KV) creds aren't
    # local yet — the latter catches the case where you attach the Redis store on
    # Vercel after the first run.
    have_login = real(local.get("DASHBOARD_USERNAME")) and real(local.get("DASHBOARD_PASSWORD"))
    have_kv = real(root.get("KV_REST_API_URL"), local.get("KV_REST_API_URL"),
                   root.get("UPSTASH_REDIS_REST_URL"), local.get("UPSTASH_REDIS_REST_URL"))
    vercel = try_vercel_pull() if (not have_login or not have_kv) else {}
    pulled = bool(vercel)

    auth_secret = real(local.get("AUTH_SECRET"), vercel.get("AUTH_SECRET")) or secrets.token_urlsafe(32)
    username = real(local.get("DASHBOARD_USERNAME"), vercel.get("DASHBOARD_USERNAME")) or "admin"
    password = real(local.get("DASHBOARD_PASSWORD"), vercel.get("DASHBOARD_PASSWORD")) or "apex"

    # One shared VPS secret across the dashboard and the algo. Prefer an existing real
    # value; otherwise generate one and write it to both.
    vps_secret = real(root.get("VPS_SECRET"), local.get("VPS_SECRET"), vercel.get("VPS_SECRET")) \
        or secrets.token_urlsafe(24)

    # Cloud-relay (Vercel KV / Upstash Redis) credentials, if a store is attached.
    kv_url = real(root.get("KV_REST_API_URL"), local.get("KV_REST_API_URL"),
                  vercel.get("KV_REST_API_URL"), vercel.get("UPSTASH_REDIS_REST_URL"))
    kv_token = real(root.get("KV_REST_API_TOKEN"), local.get("KV_REST_API_TOKEN"),
                    vercel.get("KV_REST_API_TOKEN"), vercel.get("UPSTASH_REDIS_REST_TOKEN"))
    cloud = bool(kv_url and kv_token)

    local_updates = {
        "AUTH_SECRET": auth_secret,
        "AUTH_TRUST_HOST": "true",
        "DASHBOARD_USERNAME": username,
        "DASHBOARD_PASSWORD": password,
        "DASHBOARD_PASSWORD_HASH": "",          # force the simple plaintext path locally
        "VPS_URL": "http://localhost:8080",      # used only in direct (non-KV) mode
        "VPS_SECRET": vps_secret,
    }
    # Root .env: sync the secret and neutralise any leftover template placeholders so
    # the algo boots UNCONFIGURED (UI onboarding) instead of using fake IG creds.
    root_updates = {"VPS_SECRET": vps_secret}
    if not real(root.get("IG_USERNAME")):
        root_updates.update(IG_USERNAME="", IG_PASSWORD="", IG_API_KEY="")
    if not real(root.get("ANTHROPIC_API_KEY")):
        root_updates.update(ANTHROPIC_API_KEY="")
    if cloud:
        # The laptop algo (reads root .env) needs these to join the cloud relay.
        root_updates.update(KV_REST_API_URL=kv_url, KV_REST_API_TOKEN=kv_token)
        local_updates.update(KV_REST_API_URL=kv_url, KV_REST_API_TOKEN=kv_token)

    upsert(LOCAL, local_updates)
    upsert(ENV, root_updates)

    bar = "-" * 52
    print(bar)
    print("  Local config ready.")
    print(f"  Login     : username = {username}    password = {password}")
    if cloud:
        print("  Mode      : CLOUD RELAY (Vercel KV) - configure from anywhere at")
        print("              your Vercel URL; this laptop just runs the engine.")
    else:
        print("  Mode      : LOCAL - open http://localhost:3000")
        print("  Tip       : attach a free Redis store in Vercel + re-run to enable")
        print("              run-from-anywhere (see docs/RUN_ON_VERCEL.md).")
    if pulled:
        print("  (synced settings from your Vercel project)")
    print(bar)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
