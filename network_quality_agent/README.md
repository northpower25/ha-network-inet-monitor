# Network Quality Agent Add-on

## Installation in Home Assistant

1. **Einstellungen → Add-ons → Add-on Store** öffnen.
2. Oben rechts auf die drei Punkte klicken → **Repositories**.
3. Diese Repository-URL eintragen:
   - `https://github.com/northpower25/ha-network-inet-monitor`
4. Speichern und das Add-on **Network Quality Agent** installieren.

> Wichtig: Nur die reine Repository-URL `https://github.com/northpower25/ha-network-inet-monitor` verwenden und keine zusätzlichen Pfad-Suffixe wie `/tree/main/...` anhängen, da Home Assistant eine Git-Repository-URL erwartet.

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

### `speedtest_interval_seconds`
- Standard: `900`
- Funktion: Intervall, nach dem ein kompletter Speedtest-Zyklus (HTTP-Download + iperf3 + Ookla) gestartet wird.
- Empfehlung: 900–3600 Sekunden; `0` deaktiviert alle Speedtests.

### `speedtest_timeout_seconds`
- Standard: `120`
- Funktion: Maximale Laufzeit des Ookla-Speedtests.
- Empfehlung: Nur erhöhen, wenn sehr langsame Leitungen oder Timeouts auftreten.

### `speedtest_ookla_enabled`
- Standard: `true`
- Funktion: Aktiviert oder deaktiviert den Ookla-Speedtest (provider: ookla_auto – automatische Serverwahl).
- Empfehlung: Auf `false` setzen, wenn nur HTTP- und iperf3-Messungen gewünscht sind.

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
- Funktion: Ziele für Reachability-, Ping-, Jitter-, Paketverlust- und Verfügbarkeitsberechnung (TCP-Connect auf Port 443).
- Empfehlung: Mehrere stabile Ziele verwenden (DNS + bekannte öffentliche Endpunkte).

### `token` (optional)
- Standard: leer
- Funktion: Schützt `/metrics` per Bearer-Token.
- Wichtig: Bei gesetztem Token muss in der Integration `agent_token` identisch gesetzt sein.

---

## Speedtest-Methoden

Pro Speedtest-Zyklus werden drei Messmethoden in Reihe ausgeführt. Die jeweils höchsten Werte aller Methoden fließen als `download_mbps` und `upload_mbps` in die Top-Level-Metriken ein. Alle Einzelergebnisse sind im `methods`-Objekt der `/metrics`-Antwort verfügbar.

### HTTP-Download (BNetzA-analog)

Mehrere Server werden **parallel** mit je mehreren TCP-Verbindungen für eine festgelegte Dauer heruntergeladen. Das **Medianwert** aller erfolgreichen Servergeschwindigkeiten wird als Methodenergebnis verwendet. Dieses Verfahren ist an die Messtechnik der Bundesnetzagentur (BNetzA Breitbandatlas) angelehnt und reduziert den Einfluss einzelner überlasteter Server.

#### `http_download_targets`
- Standard: `speedtest.wtnet.de`, `speedtest.studiofunk.de`, `fra.speedtest.clouvider.net`
- Funktion: Serverliste für den HTTP-Download-Test.
- Empfehlung: Mehrere geografisch verteilte, bekannte Speedtest-Server verwenden.

#### `http_download_path`
- Standard: `/10G.bin`
- Funktion: Pfad zur Test-Datei auf den Servern (wird nach `http_download_duration_seconds` abgebrochen).
- Empfehlung: `/10G.bin` ist für Clouvider-Server und viele andere kompatibel. Bei LibreSpeed-Servern ggf. `/garbage.php?ckSize=100` verwenden.

#### `http_download_duration_seconds`
- Standard: `10`
- Funktion: Dauer des Downloads pro Server in Sekunden.
- Empfehlung: 10–30 Sekunden für stabile Ergebnisse; bei sehr schnellen Leitungen (>500 Mbit/s) mindestens 15 s.

#### `http_download_streams`
- Standard: `4`
- Funktion: Anzahl paralleler HTTP-Verbindungen pro Server (simuliert Mehrstrom-Download wie BNetzA).
- Empfehlung: 4 Streams wie BNetzA; bei > 1 Gbit/s ggf. auf 8 erhöhen.

### iperf3-Tests

iperf3-Tests werden **sequenziell** (ein Server nach dem anderen) im Reverse-Modus (`-R`) ausgeführt, damit sich die Leitungsauslastungen nicht gegenseitig beeinflussen. Das Medianwert aller erfolgreichen Servergeschwindigkeiten wird als Methodenergebnis verwendet. Erfordert das im Add-on enthaltene `iperf3`-Paket.

#### `iperf3_targets`
- Standard: `fra.speedtest.clouvider.net`, `speedtest.wtnet.de`, `speedtest.studiofunk.de`
- Funktion: Hauptserverliste für iperf3-Tests (primär DE-Standorte).

#### `iperf3_eu_targets`
- Standard: `ams.speedtest.clouvider.net`, `lon.speedtest.clouvider.net`
- Funktion: Zusätzliche EU-Diversitätsserver (AMS + LON) – erhöhen die geografische Streuung der Messung.

#### `iperf3_port`
- Standard: `5201`
- Funktion: TCP-Port für iperf3-Tests.
- Empfehlung: Standard-Port 5201 beibehalten, sofern Server nichts anderes erfordern.

#### `iperf3_duration_seconds`
- Standard: `10`
- Funktion: Dauer eines einzelnen iperf3-Tests pro Server.
- Empfehlung: 10–20 Sekunden.

#### `iperf3_streams`
- Standard: `4`
- Funktion: Anzahl paralleler iperf3-Streams pro Test (`-P`-Parameter).
- Empfehlung: 4 Streams wie BNetzA; bei langsamer Leitung (<50 Mbit/s) auf 1–2 reduzieren.

### Ookla-Speedtest (provider: ookla_auto)

Der Ookla-Speedtest wählt automatisch den besten verfügbaren Server aus (`get_best_server()`) und misst Download, Upload und Ping. Er liefert als einzige Methode auch Upload-Messwerte.

### `token` (optional)
- Standard: leer
- Funktion: Schützt `/metrics` per Bearer-Token.
- Wichtig: Bei gesetztem Token muss in der Integration `agent_token` identisch gesetzt sein.

---

## Zusammenspiel mit der Integration

Empfohlene Integrationseinstellungen bei Add-on-Nutzung:

- `agent_mode = addon`
- `agent_url` leer lassen (nutzt automatisch `http://127.0.0.1:8099`)
- `agent_token` nur dann setzen, wenn im Add-on `token` gesetzt wurde
- `speedtest_interval_seconds` im Add-on passend zu den gewünschten Download-/Upload-Intervallen setzen
