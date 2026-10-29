"""Echte HA-Tests (pytest-homeassistant-custom-component, Python >= 3.14).

Getrennt von tests/ (die HA-Stubs nutzen). Aufruf:
    python -m pytest tests_ha
"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
