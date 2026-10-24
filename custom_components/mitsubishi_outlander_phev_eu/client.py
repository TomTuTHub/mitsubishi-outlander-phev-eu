"""Client factory: picks the API client for the configured region."""
from __future__ import annotations

import logging
from typing import Any, Mapping

from .api import MitsubishiEUClient
from .api_us import MitsubishiUSClient
from .const import (
    CONF_PASSWORD,
    CONF_PIN,
    CONF_REGION,
    CONF_USERNAME,
    DEFAULT_REGION,
    REGION_JP_1,
    REGION_JP_2,
    REGION_JP_3,
    REGION_JP,
    REGION_US,
)


_LOGGER = logging.getLogger(__name__)


def get_region(data: Mapping[str, Any]) -> str:
    """Region of a config entry; entries created before region support are EU.

    "jp_2" (entfernt in v1.1.0b4) und "jp_3" (entfernt in v1.1.0b3) fallen still
    auf jp_1 zurueck."""
    region = data.get(CONF_REGION) or DEFAULT_REGION
    if region in (REGION_JP_2, REGION_JP_3):
        _LOGGER.info("Region %s gibt es nicht mehr, nutze jp_1 (Japan / Thailand).", region)
        return REGION_JP_1
    return region


def _ssl_context():
    """Von Home Assistant vorgewaermter SSL-Kontext (kein Zertifikat-Laden im Event-Loop).
    None, wenn HA-Helfer nicht verfuegbar (z. B. in Offline-Tests)."""
    try:
        from homeassistant.util.ssl import client_context
    except ImportError:
        return None
    return client_context()


def create_client(data: Mapping[str, Any], use_ha_ssl: bool = False):
    """Build the client for a config entry / flow input."""
    region = get_region(data)
    kwargs = dict(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        pin=data.get(CONF_PIN, ""),
    )
    # use_ha_ssl=True nur aus dem Event-Loop aufrufen (Setup / Config-Flow)
    kwargs["ssl_context"] = _ssl_context() if use_ha_ssl else None
    if region == REGION_US:
        return MitsubishiUSClient(**kwargs)
    if region in (REGION_JP, REGION_JP_1):
        return MitsubishiEUClient(region=region, **kwargs)
    return MitsubishiEUClient(**kwargs)
