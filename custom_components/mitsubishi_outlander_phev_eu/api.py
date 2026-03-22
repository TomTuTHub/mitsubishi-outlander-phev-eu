"""Mitsubishi Connect EU API Client — Kintaro-Protokoll.

GET-Requests verwenden Query-String-Format (vin=X&internalVin=Y).
POST-Requests verwenden JSON.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from .const import (
    EU_AUTH_URL,
    EU_KINTARO_BASE,
    EU_CLIENT_ID,
    EU_CLIENT_SECRET,
    KINTARO_PKG_NAME,
    KINTARO_APP_CODE,
    KINTARO_HASH,
    KINTARO_SECURITY_KEY,
    KINTARO_JWT_SIGN,
    EP_INIT,
    EP_VEHICLE_LIST,
    EP_VSR,
    EP_CHARGE_DETAILS,
    EP_CLIMATE_DETAILS,
    EP_ENGINE_DETAILS,
    EP_CHARGING_BASE_COST,
    EP_FIRMWARE_STATUS,
    EP_GENERATE_NONCE,
    EP_VERIFY_PIN,
    EP_REFRESH_VSR,
    EP_VEHICLE_LOCATION,
    EP_BATCH_REQUEST_STATUS,
    EP_START_CLIMATE,
    EP_STOP_CLIMATE,
    EP_START_CHARGE,
    EP_STOP_CHARGE,
    EP_LOCK_DOOR,
    EP_UNLOCK_DOOR,
    EP_START_HORN,
    EP_START_LIGHT,
    EP_START_ENGINE,
    EP_STOP_ENGINE,
    EP_TAKE_PHOTO,
    EP_TRACKING_LOCATION,
    EP_PHOTO_HISTORY_LIST,
    EP_PHOTO_HISTORY_DETAILS,
    EP_MILEAGE_HISTORY,
    EP_CHARGING_HISTORY,
    EP_GEOFENCE_ALERT,
    EP_SPEED_ALERT,
    EP_CURFEW_ALERT,
)

_LOGGER = logging.getLogger(__name__)

TOKEN_EXPIRY_MARGIN = timedelta(minutes=5)


# ======================================================================
# Datenmodelle
# ======================================================================

@dataclass
class TokenState:
    access_token: str = ""
    refresh_token: str = ""
    expires_at: datetime = field(default_factory=datetime.now)

    @property
    def is_valid(self) -> bool:
        return bool(self.access_token) and datetime.now() < (self.expires_at - TOKEN_EXPIRY_MARGIN)


@dataclass
class VehicleLocation:
    latitude: float | None = None
    longitude: float | None = None
    last_updated: str = ""


@dataclass
class VehicleState:
    """Kompletter Fahrzeugzustand aus allen API-Endpoints."""
    vin: str = ""
    internal_vin: str = ""
    nickname: str = ""

    # Batterie / Laden (getChargeDetails)
    battery_level: int | None = None
    ev_range: float | None = None
    fuel_range: float | None = None
    total_range: float | None = None
    is_charging: bool = False
    is_plugged_in: bool = False
    charging_remaining_time: int | None = None

    # Motor (getEngineDetails)
    engine_on: bool = False

    # Klima (getClimateDetails)
    ac_on: bool = False
    target_temperature: float | None = None

    # Laden erweitert (getChargeDetails)
    charging_ready: bool = False
    charge_disabled: bool = False

    # VSR Diagnose (getVSR)
    odometer: float | None = None
    speed: float | None = None
    doors_locked: bool | None = None
    battery_12v: int | None = None

    # Türen einzeln (getVSR vehicleStatus.doorStatus)
    door_fl_open: bool = False
    door_fr_open: bool = False
    door_rl_open: bool = False
    door_rr_open: bool = False
    door_hood_open: bool = False
    door_trunk_open: bool = False

    # Fenster einzeln (getVSR vehicleStatus.windowStatus)
    window_fl_open: bool = False
    window_fr_open: bool = False
    window_rl_open: bool = False
    window_rr_open: bool = False
    window_sunroof_open: bool = False

    # Licht (getVSR vehicleStatus.lightStatus)
    headlights_on: bool = False

    # Reifendruck kPa (getVSR)
    tire_fl_pressure: float | None = None
    tire_fr_pressure: float | None = None
    tire_rl_pressure: float | None = None
    tire_rr_pressure: float | None = None

    # Warnungen (getVSR)
    brake_warning: bool = False
    abs_warning: bool = False
    airbag_warning: bool = False
    engine_oil_warning: bool = False
    mil_warning: bool = False

    # Ladekosten (getChargingBaseCost)
    charging_base_cost: float | None = None

    # Firmware (getFirmwareStatus)
    firmware_version: str | None = None

    # Position (getVehicleLocation)
    location: VehicleLocation = field(default_factory=VehicleLocation)

    # Letzte Fahrt (getMileageHistory)
    last_trip_distance: float | None = None
    last_trip_duration: int | None = None
    last_trip_date: str | None = None

    # Letzte Ladung (getChargingHistory)
    last_charge_energy: float | None = None
    last_charge_duration: float | None = None
    last_charge_date: str | None = None

    # Alerts (Geofence/Speed/Curfew)
    geofence_min_radius: int | None = None
    geofence_max_radius: int | None = None
    speed_alert_unit: str | None = None

    # Meta
    last_updated: str = ""
    raw_data: dict = field(default_factory=dict)


# ======================================================================
# Kintaro Krypto
# ======================================================================

def _md5h(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()

def _sha256h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def _base64url_encode(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def _generate_jwt(secret: str) -> str:
    iat_ms = int(time.time() * 1000)
    header = json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":"))
    payload = json.dumps({"iat": iat_ms, "exp": iat_ms}, separators=(",", ":"))
    h_b64 = _base64url_encode(header)
    p_b64 = _base64url_encode(payload)
    signing_input = f"{h_b64}.{p_b64}"
    sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_base64url_encode(sig)}"

def _compute_init_sign(nonce: str) -> str:
    md5_1 = _md5h(KINTARO_APP_CODE + KINTARO_PKG_NAME).upper()
    md5_2 = _md5h(md5_1 + KINTARO_HASH).lower()
    asm = md5_2[18:22] + md5_2[0:13] + md5_2[1:5]
    ns = nonce[7:]
    return _sha256h(nonce + ns + ns + asm).upper()

def _decrypt_init_response(payload_b64: str) -> dict:
    md5_1 = _md5h(KINTARO_APP_CODE + KINTARO_PKG_NAME).upper()
    md5_2 = _md5h(md5_1 + KINTARO_HASH).lower()
    aes_key = md5_2[15:31].encode("ascii")[:16]
    iv = KINTARO_SECURITY_KEY.encode("ascii")[:16]
    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    decrypted = unpad(cipher.decrypt(base64.b64decode(payload_b64)), AES.block_size)
    return json.loads(decrypted.decode("utf-8"))

def _encrypt_body(body_plain: str, enc_key: str) -> str:
    key = enc_key[:16].encode("ascii")
    iv = KINTARO_SECURITY_KEY[:16].encode("ascii")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(body_plain.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("ascii")

def _decrypt_response(payload_b64: str, enc_key: str) -> dict:
    key = enc_key[:16].encode("ascii")
    iv = KINTARO_SECURITY_KEY[:16].encode("ascii")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = unpad(cipher.decrypt(base64.b64decode(payload_b64)), AES.block_size)
    return json.loads(decrypted.decode("utf-8"))

def _compute_sign(enc_body: str, nonce: str, sign_key: str) -> str:
    ns = nonce[7:]
    sign_input = enc_body + nonce + ns + ns + sign_key
    return _sha256h(sign_input).upper()

def _compute_pin_hash(client_nonce_b64: str, server_nonce_b64: str, pin: str) -> str:
    client_bytes = base64.b64decode(client_nonce_b64)
    server_bytes = base64.b64decode(server_nonce_b64)
    hmac_key = client_bytes + b":" + server_bytes
    mac = hmac.new(hmac_key, pin.encode("utf-8"), hashlib.sha256)
    hmac_result = mac.digest()
    xored = bytes(hmac_result[i] ^ hmac_result[i + 16] for i in range(16))
    return base64.b64encode(xored).decode("ascii")


# ======================================================================
# API Client
# ======================================================================

class MitsubishiEUClient:

    def __init__(self, username: str, password: str, pin: str = "") -> None:
        self._username = username
        self._password = password
        self._pin = pin
        self._token = TokenState()
        self._enc_key: str | None = None
        self._sign_key: str | None = None
        self._corr_id = str(uuid.uuid4())
        self._http = httpx.AsyncClient(timeout=30.0)
        self._vehicles_cache: list[dict] = []
        self._internal_vins: dict[str, str] = {}
        self._pin_verified = False
        self._pin_hash: str | None = None

    async def async_close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def async_login(self) -> bool:
        try:
            r = await self._http.post(
                EU_AUTH_URL,
                data={
                    "grant_type": "password",
                    "username": self._username,
                    "password": self._password,
                    "client_id": EU_CLIENT_ID,
                    "client_secret": EU_CLIENT_SECRET,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "okhttp/4.9.0",
                },
            )
            if r.status_code != 200:
                _LOGGER.error("Login fehlgeschlagen: %s", r.status_code)
                return False

            data = r.json()
            self._token = TokenState(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token", ""),
                expires_at=datetime.now() + timedelta(seconds=data.get("expires_in", 3600)),
            )
            return await self._kintaro_init()
        except httpx.RequestError as err:
            _LOGGER.error("Login Fehler: %s", err)
            return False

    async def _kintaro_init(self) -> bool:
        try:
            nonce = str(int(time.time() * 1000))
            sign = _compute_init_sign(nonce)
            jwt = _generate_jwt(KINTARO_JWT_SIGN)
            headers = self._kintaro_headers(nonce, sign)
            headers["knt-app-device-token"] = jwt

            r = await self._http.post(f"{EU_KINTARO_BASE}{EP_INIT}", content="", headers=headers)
            rj = r.json()
            if rj.get("state") != "S":
                _LOGGER.error("Kintaro Init fehlgeschlagen: %s", rj)
                return False

            keys = _decrypt_init_response(rj["payload"])
            self._enc_key = keys["encKey"]
            self._sign_key = keys["signKey"]
            self._pin_verified = False
            return True
        except Exception as err:
            _LOGGER.error("Kintaro Init Fehler: %s", err)
            self._enc_key = ""
            self._sign_key = ""
            return False

    async def async_refresh_token(self) -> bool:
        if not self._token.refresh_token:
            return await self.async_login()
        try:
            r = await self._http.post(
                EU_AUTH_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._token.refresh_token,
                    "client_id": EU_CLIENT_ID,
                    "client_secret": EU_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "okhttp/4.9.0"},
            )
            if r.status_code == 200:
                data = r.json()
                self._token = TokenState(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token", self._token.refresh_token),
                    expires_at=datetime.now() + timedelta(seconds=data.get("expires_in", 3600)),
                )
                return await self._kintaro_init()
            return await self.async_login()
        except httpx.RequestError:
            return await self.async_login()

    async def _ensure_token(self) -> bool:
        if self._token.is_valid and self._enc_key:
            return True
        _LOGGER.debug("Token abgelaufen oder enc_key fehlt, erneuere Session")
        if self._token.refresh_token:
            ok = await self.async_refresh_token()
            if ok:
                _LOGGER.debug("Token-Refresh erfolgreich")
                return True
            _LOGGER.warning("Token-Refresh fehlgeschlagen, versuche neuen Login")
        ok = await self.async_login()
        if not ok:
            _LOGGER.error("Login fehlgeschlagen — API-Zugriff nicht moeglich")
        return ok

    # ------------------------------------------------------------------
    # PIN
    # ------------------------------------------------------------------

    async def _verify_pin(self, vin: str, internal_vin: str) -> bool:
        if not self._pin:
            _LOGGER.warning("Kein PIN konfiguriert")
            return False
        try:
            client_nonce_b64 = base64.b64encode(secrets.token_bytes(32)).decode()
            r_nonce = await self._kintaro_post(EP_GENERATE_NONCE, {
                "vin": vin, "internalVin": internal_vin, "clientNonce": client_nonce_b64,
            })
            if not r_nonce or not r_nonce.get("serverNonce"):
                return False

            pin_hash = _compute_pin_hash(client_nonce_b64, r_nonce["serverNonce"], self._pin)
            r_pin = await self._kintaro_post(EP_VERIFY_PIN, {
                "vin": vin, "internalVin": internal_vin, "pinHash": pin_hash,
            })
            if r_pin and r_pin.get("isValidPIN"):
                self._pin_verified = True
                self._pin_hash = pin_hash
                return True
            _LOGGER.error("PIN ungueltig")
            return False
        except Exception as err:
            _LOGGER.error("PIN Fehler: %s", err)
            return False

    async def _ensure_pin(self, vin: str) -> bool:
        if self._pin_verified:
            return True
        internal_vin = self._internal_vins.get(vin, vin)
        return await self._verify_pin(vin, internal_vin)

    # ------------------------------------------------------------------
    # Request-Infrastruktur
    # ------------------------------------------------------------------

    def _kintaro_headers(self, nonce: str | None = None, sign: str | None = None) -> dict:
        hdrs = {
            "knt-access-token": self._token.access_token,
            "knt-iso-locale": "de_DE",
            "knt-timezone": "Europe/Berlin",
            "knt-correlation-id": self._corr_id,
            "knt-app-key": KINTARO_APP_CODE,
            "knt-app-os": "ANDROID",
            "knt-app-version": "1.3.1",
            "knt-app-unique-id": KINTARO_PKG_NAME,
            "knt-region": "DE",
            "Content-Type": "text/plain",
            "knt-req-id": str(uuid.uuid4()),
            "knt-language": "de",
            "knt-locale": "de_DE",
            "knt-device-os-version": "14",
            "knt-device-model": "Pixel 7",
            "User-Agent": "okhttp/4.9.0",
        }
        if nonce:
            hdrs["knt-timestamp"] = nonce
        if sign:
            hdrs["knt-sign"] = sign
        return hdrs

    async def _kintaro_get(self, endpoint: str, params: dict | None = None) -> dict | None:
        """GET mit Query-String-Format."""
        if not await self._ensure_token():
            _LOGGER.error("GET %s abgebrochen — keine gueltige Session", endpoint)
            raise ConnectionError(f"Keine gueltige API-Session fuer {endpoint}")
        nonce = str(int(time.time() * 1000))
        qs = "&".join(f"{k}={v}" for k, v in params.items()) if params else ""
        enc_body = _encrypt_body(qs, self._enc_key)
        sign = _compute_sign(enc_body, nonce, self._sign_key)
        headers = self._kintaro_headers(nonce, sign)
        url = f"{EU_KINTARO_BASE}{endpoint}?params={urllib.parse.quote(enc_body, safe='')}"
        try:
            r = await self._http.get(url, headers=headers)
            rj = r.json()
            if rj.get("state") != "S":
                _LOGGER.debug("GET %s: error=%s", endpoint, rj.get("errorCode"))
                return None
            if rj.get("payload"):
                return _decrypt_response(rj["payload"], self._enc_key)
            return rj
        except Exception as err:
            _LOGGER.error("GET %s Fehler: %s", endpoint, err)
            return None

    async def _kintaro_post(self, endpoint: str, params: dict | None = None) -> dict | None:
        """POST mit JSON-Format."""
        if not await self._ensure_token():
            _LOGGER.error("POST %s abgebrochen — keine gueltige Session", endpoint)
            raise ConnectionError(f"Keine gueltige API-Session fuer {endpoint}")
        nonce = str(int(time.time() * 1000))
        body_str = json.dumps(params or {}, separators=(",", ":"))
        enc_body = _encrypt_body(body_str, self._enc_key)
        sign = _compute_sign(enc_body, nonce, self._sign_key)
        headers = self._kintaro_headers(nonce, sign)
        try:
            r = await self._http.post(f"{EU_KINTARO_BASE}{endpoint}", content=enc_body, headers=headers)
            rj = r.json()
            if rj.get("state") != "S":
                _LOGGER.debug("POST %s: error=%s", endpoint, rj.get("errorCode"))
                return None
            if rj.get("payload"):
                return _decrypt_response(rj["payload"], self._enc_key)
            return rj
        except Exception as err:
            _LOGGER.error("POST %s Fehler: %s", endpoint, err)
            return None

    # ------------------------------------------------------------------
    # Fahrzeugliste
    # ------------------------------------------------------------------

    async def async_get_vehicles(self) -> list[dict]:
        data = await self._kintaro_get(EP_VEHICLE_LIST)
        if not data:
            return []
        vehicles = data.get("vehicles", [])
        for entry in data.get("vinList", []):
            v, iv = entry.get("vin", ""), entry.get("internalVin", "")
            if v and iv:
                self._internal_vins[v] = iv
        for v in vehicles:
            if not v.get("nickName"):
                v["nickName"] = ""
        self._vehicles_cache = vehicles
        return vehicles

    # ------------------------------------------------------------------
    # Fahrzeugstatus (alle Endpoints zusammen)
    # ------------------------------------------------------------------

    async def async_get_vehicle_status(self, vin: str) -> VehicleState:
        state = VehicleState(vin=vin)
        internal_vin = self._internal_vins.get(vin, vin)
        state.internal_vin = internal_vin
        params = {"vin": vin, "internalVin": internal_vin}

        # PIN verifizieren damit Location und Remote-Commands funktionieren
        await self._ensure_pin(vin)

        for v in self._vehicles_cache:
            if v.get("vin") == vin:
                state.nickname = v.get("nickName", "")
                break

        # VSR — Kilometerstand, Reifendruck, Warnungen, Tueren
        vsr = await self._kintaro_get(EP_VSR, params)
        if vsr:
            state.raw_data["vsr"] = vsr
            state = self._parse_vsr(vsr, state)

        # Ladestatus
        charge = await self._kintaro_get(EP_CHARGE_DETAILS, params)
        if charge:
            state.raw_data["charge"] = charge
            state = self._parse_charge(charge, state)

        # Klimaanlage
        climate = await self._kintaro_get(EP_CLIMATE_DETAILS, params)
        if climate:
            state.raw_data["climate"] = climate
            state = self._parse_climate(climate, state)

        # Motor
        engine = await self._kintaro_get(EP_ENGINE_DETAILS, params)
        if engine:
            state.raw_data["engine"] = engine
            state.engine_on = engine.get("isEngineOn", False) is True

        # Ladekosten
        cost = await self._kintaro_get(EP_CHARGING_BASE_COST, params)
        if cost:
            state.raw_data["cost"] = cost
            try:
                state.charging_base_cost = float(cost.get("baseCost", 0))
            except (ValueError, TypeError):
                pass

        # Firmware
        fw = await self._kintaro_get(EP_FIRMWARE_STATUS, params)
        if fw:
            state.raw_data["firmware"] = fw
            installed = fw.get("installed", [])
            if installed:
                state.firmware_version = installed[0].get("version", "")

        # Location (POST — braucht pinHash im Body)
        if self._pin_hash:
            await self._ensure_pin(vin)
        loc = await self._kintaro_post(EP_VEHICLE_LOCATION, {
            "vin": vin, "internalVin": internal_vin,
            **({"pinHash": self._pin_hash} if self._pin_hash else {}),
        })
        if loc:
            state.raw_data["location"] = loc
            state = self._parse_location(loc, state)

        # Letzte Fahrt (getMileageHistory — braucht startDate/endDate)
        now = datetime.now()
        month_ago = now - timedelta(days=30)
        mileage = await self._kintaro_get(EP_MILEAGE_HISTORY, {
            **params,
            "startDate": month_ago.strftime("%Y-%m-%d"),
            "endDate": now.strftime("%Y-%m-%d"),
        })
        if mileage:
            state.raw_data["mileage_history"] = mileage
            trips = mileage.get("trips", [])
            if trips:
                # Sortiere nach Enddatum (neueste zuerst)
                trips_sorted = sorted(
                    trips,
                    key=lambda t: t.get("tripEndDate", ""),
                    reverse=True,
                )
                latest = trips_sorted[0]
                try:
                    state.last_trip_distance = round(float(latest.get("tripTotalDistance", 0)), 1)
                    state.last_trip_duration = int(latest.get("tripTotalDuration", 0))
                    state.last_trip_date = latest.get("tripEndDate", "")
                except (ValueError, TypeError):
                    pass

        # Ladehistorie (getChargingHistory — braucht start/end Params)
        charge_hist = await self._kintaro_get(EP_CHARGING_HISTORY, {
            **params,
            "start": month_ago.strftime("%Y-%m-%d"),
            "end": now.strftime("%Y-%m-%d"),
        })
        if charge_hist:
            state.raw_data["charging_history"] = charge_hist
            charges = charge_hist.get("charges", [])
            if charges:
                charges_sorted = sorted(
                    charges,
                    key=lambda c: c.get("chargeEndDate", ""),
                    reverse=True,
                )
                latest_charge = charges_sorted[0]
                try:
                    state.last_charge_energy = round(float(latest_charge.get("chargeEnergyRecovered", 0)), 2)
                    state.last_charge_duration = round(float(latest_charge.get("chargeDuration", 0)), 0)
                    state.last_charge_date = latest_charge.get("chargeEndDate", "")
                except (ValueError, TypeError):
                    pass

        # Geofence-Einstellungen
        geo = await self._kintaro_get(EP_GEOFENCE_ALERT, params)
        if geo:
            state.raw_data["geofence"] = geo
            geo_data = geo.get("data", geo)
            try:
                state.geofence_min_radius = int(geo_data.get("minRad", 0))
                state.geofence_max_radius = int(geo_data.get("maxRad", 0))
            except (ValueError, TypeError):
                pass

        # Speed Alert
        spd_alert = await self._kintaro_get(EP_SPEED_ALERT, params)
        if spd_alert:
            state.raw_data["speed_alert"] = spd_alert
            state.speed_alert_unit = spd_alert.get("speedUnit", "")

        return state

    # ------------------------------------------------------------------
    # Parser
    # ------------------------------------------------------------------

    def _parse_vsr(self, data: dict, state: VehicleState) -> VehicleState:
        diag = data.get("data", {}).get("diagnostic", {})
        if not diag:
            return state

        # Kilometerstand
        odo = diag.get("odo", {})
        if odo:
            try:
                state.odometer = float(odo.get("value", 0))
            except (ValueError, TypeError):
                pass

        # Geschwindigkeit
        spd = diag.get("spd", {})
        if spd:
            try:
                state.speed = float(spd.get("value", 0))
            except (ValueError, TypeError):
                pass

        # EV-Reichweite (cruisingRangeSecond = electric)
        # Nur ersten gültigen Wert nehmen — Loop kann mehrere Felder pro Entry treffen
        cr_second = diag.get("cruisingRangeSecond", {})
        for entry in cr_second.get("cruisingRange", []):
            found = False
            for key, val in entry.items():
                if "range" in key.lower() and isinstance(val, dict):
                    try:
                        candidate = float(val.get("value", 0))
                        if candidate > 0:
                            state.ev_range = candidate
                            found = True
                            break
                    except (ValueError, TypeError):
                        pass
            if found:
                break

        # Benzin-Reichweite (cruisingRangeFirst = gasoline)
        # Nur ersten gültigen Wert nehmen; Werte > 1200 km sind Sentinel-Werte der API
        cr_first = diag.get("cruisingRangeFirst", {})
        for entry in cr_first.get("cruisingRange", []):
            found = False
            for key, val in entry.items():
                if "range" in key.lower() and isinstance(val, dict):
                    try:
                        candidate = float(val.get("value", 0))
                        if 0 < candidate <= 1200:
                            state.fuel_range = candidate
                            found = True
                            break
                        elif candidate > 1200:
                            _LOGGER.debug(
                                "cruisingRangeFirst-Wert %s km verworfen (Sentinel/ungültig).",
                                candidate,
                            )
                    except (ValueError, TypeError):
                        pass
            if found:
                break

        # Gesamtreichweite
        avail = diag.get("availRange", {})
        if avail:
            try:
                state.total_range = float(avail.get("value", 0))
            except (ValueError, TypeError):
                pass

        # Fallback: Benzinreichweite aus Gesamtreichweite - EV-Reichweite ableiten
        if state.fuel_range is None and state.total_range is not None:
            ev = state.ev_range or 0.0
            state.fuel_range = round(max(0.0, state.total_range - ev), 1)
            _LOGGER.debug(
                "Benzinreichweite aus total (%s) - ev (%s) = %s km abgeleitet.",
                state.total_range, ev, state.fuel_range,
            )

        # Reifendruck: API liefert kPa → Umrechnung in Bar (÷100, 2 Nachkommastellen)
        tire_status = diag.get("tireStatus", {})
        _LOGGER.debug("VSR tireStatus raw: %s", tire_status)
        for tire in tire_status.get("tires", []):
            pos = tire.get("position", {}).get("value", "")
            pval = tire.get("pressureValue", {}).get("value", "")
            try:
                pressure_bar = round(float(pval) / 100, 2)
                pos_int = int(pos)
                if pos_int == 0:
                    state.tire_fl_pressure = pressure_bar
                elif pos_int == 1:
                    state.tire_fr_pressure = pressure_bar
                elif pos_int == 2:
                    state.tire_rl_pressure = pressure_bar
                elif pos_int == 3:
                    state.tire_rr_pressure = pressure_bar
            except (ValueError, TypeError):
                pass

        # 12V Batterie
        batt_12v = diag.get("batteryLife", {})
        if batt_12v:
            try:
                state.battery_12v = int(batt_12v.get("value", 0))
            except (ValueError, TypeError):
                pass

        # Tuerstatus — verschiedene Formate abfangen: "1"/"0", "true"/"false", True/False
        _LOGGER.debug("VSR doorLockSts raw: %s", diag.get("doorLockSts"))
        door_lock = diag.get("doorLockSts", {})
        if door_lock is not None:
            raw_val = door_lock.get("value", None) if isinstance(door_lock, dict) else door_lock
            if raw_val is not None:
                if isinstance(raw_val, bool):
                    state.doors_locked = raw_val
                else:
                    raw_str = str(raw_val).lower().strip()
                    if raw_str in ("1", "true", "locked", "yes"):
                        state.doors_locked = True
                    elif raw_str in ("0", "false", "unlocked", "no"):
                        state.doors_locked = False
                    # sonst bleibt None → "Unbekannt"

        # Einzelne Türen (vehicleStatus)
        vs = data.get("data", {}).get("vehicleStatus", {})
        _DOOR_MAP = {0: "door_fl_open", 2: "door_fr_open", 3: "door_rl_open",
                     4: "door_rr_open", 1: "door_hood_open", 5: "door_trunk_open"}
        for door in vs.get("doorStatus", {}).get("doors", []):
            try:
                pos = int(door.get("position", {}).get("value", -1))
                is_open = door.get("state", {}).get("value", "0") != "0"
                if pos in _DOOR_MAP:
                    setattr(state, _DOOR_MAP[pos], is_open)
            except (ValueError, TypeError):
                pass

        # Schloss aus vehicleStatus (Fallback falls doorLockSts fehlt)
        lock_st = vs.get("lockStatus", {})
        if lock_st and state.doors_locked is None:
            lv = lock_st.get("value", "")
            if lv == "1":
                state.doors_locked = True
            elif lv == "0":
                state.doors_locked = False

        # Einzelne Fenster
        _WIN_MAP = {0: "window_fl_open", 2: "window_fr_open", 3: "window_rl_open",
                    4: "window_rr_open", 1: "window_sunroof_open"}
        for win in vs.get("windowStatus", {}).get("windows", []):
            try:
                pos = int(win.get("position", {}).get("value", -1))
                is_open = win.get("state", {}).get("value", "0") != "0"
                if pos in _WIN_MAP:
                    setattr(state, _WIN_MAP[pos], is_open)
            except (ValueError, TypeError):
                pass

        # Scheinwerfer
        for light in vs.get("lightStatus", {}).get("lights", []):
            lpos = light.get("position", {}).get("value", "")
            lval = light.get("state", {}).get("value", "3")
            if lpos == "0":
                state.headlights_on = lval not in ("3", "0")

        # Warnungen
        state.brake_warning = diag.get("breakWarn", {}).get("warning", "false") == "true"
        state.abs_warning = diag.get("absWarn", {}).get("warning", "false") == "true"
        state.airbag_warning = diag.get("airbagWarn", {}).get("warning", "false") == "true"
        state.engine_oil_warning = diag.get("engineOilWarn", {}).get("warning", "false") == "true"
        state.mil_warning = diag.get("milStatus", {}).get("warning", "false") == "true"

        # Timestamp
        ts = diag.get("digsts", "")
        if ts:
            state.last_updated = ts

        return state

    def _parse_charge(self, data: dict, state: VehicleState) -> VehicleState:
        try:
            batt = data.get("hvBatteryLife")
            if batt is not None:
                state.battery_level = int(batt)
        except (ValueError, TypeError):
            pass

        state.is_charging = data.get("isCharging", False) is True
        state.is_plugged_in = data.get("isPluggedIn", False) is True
        state.charging_ready = str(data.get("hvChargingReady", "0")) != "0"
        state.charge_disabled = data.get("isStartChargeDisable", False) is True

        try:
            ttf = data.get("hvTimeToFullCharge")
            if ttf is not None and int(ttf) > 0:
                state.charging_remaining_time = int(ttf)
        except (ValueError, TypeError):
            pass
        return state

    def _parse_climate(self, data: dict, state: VehicleState) -> VehicleState:
        state.ac_on = data.get("isACOn", False) is True
        try:
            temp = data.get("targetTemperature")
            if temp is not None:
                state.target_temperature = float(temp)
        except (ValueError, TypeError):
            pass
        return state

    def _parse_location(self, data: dict, state: VehicleState) -> VehicleState:
        # Format: {"locationLatitude": {"value": 48.4, "lastUpdateDateTime": "..."}, ...}
        lat_obj = data.get("locationLatitude", {})
        lon_obj = data.get("locationLongitude", {})
        lat = lat_obj.get("value") if isinstance(lat_obj, dict) else data.get("latitude") or data.get("lat")
        lon = lon_obj.get("value") if isinstance(lon_obj, dict) else data.get("longitude") or data.get("lon")
        ts = lat_obj.get("lastUpdateDateTime", "") if isinstance(lat_obj, dict) else str(data.get("timestamp", ""))
        try:
            if lat is not None and lon is not None:
                state.location = VehicleLocation(
                    latitude=float(lat),
                    longitude=float(lon),
                    last_updated=ts,
                )
        except (ValueError, TypeError):
            pass
        return state

    # ------------------------------------------------------------------
    # Remote Commands (alle brauchen PIN)
    # ------------------------------------------------------------------

    async def _remote_command(self, vin: str, endpoint: str) -> bool:
        """Generischer Remote-Command mit PIN-Hash im Body."""
        if not await self._ensure_pin(vin):
            return False
        internal_vin = self._internal_vins.get(vin, vin)
        result = await self._kintaro_post(endpoint, {
            "vin": vin, "internalVin": internal_vin, "pinHash": self._pin_hash,
        })
        return result is not None

    async def async_start_climate(self, vin: str, temperature: float | None = None) -> bool:
        """Klimaanlage starten, optional mit Zieltemperatur."""
        if not await self._ensure_pin(vin):
            return False
        internal_vin = self._internal_vins.get(vin, vin)
        body: dict = {"vin": vin, "internalVin": internal_vin, "pinHash": self._pin_hash}
        if temperature is not None:
            body["targetTemperature"] = temperature
        result = await self._kintaro_post(EP_START_CLIMATE, body)
        return result is not None

    async def async_stop_climate(self, vin: str) -> bool:
        return await self._remote_command(vin, EP_STOP_CLIMATE)

    async def async_start_charging(self, vin: str) -> bool:
        return await self._remote_command(vin, EP_START_CHARGE)

    async def async_stop_charging(self, vin: str) -> bool:
        return await self._remote_command(vin, EP_STOP_CHARGE)

    async def async_lock_doors(self, vin: str) -> bool:
        return await self._remote_command(vin, EP_LOCK_DOOR)

    async def async_unlock_doors(self, vin: str) -> bool:
        return await self._remote_command(vin, EP_UNLOCK_DOOR)

    async def async_horn(self, vin: str) -> bool:
        return await self._remote_command(vin, EP_START_HORN)

    async def async_lights(self, vin: str) -> bool:
        return await self._remote_command(vin, EP_START_LIGHT)

    async def async_start_engine(self, vin: str) -> bool:
        return await self._remote_command(vin, EP_START_ENGINE)

    async def async_stop_engine(self, vin: str) -> bool:
        return await self._remote_command(vin, EP_STOP_ENGINE)

    async def async_take_photo(self, vin: str) -> bool:
        return await self._remote_command(vin, EP_TAKE_PHOTO)

    async def async_get_photo_list(self, vin: str) -> list[dict]:
        """Foto-Historie abrufen."""
        internal_vin = self._internal_vins.get(vin, vin)
        data = await self._kintaro_get(EP_PHOTO_HISTORY_LIST, {
            "vin": vin, "internalVin": internal_vin,
        })
        if not data:
            return []
        # Versuche verschiedene Response-Strukturen
        photos = data.get("photoList", data.get("photos", data.get("historyList", [])))
        _LOGGER.debug("Photo list response: %s", data)
        return photos if isinstance(photos, list) else []

    async def async_get_photo_details(self, vin: str, photo_id: str) -> dict | None:
        """Foto-Details (URL/Daten) abrufen."""
        internal_vin = self._internal_vins.get(vin, vin)
        data = await self._kintaro_get(EP_PHOTO_HISTORY_DETAILS, {
            "vin": vin, "internalVin": internal_vin, "photoId": photo_id,
        })
        _LOGGER.debug("Photo details response: %s", data)
        return data

    async def async_get_latest_photo_url(self, vin: str) -> str | None:
        """Neuestes Foto-URL holen."""
        photos = await self.async_get_photo_list(vin)
        if not photos:
            return None
        # Neuestes Foto (erstes in der Liste oder nach Timestamp sortiert)
        latest = photos[0]
        photo_id = latest.get("photoId", latest.get("id", ""))
        if not photo_id:
            # Vielleicht ist die URL direkt in der Liste
            url = latest.get("photoUrl", latest.get("url", latest.get("imageUrl", "")))
            if url:
                return url
            return None
        details = await self.async_get_photo_details(vin, photo_id)
        if not details:
            return None
        return details.get("photoUrl", details.get("url", details.get("imageUrl", "")))

    async def async_refresh_status(self, vin: str) -> bool:
        """VSR-Refresh triggern."""
        await self._ensure_pin(vin)
        internal_vin = self._internal_vins.get(vin, vin)
        result = await self._kintaro_post(EP_REFRESH_VSR, {
            "vin": vin, "internalVin": internal_vin,
            **({"pinHash": self._pin_hash} if self._pin_hash else {}),
        })
        return result is not None

