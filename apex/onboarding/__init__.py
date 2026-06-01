"""Web-UI onboarding — the unconfigured-launch state.

The system boots with **no** credentials. The user enters IG keys, the Anthropic
key and a risk profile through the dashboard wizard; those are validated against
the live broker / API and then persisted **encrypted at rest** (Fernet) via
:class:`~apex.onboarding.store.ConfigStore`. ``apex.config`` overlays that stored
config on top of the environment at startup, and the heartbeat stays locked until
onboarding completes (see ``main.py`` + :data:`~apex.onboarding.runtime.RUNTIME`).
"""

from apex.onboarding.runtime import RUNTIME
from apex.onboarding.store import STORE, ConfigStore

__all__ = ["RUNTIME", "STORE", "ConfigStore"]
