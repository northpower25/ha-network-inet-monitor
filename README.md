# ha-network-inet-monitor
HomeAssistant Network and Internet Monitor Integration

## Status

Diese Repository-Version enthält ein MVP der HACS-fähigen Home-Assistant-Custom-Integration unter:

`custom_components/network_quality/`

## Enthaltene MVP-Funktionen

- UI-basierter Config Flow mit Pflichtfeldern:
  - Internetanbieter (ISP)
  - Routertyp
  - Vertragswerte für Download/Upload (min/normal/max)
- Options Flow für:
  - Region
  - Messintervalle (Speedtest/Ping/Status)
  - Opt-in für externe Checks
  - Testziele (zeilenweise konfigurierbar)
  - auswählbare Dienststatus-Kategorien
  - optionaler lokaler Agent-Endpunkt (`/metrics`)
- `DataUpdateCoordinator`-basierte Datenaufbereitung mit:
  - Download/Upload
  - Ping/Jitter/Paketverlust
  - Verfügbarkeit
  - Vertragsquote
  - Quality Score (0–100) + Qualitätsklasse A–E
- Sensoren und Binary Sensoren für Kernmetriken und Dienststatus
- Diagnostik mit Redaction sensibler Felder
- Services:
  - `network_quality.export_report`
  - `network_quality.install_dashboard`
- Dashboard-Template unter:
  - `custom_components/network_quality/dashboard/network_quality_dashboard.json`

## Struktur

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
  └── translations/
      ├── de.json
      └── en.json
```

## Hinweis zum Mess-Backend

Das MVP unterstützt optional einen lokalen Agent-Endpunkt via `agent_url`.
Wenn kein Agent konfiguriert ist, werden sichere lokale Defaultwerte zur Funktionsprüfung genutzt.
