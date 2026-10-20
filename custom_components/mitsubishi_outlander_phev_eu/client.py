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

    "jp_3" (Variante 3, in v1.1.0b3 entfernt) faellt auf jp_1 zurueck."""
    region = data.get(CONF_REGION) or DEFAULT_REGION
    if region == REGION_JP_3:
        _LOGGER.info(
            "Region jp_3 (Variante 3) gibt es seit v1.1.0b3 nicht mehr, nutze jp_1. "
            "Bitte den Eintrag ueber 'Neu konfigurieren' auf Variante 1 oder 2 stellen."
        )
        return REGION_JP_1
    return region


def create_client(data: Mapping[str, Any]):
    """Build the client for a config entry / flow input."""
    region = get_region(data)
    kwargs = dict(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        pin=data.get(CONF_PIN, ""),
    )
    if region == REGION_US:
        return MitsubishiUSClient(**kwargs)
    if region in (REGION_JP, REGION_JP_1, REGION_JP_2):
        return MitsubishiEUClient(region=region, **kwargs)
    return MitsubishiEUClient(**kwargs)
