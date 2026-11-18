"""Offline tests v1.1.0b9: kein X-Device-Header, kein 'homeassistant' in ausgehenden Requests."""
from __future__ import annotations

from pathlib import Path

import pytest

from test_b6_login import EU, JP, FakeServer, _run, api


@pytest.mark.parametrize("profile", [EU, JP])
def test_idm_headers_have_no_x_device(profile):
    h = api._idm_headers("dev1", profile, ts="1", nonce="n")
    assert not any(k.lower() == "x-device" for k in h)
    assert "X-Device-Id" in h


@pytest.mark.parametrize("region", ["eu", "jp_1"])
def test_login_requests_leak_no_homeassistant(region):
    srv = FakeServer()
    _run(region, srv)
    assert srv.calls
    for call in srv.calls:
        for k, v in call["headers"].items():
            assert k.lower() != "x-device"
            assert "homeassistant" not in (k + v).lower().replace(" ", "")
        assert "homeassistant" not in str(call["body"]).lower().replace(" ", "")


def test_no_x_device_literal_in_source():
    assert '"X-Device"' not in Path(api.__file__).read_text(encoding="utf-8")
