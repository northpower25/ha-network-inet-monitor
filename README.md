# ha-network-inet-monitor

Home Assistant Custom Integration zur Überwachung der Internet- und Verbindungsqualität.

## Installation über HACS

### Voraussetzungen

- Laufende Home-Assistant-Installation
- [HACS](https://hacs.xyz/) ist bereits installiert

### Installation (Custom Repository)

1. HACS in Home Assistant öffnen.
2. **Integrations** auswählen.
3. Oben rechts auf die drei Punkte klicken → **Custom repositories**.
4. Repository-URL eintragen:
   - `https://github.com/northpower25/ha-network-inet-monitor`
5. Kategorie **Integration** wählen und speichern.
6. In HACS nach **Network Quality Internet Monitor** suchen.
7. Integration installieren.
8. Home Assistant neu starten.

## Installation des Home-Assistant-Add-ons

Dieses Repository enthält zusätzlich das Add-on **Network Quality Agent**.

### Add-on-Repository in Home Assistant hinzufügen

1. **Einstellungen → Add-ons → Add-on Store** öffnen.
2. Oben rechts auf die drei Punkte klicken → **Repositories**.
3. Als Repository-URL eintragen:
   - `https://github.com/northpower25/ha-network-inet-monitor`
4. Speichern.
5. Danach erscheint das Add-on **Network Quality Agent** im Add-on Store und kann installiert werden.

> Wichtig: Nicht die GitHub-Web-URL mit `/tree/main/...` verwenden. Home Assistant erwartet die URL des Git-Repositories.

### Empfohlene Kombination mit der Integration

1. Add-on **Network Quality Agent** installieren und starten.
2. Danach die Integration **Network Quality Internet Monitor** über HACS installieren.
3. In der Integration `agent_mode = addon` wählen.
4. `agent_url` leer lassen, damit automatisch `http://127.0.0.1:8099` verwendet wird.
5. `agent_token` nur setzen, wenn im Add-on ebenfalls ein Token konfiguriert wurde.

## Konfiguration in Home Assistant

Nach dem Neustart:

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen**.
2. Nach **Network Quality Internet Monitor** suchen.
3. Setup-Dialog ausfüllen.

### Pflichtfelder

- Anzeigename der Instanz
- Internetanbieter (ISP)
- Router-Typ (`fritzbox`, `OpenWRT`, `unifi`, `other`)
- Vertragswerte für Download (min/normal/max)
- Vertragswerte für Upload (min/normal/max)

### Optionen im Setup/Options-Flow

- Region
- Test-Intervalle (Speedtest, Ping, Traceroute, Download-Test, Upload-Test, Status)
- Opt-in für externe Servicechecks
- Testziele (IP, Hostname oder URL; kommasepariert oder zeilenweise)
- Messmodus `agent_mode` (`fallback`, `local_runner`, `addon`, `external_agent`)
- `agent_url` für lokalen/externalen Mess-Agenten (bei `addon` optional; Default `http://127.0.0.1:8099`)
- optionales `agent_token` (Bearer-Token für `/metrics`)
- Auswahl der zu überwachenden Dienste (z. B. Amazon, Google, Netflix, OpenAI, GitHub, …)

### Neue Funktionen: Was ist einzustellen?

#### 1) Messmodus (`agent_mode`)

- `fallback`  
  Nutzen, wenn kein Agent/Add-on eingesetzt wird. Die Integration macht leichte lokale Erreichbarkeits-Checks und nutzt Vertrags-Normalwerte für Download/Upload.
- `local_runner`  
  Nutzen für lokale Light-Probes ohne externen Endpoint. Verhalten ähnlich zu `fallback`, aber explizit als lokaler Runner-Modus.
- `addon`  
  Empfohlen bei Nutzung des mitgelieferten Home-Assistant-Add-ons. Wenn `agent_url` leer bleibt, wird automatisch `http://127.0.0.1:8099` verwendet.
- `external_agent`  
  Für externe Agenten/Hosts. Hier muss `agent_url` gesetzt sein.

#### 2) Agent-Endpoint (`agent_url`)

- Bei `addon`: optional (Default greift automatisch)
- Bei `external_agent`: Pflichtfeld
- Bei `fallback`/`local_runner`: wird nicht benötigt

Beispiel:
- Lokal im HA-Host/Add-on: `http://127.0.0.1:8099`
- Extern im LAN: `http://192.168.1.50:8099`

#### 3) Agent-Token (`agent_token`)

- Wenn im Add-on/Agent ein Token konfiguriert ist, muss derselbe Wert hier eingetragen werden.
- Die Integration sendet das Token als Authorization-Header (Bearer-Token) an `/metrics`.
- Wenn kein Token im Agent gesetzt ist, bleibt das Feld leer.

#### 4) Testziele (`test_targets`)

- Unterstützt IP, Hostname oder URL
- Eingabe kommasepariert oder zeilenweise
- Empfehlung: 3–5 stabile, gut erreichbare Ziele (z. B. DNS-Resolver + bekannte Webseiten)

#### 5) Diagnose (`debug_status` Sensor)

- `ok`: Konfiguration und Datenaktualisierung sind plausibel
- `warning`: z. B. Fallback-Modus aktiv, Endpoint fehlt oder Daten sind veraltet
- `error`: letzte Aktualisierung fehlgeschlagen

Der Sensor liefert zusätzlich Diagnoseattribute wie:
- aktive Agent-Konfiguration
- letzte Fehler inkl. Typ/Zeitpunkt
- erkannte Testläufe und konfiguriertes Intervall

### Add-on: empfohlene Grundkonfiguration

Wenn das Add-on **Network Quality Agent** genutzt wird, sind folgende Einstellungen sinnvoll:

- `agent_mode = addon`
- `agent_url` leer lassen (Default wird automatisch genutzt)
- `agent_token` nur setzen, wenn im Add-on ebenfalls ein Token gesetzt wurde

Add-on-Optionen (im Add-on selbst):
- `bind_host`: meist `0.0.0.0`
- `bind_port`: Standard `8099`
- `interval_seconds`: Update-Intervall des Agenten (typisch 30–120)
- `connect_timeout_seconds`: Timeout pro Probe (typisch 2–5)
- `probe_attempts`: Anzahl Probes pro Zyklus (typisch 3)
- `targets`: Ziele für Reachability/Ping/Jitter/Verfügbarkeit

### Wichtige Hinweise zur Konfiguration

- `download_min <= download_normal <= download_max` und analog für Upload, sonst wird die Eingabe abgelehnt.
- Wenn keine Testziele gesetzt sind, nutzt die Integration Standardziele.
- Änderungen in den Intervall-Optionen greifen dynamisch, da der Coordinator sein Aktualisierungsintervall bei jedem Refresh neu berechnet.

## Funktionsweise der Integration (detailliert)

### 1. Datenerfassung

Die Integration nutzt einen `DataUpdateCoordinator` als zentrale Sammelstelle.

Es gibt vier Betriebsarten:

1. **`external_agent`**
   - Abruf von `.../metrics`
   - Übernahme von Download, Upload, Ping, Jitter, Paketverlust, Verfügbarkeit, Online-Status
   - Optional methodenspezifische Übernahme für Ookla/Fast.com/iPerf3/HTTP-Download aus `methods` oder kompatiblen Feldern im Agent-Payload
   - Übernahme von Testlauf-Metadaten (z. B. letzte Läufe, aktive Tests)

2. **`addon` (empfohlen)**
   - Nutzt denselben `/metrics`-Vertrag wie `external_agent`
   - Falls keine URL gesetzt ist, wird standardmäßig `http://127.0.0.1:8099/metrics` verwendet

3. **`local_runner`**
   - Leichte lokale Probe-Messungen (TCP-Connect) mit festen Laufzeit-/Parallelitätslimits
   - Download/Upload bleiben auf Vertrags-Normalwerten

4. **`fallback`**
   - Download/Upload werden aus den konfigurierten Vertrags-Normalwerten initialisiert
   - Lokale Fallback-Messung per TCP-Connect-Probes auf konfigurierte Ziele (Port 443, lightweight)
   - Daraus werden Ping/Jitter/Paketverlust/Verfügbarkeit und Online-Status bestimmt

### 2. Bewertung und Kennzahlen

Aus jedem Sample werden Kennzahlen berechnet:

- **Contract Ratio (%)** aus dem Verhältnis gemessener zu erwarteter Download-/Upload-Leistung
- **Quality Score (0–100)** aus gewichteten Faktoren:
  - Vertragserfüllung
  - Latenz
  - Jitter
  - Paketverlust
  - Verfügbarkeit
- **Qualitätsklasse A–E** auf Basis des Scores

Zusätzlich werden Rolling-Aggregate (Durchschnitt, Min, Max) über den internen Sample-Verlauf bereitgestellt.

### 3. Historie und Analyse

- Persistente Historie wird in Home-Assistant-Storage abgelegt.
- Samples werden mit Downsampling-Logik gespeichert (zeitbasiert oder bei relevanten Zustandsänderungen).
- Die Analytics-Komponente erzeugt Aggregationen für Stunde/Tag/Woche/Monat/Quartal.
- Es werden u. a. Ausfälle, starke Qualitätseinbrüche und Muster für das Dashboard aufbereitet.

### 4. Entitäten

#### Sensoren

- `internet_download`
- `internet_upload`
- `download_speed_ookla`
- `upload_speed_ookla`
- `download_speed_fast`
- `bandwidth_iperf_download`
- `bandwidth_iperf_upload`
- `download_http_test`
- `ping_public`
- `packet_loss`
- `jitter`
- `availability`
- `contract_ratio`
- `quality_score`
- `quality_class`
- `debug_status`

#### Binary Sensoren

- `internet_online`
- Dienststatus-Sensoren je aktivierter Dienst (`service_<name>`)

### 5. Dashboard und Frontend

Die Integration registriert automatisch:

- ein Sidebar-Panel **Network Quality** unter `/network-quality-overview`
- statische Frontend-Ressourcen unter `/{domain}_local/`
- einen WebSocket-Command `network_quality/dashboard_data` für aggregierte Dashboard-Daten

Zusätzlich kann ein Lovelace-Dashboard-Template aus `custom_components/network_quality/dashboard/network_quality_dashboard.json` installiert werden.

### 6. Services

- `network_quality.export_report`
  - Exportiert einen Qualitätsbericht (Datei oder Event)
  - Optional mit Rohdaten
- `network_quality.install_dashboard`
  - Installiert Dashboard-Views in das Standard-Lovelace-Dashboard

### 7. Diagnose

Der Sensor `debug_status` liefert Diagnosezustand (`ok`, `warning`, `error`) und detaillierte Attribute, z. B.:

- Agent-Konfiguration
- letzte erfolgreiche/fehlerhafte Aktualisierung
- konfigurierte Testintervalle
- Checkliste für letzte Testläufe

## Projektstruktur

```text
custom_components/network_quality/
  ├── __init__.py
  ├── manifest.json
  ├── config_flow.py
  ├── const.py
  ├── coordinator.py
  ├── sensor.py
  ├── binary_sensor.py
  ├── diagnostics.py
  ├── services.yaml
  ├── strings.json
  ├── dashboard/network_quality_dashboard.json
  ├── www/network-quality-panel.js
  └── translations/
      ├── de.json
      └── en.json
```
