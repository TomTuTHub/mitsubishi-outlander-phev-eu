"""Mitsubishi Connect US API client (experimental).

Based on the MIT-licensed work of Patrick Cartwright (@pcartwright81):
https://github.com/pcartwright81/mitsubishi_connect_client and
https://github.com/pcartwright81/mitsubishi_connect
Copyright (c) 2019 - 2025 Patrick Cartwright / Joakim Sorensen (MIT License).
The protocol knowledge (endpoints, auth flow, PIN hash) comes from that project;
this module is a re-implementation that returns the same ``VehicleState`` and
offers the same public methods as ``MitsubishiEUClient``.

The US platform is much smaller than the EU one: no battery level, no charge or
climate status, no tire pressures, no lock state. Unsupported commands return
False and set ``last_error_code`` to ``unsupported_in_region``.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from .api import TokenState, VehicleLocation, VehicleState
from .const import US_API_KEY, US_BASIC_AUTH, US_BASE_URL, US_REMOTE_PORT

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
MILES_TO_KM = 1.609344
UNSUPPORTED = "unsupported_in_region"


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def generate_pin_hash(client_nonce: str, server_nonce: str, pin: str) -> str | None:
    """HMAC-SHA256 over the PIN, folded to 128 bit (as in the US app)."""
    try:
        key = base64.b64decode(client_nonce) + b":" + base64.b64decode(server_nonce)
        digest = hmac.new(key, pin.encode("utf-8"), hashlib.sha256).digest()
        folded = b""
        for i in range(4):
            a = digest[i * 4:(i * 4) + 4]
            b = digest[(i + 4) * 4:((i + 4) * 4) + 4]
            folded += bytes(x ^ y for x, y in zip(a, b))
        return base64.b64encode(folded).decode("utf-8")
    except Exception:  # noqa: BLE001
        return None


class MitsubishiUSClient:
    """Client for the US platform, interface-compatible with MitsubishiEUClient."""

    def __init__(self, username: str, password: str, pin: str = "", ssl_context=None) -> None:
        self._ssl_context = ssl_context
        self._username = username.strip()
        self._password = password.strip()
        self._pin = pin
        self._token = TokenState()
        self._account_dn = ""
        self._vehicles_cache: list[dict] = []
        self._session: aiohttp.ClientSession | None = None
        self.last_error_code: str | None = None

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _headers(self, auth: str | None = None) -> dict[str, str]:
        return {
            "content-type": "application/json; charset=UTF-8",
            "user-agent": "Mobile",
            "x-client-id": "mobile",
            "ampapikey": US_API_KEY,
            "connection": "Keep-Alive",
            "authorization": auth or f"Bearer {self._token.access_token}",
        }

    async def _request(
        self, method: str, url: str, *, json_body: dict | None = None,
        data: dict | None = None, auth: str | None = None,
    ) -> Any | None:
        """One HTTP request, returns parsed JSON or None on any failure."""
        if self._session is None:
            if self._ssl_context is not None:
                self._session = aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(ssl=self._ssl_context))
            else:
                self._session = aiohttp.ClientSession()
        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method, url, headers=self._headers(auth),
                    json=data, data=body,
                ) as resp:
                    if not resp.ok:
                        _LOGGER.debug("US API %s %s -> %s", method, url, resp.status)
                        self.last_error_code = str(resp.status)
                        return None
                    return json.loads(await resp.text())
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            _LOGGER.error("US API request failed: %s", err)
            return None

    async def async_close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _store_token(self, data: dict) -> bool:
        try:
            self._token = TokenState(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token", ""),
                expires_at=datetime.now() + timedelta(seconds=int(data.get("expires_in", 3600))),
            )
        except (KeyError, TypeError, ValueError):
            return False
        self._account_dn = data.get("accountDN", self._account_dn)
        return bool(self._token.access_token and self._account_dn)

    async def async_login(self) -> bool:
        data = await self._request(
            "POST", f"{US_BASE_URL}/auth/v1/token",
            data={"grant_type": "password", "username": self._username,
                  "password": self._password},
            auth=US_BASIC_AUTH,
        )
        return bool(data) and self._store_token(data)

    async def async_refresh_token(self) -> bool:
        data = await self._request(
            "POST", f"{US_BASE_URL}/auth/v1/token",
            data={"grant_type": "refresh_token",
                  "refresh_token": self._token.refresh_token},
            auth=US_BASIC_AUTH,
        )
        return bool(data) and self._store_token(data)

    async def _ensure_token(self) -> bool:
        if self._token.is_valid:
            return True
        if self._token.refresh_token and await self.async_refresh_token():
            return True
        return await self.async_login()

    # ------------------------------------------------------------------
    # Vehicles / status
    # ------------------------------------------------------------------

    async def async_get_vehicles(self) -> list[dict]:
        if not await self._ensure_token():
            return []
        data = await self._request(
            "GET", f"{US_BASE_URL}/user/v1/users/{self._account_dn}/vehicles"
        )
        vehicles = []
        for v in (data or {}).get("vehicles", []):
            if not v.get("vin"):
                continue
            vehicles.append({
                "vin": v["vin"],
                "nickName": "",
                "model": {"bodyWork": v.get("model") or "Outlander PHEV",
                          "modelYear": str(v.get("year", ""))},
                "raw": v,
            })
        self._vehicles_cache = vehicles
        return vehicles

    async def async_get_vehicle_status(self, vin: str) -> VehicleState:
        state = VehicleState(vin=vin, internal_vin=vin)
        for v in self._vehicles_cache:
            if v.get("vin") == vin:
                state.nickname = v.get("nickName", "")
        if not await self._ensure_token():
            return state

        vs = await self._request("GET", f"{US_BASE_URL}/avi/v1/vehicles/{vin}/vehiclestate")
        if vs:
            state.raw_data["vehiclestate"] = vs
            self._parse_vehiclestate(vs, state)

        st = await self._request(
            "GET", f"{US_BASE_URL}:{US_REMOTE_PORT}/avi/v1/vehicles/{vin}/vehicleStatus?count=1"
        )
        if st:
            state.raw_data["status"] = st
            self._parse_status(st, state)
        return state

    @staticmethod
    def _parse_vehiclestate(data: dict, state: VehicleState) -> None:
        s = data.get("state", {}) or {}
        loc = s.get("extLocMap") or {}
        lat, lon = _num(loc.get("lat")), _num(loc.get("lon"))
        if lat is not None and lon is not None:
            state.location = VehicleLocation(
                latitude=lat, longitude=lon, last_updated=str(loc.get("ts", "")),
            )
        state.engine_on = str(s.get("ignitionState", "0")) not in ("0", "False", "false")
        rng = _num((s.get("chargingControl") or {}).get("cruisingRangeCombined"))
        if rng is not None:
            state.total_range = rng
        state.last_updated = str(data.get("ts", ""))

    @staticmethod
    def _parse_status(data: dict, state: VehicleState) -> None:
        items = data.get("vhr") or []
        if not items:
            return
        dt = items[0].get("dt", {}) or {}
        diag = dt.get("diagnostic", {}) or {}

        miles = "miles" in str((diag.get("odo") or {}).get("displayMessage", ""))
        factor = MILES_TO_KM if miles else 1.0
        odo = _num((diag.get("odo") or {}).get("value"))
        if odo is not None:
            state.odometer = round(odo * factor, 1)
        spd = _num((diag.get("spd") or {}).get("value"))
        if spd is not None:
            state.speed = round(spd * factor, 1)
        rng = _num((diag.get("availRange") or {}).get("value"))  # "--" -> None
        if rng is not None:
            state.total_range = round(rng * factor, 1)

        state.brake_warning = bool((diag.get("breakWarn") or {}).get("warning"))
        state.engine_oil_warning = bool((diag.get("engineOilWarn") or {}).get("warning"))

        vstat = dt.get("vehicleStatus", {}) or {}
        door_map = {
            "doorFrontLeft": "door_fl_open", "doorFrontRight": "door_fr_open",
            "doorRearLeft": "door_rl_open", "doorRearRight": "door_rr_open",
            "doorHood": "door_hood_open", "doorTrunk": "door_trunk_open",
        }
        for door in (vstat.get("doorStatus") or {}).get("doors", []):
            attr = door_map.get((door.get("position") or {}).get("displayMessage"))
            if attr:
                # "#msg_close_close" / value "0" = closed
                setattr(state, attr, str((door.get("state") or {}).get("value", "0")) != "0")
        for light in (vstat.get("lightStatus") or {}).get("lights", []):
            if (light.get("position") or {}).get("displayMessage") == "lightHead":
                # value "3" = off in the sample data; treat only "1" as on
                state.headlights_on = str((light.get("state") or {}).get("value")) == "1"

    # ------------------------------------------------------------------
    # Remote commands
    # ------------------------------------------------------------------

    async def _remote_operation(self, vin: str, operation: str,
                                pin_token: str | None = None) -> bool:
        if not await self._ensure_token():
            return False
        body = {"vin": vin, "operation": operation, "forced": "true",
                "userAgent": "android"}
        if pin_token:
            body["pinToken"] = pin_token
        self.last_error_code = None
        result = await self._request(
            "POST", f"{US_BASE_URL}:{US_REMOTE_PORT}/avi/v3/remoteOperation",
            json_body=body,
        )
        return result is not None

    async def _get_pin_token(self, vin: str) -> str | None:
        client_nonce = base64.b64encode(os.urandom(32)).decode("utf-8")
        res = await self._request(
            "POST", f"{US_BASE_URL}:{US_REMOTE_PORT}/oauth/v3/remoteOperation",
            json_body={"vin": vin, "clientNonce": client_nonce},
        )
        if not res or "serverNonce" not in res:
            return None
        pin_hash = generate_pin_hash(client_nonce, res["serverNonce"], self._pin)
        if not pin_hash:
            return None
        res = await self._request(
            "POST", f"{US_BASE_URL}:{US_REMOTE_PORT}/oauth/v3/remoteOperation/pin",
            json_body={"vin": vin, "hash": pin_hash, "userAgent": "android"},
        )
        return (res or {}).get("pinToken")

    def _unsupported(self) -> bool:
        self.last_error_code = UNSUPPORTED
        return False

    async def async_start_climate(self, vin: str, temperature: float | None = None) -> bool:
        return await self._remote_operation(vin, "remoteAC")

    async def async_stop_climate(self, vin: str) -> bool:
        return await self._remote_operation(vin, "engineOff")

    async def async_start_engine(self, vin: str) -> bool:
        return await self._remote_operation(vin, "remoteAC")

    async def async_stop_engine(self, vin: str) -> bool:
        return await self._remote_operation(vin, "engineOff")

    async def async_lights(self, vin: str) -> bool:
        return await self._remote_operation(vin, "lights")

    async def async_unlock_doors(self, vin: str) -> bool:
        token = await self._get_pin_token(vin)
        if not token:
            self.last_error_code = self.last_error_code or "pin_token"
            return False
        return await self._remote_operation(vin, "doorUnlock", pin_token=token)

    async def async_lock_doors(self, vin: str) -> bool:
        return self._unsupported()

    async def async_horn(self, vin: str) -> bool:
        return self._unsupported()

    async def async_start_charging(self, vin: str) -> bool:
        return self._unsupported()

    async def async_stop_charging(self, vin: str) -> bool:
        return self._unsupported()

    async def async_take_photo(self, vin: str) -> bool:
        return self._unsupported()

    async def async_refresh_status(self, vin: str) -> bool:
        # The US platform has no refresh trigger; reading the status is enough.
        return True
