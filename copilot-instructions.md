# Copilot Instructions – Entwicklungsregeln für `ha-network-inet-monitor`

Diese Datei ist vor **jeder** Änderung zu lesen und als verbindliche Arbeitsgrundlage zu verwenden.

## 1) Grundprinzipien

- HACS-konforme Home-Assistant-Custom-Integration bauen.
- Kleine, nachvollziehbare, testbare Änderungen bevorzugen.
- Keine unnötigen Abhängigkeiten einführen.
- Datenschutz-by-default: lokale Verarbeitung, externe Übertragung nur mit Opt-in.

## 2) Funktionsziele der Integration

- Netzwerk-/Internetqualität BNetzA-orientiert messen.
- ISP-Störungen und globale Dienststatus integrieren.
- Config Flow mit Pflichtfeldern:
  - Internetanbieter
  - gebuchter Tarif (mind./normal/max)
  - Routertyp (z. B. FRITZ!Box)
- Eigenes Dashboard mit grafischer + tabellarischer QoS-Auswertung bereitstellen.
- PDF-Export für Nachweis-/Supportberichte ermöglichen.

## 3) Architektur- und Code-Regeln

- `DataUpdateCoordinator` für zentrale Datenerhebung/Koordination verwenden.
- Plattformen klar trennen (`sensor`, `binary_sensor`, `diagnostics`, ggf. `button`/`event`).
- Router-spezifische Logik über Adapter/Strategie kapseln (kein Wildwuchs in Entitäten).
- Externe Datenquellen robust anbinden (Timeout, Retry, Fehlerzustände).
- Entitätsnamen stabil, übersetzbar und verständlich halten.

## 4) Config Flow und Optionen

- Einrichtung vollständig per UI (`config_flow.py`).
- Pflichtfelder validieren und verständlich fehlern.
- Erweiterte Optionen in Options Flow auslagern (Intervalle, Quellen, Schwellen).
- Keine geheimen Daten in Klartext in Logs oder Diagnosen ausgeben.

## 5) Dashboard und Reporting

- Dashboard beim Setup direkt verfügbar machen.
- Ansicht muss enthalten:
  - KPI-Karten
  - Verlaufsgrafiken
  - tabellarische Mess-/Störungshistorie
  - SLA-/Qualitätsindikatoren
- PDF-Report reproduzierbar aus gespeicherten Aggregatdaten erzeugen.

## 6) Qualität, Tests, Betrieb

- Vor jedem Commit mindestens relevante bestehende Checks ausführen.
- Fehlerfälle (Offline, Timeout, Router nicht erreichbar, API-Fehler) gezielt behandeln.
- Rate-Limits und Ressourcenverbrauch beachten (keine aggressiven Polling-Defaults).
- Breaking Changes vermeiden; falls nötig, Migration dokumentieren.

## 7) Sicherheits- und Datenschutzregeln

- Keine Messdaten an Dritte ohne explizites Opt-in.
- Minimale Datenerhebung, zweckgebundene Speicherung.
- Diagnostik anonymisieren/pseudonymisieren, wenn möglich.
- Keine Secrets in Repository, Logs, Diagnostics oder Events.

## 8) Dokumentationsregeln

- README und Nutzerdokumentation bei relevanten Änderungen aktualisieren.
- Neue Sensoren/Binary Sensoren/Services dokumentieren.
- Entscheidungsänderungen (z. B. Messmethode, Scoring) nachvollziehbar festhalten.

## 9) Do/Don’t Kurzliste

**Do**
- Modular entwickeln
- Fehlertolerant integrieren
- Nutzerkonfiguration respektieren
- Mess- und Bewertungslogik transparent halten

**Don’t**
- Harte Provider-/Router-Annahmen im Kerncode verankern
- Ungeprüfte Scraping-Logik als Primärquelle verwenden
- PDF-/Dashboard-Features als optionalen Nachgedanken behandeln
- Nicht dokumentierte Magic Numbers für QoS-Score verwenden
