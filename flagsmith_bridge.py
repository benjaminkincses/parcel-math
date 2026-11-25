"""Assign checkout variants with Flagsmith and forward live experiment outcomes."""

import atexit
import os
from pathlib import Path

from flagsmith import Flagsmith
from flagsmith.analytics import EventProcessorConfig
from flagsmith.offline_handlers import LocalFileHandler


FLAG = "checkout_price_display"
VARIANTS = {"standard", "landed"}
KEY = os.environ.get("FLAGSMITH_ENVIRONMENT_KEY")


def _client() -> Flagsmith:
    if not KEY:
        snapshot = Path(__file__).with_name("flagsmith-environment.json")
        return Flagsmith(offline_mode=True, offline_handler=LocalFileHandler(str(snapshot)))

    api_url = os.environ.get("FLAGSMITH_API_URL")
    events_url = os.environ.get("FLAGSMITH_EVENTS_URL")
    if api_url and not events_url:
        raise ValueError("Set FLAGSMITH_EVENTS_URL alongside a custom FLAGSMITH_API_URL.")
    config = EventProcessorConfig(events_api_url=events_url) if events_url else None
    return Flagsmith(
        environment_key=KEY,
        api_url=api_url,
        request_timeout_seconds=3,
        enable_events=True,
        event_processor_config=config,
    )


client = _client()
atexit.register(client.close)


def mode() -> str:
    return "offline" if client.offline_mode else "live"


def assign(identity: str) -> str:
    """Evaluate the flag for this participant. Live evaluation tracks an eligible exposure."""
    if client.offline_mode:
        flag = client.get_identity_flags(identity).get_flag(FLAG)
    else:
        flag = client.get_experiment_flag(FLAG, identity)
        if not (flag.enabled and flag.experiment and flag.experiment.in_experiment and flag.variant):
            raise ValueError(f"{FLAG} needs a running experiment with this visitor enrolled.")
    if not flag.enabled:
        return "standard"
    if flag.value not in VARIANTS:
        raise ValueError(f"{FLAG} needs a string value of standard or landed.")
    return flag.value


def record_event(identity: str, name: str, properties: dict | None = None) -> bool:
    """Queue a live outcome; False means the local demo sent no SDK event."""
    if client.offline_mode:
        return False
    data = dict(properties or {})
    client.track_event(name, identifier=identity, value=data.pop("value", None), metadata=data)
    return True
