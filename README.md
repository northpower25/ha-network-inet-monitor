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

## Konfiguration in Home Assistant

Nach dem Neustart:

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen**.
2. Nach **Network Quality Internet Monitor** suchen.
3. Setup-Dialog ausfüllen.

### Pflichtfelder

- Anzeigename der Instanz
- Internetanbieter (ISP)
- Router-Typ (`fritzbox`, `openwrt`, `unifi`, `other`)
- Vertragswerte für Download (min/normal/max)
- Vertragswerte für Upload (min/normal/max)

### Optionen im Setup/Options-Flow

- Region
- Test-Intervalle (Speedtest, Ping, Traceroute, Download-Test, Upload-Test, Status)
- Opt-in für externe Servicechecks
- Testziele (IP, Hostname oder URL; kommasepariert oder zeilenweise)
- `agent_url` für einen lokalen Mess-Agenten
- Auswahl der zu überwachenden Dienste (z. B. Amazon, Google, Netflix, OpenAI, GitHub, …)

### Wichtige Hinweise zur Konfiguration

- `download_min <= download_normal <= download_max` und analog für Upload, sonst wird die Eingabe abgelehnt.
- Wenn keine Testziele gesetzt sind, nutzt die Integration Standardziele.
- Änderungen in den Intervall-Optionen greifen dynamisch, da der Coordinator sein Aktualisierungsintervall bei jedem Refresh neu berechnet.

## Funktionsweise der Integration (detailliert)

### 1. Datenerfassung

Die Integration nutzt einen `DataUpdateCoordinator` als zentrale Sammelstelle.

Es gibt zwei Betriebsarten:

1. **Mit Agent (`agent_url` gesetzt)**
   - Abruf von `.../metrics`
   - Übernahme von Download, Upload, Ping, Jitter, Paketverlust, Verfügbarkeit, Online-Status
   - Übernahme von Testlauf-Metadaten (z. B. letzte Läufe, aktive Tests)

2. **Ohne Agent (`agent_url` leer)**
   - Download/Upload werden aus den konfigurierten Vertrags-Normalwerten initialisiert
   - Lokale Fallback-Messung per TCP-Connect-Probes auf konfigurierte Ziele (Port 443)
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
