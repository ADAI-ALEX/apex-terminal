"""Cloud relay — lets the laptop algo and the Vercel dashboard share state via a
free Vercel KV (Upstash Redis) store, so no inbound tunnel to the laptop is needed.

The laptop makes only outbound calls: it reads its config from KV and pushes live
state back to KV. The dashboard (on Vercel) reads/writes the same keys. When KV env
vars are absent the whole layer is inert and the system falls back to the local
state-server path.
"""

from apex.cloud.kv import (
    CONFIG_KEY,
    STATE_KEY,
    STATUS_KEY,
    kv_delete,
    kv_enabled,
    kv_get,
    kv_set,
)

__all__ = [
    "CONFIG_KEY", "STATE_KEY", "STATUS_KEY",
    "kv_enabled", "kv_get", "kv_set", "kv_delete",
]
