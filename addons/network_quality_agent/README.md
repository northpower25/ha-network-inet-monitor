# Network Quality Agent Add-on

Dieses Add-on stellt lokal zwei Endpunkte bereit:

- `GET /health`
- `GET /metrics` (kompatibel zur `agent_url`-Erwartung der Integration)

## Standard-URL in der Integration

Wenn in der Integration `agent_mode=addon` gewählt ist und keine `agent_url` gesetzt wird,
verwendet die Integration automatisch:

`http://127.0.0.1:8099/metrics`

## Token-Schutz

Wenn im Add-on ein `token` gesetzt ist, muss die Integration dasselbe `agent_token` setzen.
Die Integration sendet dafür einen Authorization-Header mit Bearer-Token.

## Add-on Optionen (was einstellen?)

### `bind_host`
- Standard: `0.0.0.0`
- Funktion: Netzwerk-Interface, auf dem der Agent lauscht.
- Empfehlung: Bei Standard-HA-Setup auf `0.0.0.0` belassen.

### `bind_port`
- Standard: `8099`
- Funktion: HTTP-Port für `/health` und `/metrics`.
- Empfehlung: Nur ändern, wenn Port bereits belegt ist (dann auch `agent_url` in der Integration anpassen).

### `interval_seconds`
- Standard: `60`
- Funktion: Intervall, in dem neue Messwerte erzeugt werden.
- Empfehlung: 30–120 Sekunden für den Normalbetrieb.

### `connect_timeout_seconds`
- Standard: `3`
- Funktion: Timeout pro Verbindungsprobe zu einem Ziel.
- Empfehlung: 2–5 Sekunden (zu klein = unnötige Fehlmessungen, zu groß = träge Updates).

### `probe_attempts`
- Standard: `3`
- Funktion: Anzahl der Probes pro Messzyklus.
- Empfehlung: 3 als guter Kompromiss zwischen Stabilität und Last.

### `targets`
- Standard: `1.1.1.1`, `8.8.8.8`, `9.9.9.9`
- Funktion: Ziele für Reachability-, Ping-, Jitter-, Paketverlust- und Verfügbarkeitsberechnung.
- Empfehlung: Mehrere stabile Ziele verwenden (DNS + bekannte öffentliche Endpunkte).

### `token` (optional)
- Standard: leer
- Funktion: Schützt `/metrics` per Bearer-Token.
- Wichtig: Bei gesetztem Token muss in der Integration `agent_token` identisch gesetzt sein.

## Zusammenspiel mit der Integration

Empfohlene Integrationseinstellungen bei Add-on-Nutzung:

- `agent_mode = addon`
- `agent_url` leer lassen (nutzt automatisch `http://127.0.0.1:8099`)
- `agent_token` nur dann setzen, wenn im Add-on `token` gesetzt wurde
