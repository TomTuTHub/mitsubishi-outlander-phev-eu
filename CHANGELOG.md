# Changelog

## 1.1.0

First stable release of the 1.1 line (built from 1.1.0b11, which replaces the 1.0.x line).

- The integration no longer identifies itself to Mitsubishi as "homeassistant" (Mitsubishi started rejecting those logins on 17 Nov 2026); no X-Device header is sent.
- One version for Europe and Japan: choose the region in the config flow.
- Remote commands now work like the official app 3.2.0: the vehicle is woken first, every command gets a fresh PIN proof (server nonce + pinHash), and the request body matches the app (target temperature, unit, climate settings).
- Real result: the integration follows each command's requestId and reports success / no response / rejected in the `last_command` attribute. No automatic retries.
- New service `request_status`: one read-only status query for a requestId.
- Diagnostic switch "Motor remote" (startEngine) is disabled by default and meant for diagnosis only; on the PHEV it may start the petrol engine.
- Session-loss fix (from 1.1.0b8): re-login at most every 10 minutes (backoff), plus a connection sensor.
