"""Client factory: picks the API client for the configured region."""
from __future__ import annotations

from typing import Any, Mapping

from .api import MitsubishiEUClient
from .api_us import MitsubishiUSClient
from .const import (
    CONF_PASSWORD,
    CONF_PIN,
    CONF_REGION,
    CONF_USERNAME,
    DEFAULT_REGION,
    REGION_US,
)


def get_region(data: Mapping[str, Any]) -> str:
    """Region of a config entry; entries created before region support are EU."""
    return data.get(CONF_REGION, DEFAULT_REGION)


def create_client(data: Mapping[str, Any]):
    """Build the client for a config entry / flow input."""
    cls = MitsubishiUSClient if get_region(data) == REGION_US else MitsubishiEUClient
    return cls(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        pin=data.get(CONF_PIN, ""),
    )
