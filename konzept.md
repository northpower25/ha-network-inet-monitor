# Konzept: Home Assistant Integration „ha-network-inet-monitor“ (HACS-konform)

## 1) Zielbild

Die Integration überwacht die Qualität der Heimnetz-/Internetverbindung objektiv, BNetzA-orientiert und automatisierbar in Home Assistant.  
Sie kombiniert:

- lokale Messdaten (Bandbreite, Latenz, Stabilität, Verfügbarkeit),
- Router- und WAN-Statusdaten,
- externe Störungs-/Statussignale (ISP, DNS/CDN/Cloud),
- sowie ein integriertes Dashboard inklusive PDF-Bericht.

Ergebnis: Frühzeitige Erkennung von Problemen, belastbare Langzeitdaten, nutzbare Nachweise für Provider-Reklamationen.

---

## 2) HACS- und Integrationsrahmen

- Bereitstellung als Custom Integration unter `custom_components/network_quality/`
- Vollständiger `config_flow` (UI-Einrichtung statt YAML-only)
- Entitäten über `DataUpdateCoordinator`
- Sensoren, Binary Sensoren, ggf. Events/Diagnostik
- Übersetzungen (`translations/*.json`)
- Marken-/Icon-Ressourcen (`brands/`)
- Dokumentation für HACS (README, Beispiele, Optionen)

Geplante Kernstruktur:

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
  └── translations/
```

---

## 3) Funktionsumfang (fachlich)

## 3.1 Kernmetriken (BNetzA-orientiert)

### Bandbreite
- Download/Upload (Mbit/s)
- Vertragsquote in % (Messwert vs. Tarifparameter)
- Zeitreihen + Aggregationen (Ø, Min/Max, 95. Perzentil)

Beispiel-Entitäten:
- `sensor.internet_download`
- `sensor.internet_upload`
- `sensor.bandbreite_vertragsquote`

### Latenz/Stabilität
- Ping-Latenz (ms), Paketverlust (%), Jitter (ms)
- Ziele: Provider-Gateway, öffentliche Endpunkte (DE-CIX-nah, Cloudflare, Google DNS)

Beispiel-Entitäten:
- `sensor.ping_provider`
- `sensor.ping_public`
- `sensor.packet_loss`
- `sensor.jitter`

### Verfügbarkeit
- Online-Zeit (%), Disconnect-Anzahl, Ausfalldauer
- Daten aus WAN-/Router-Status und Messlauf-Historie

Zusatz:
- Qualitätsklasse (z. B. A–E)
- BNetzA-ähnliche Konformitätsbewertung (konzeptionell)

---

## 3.2 Config Flow (Pflichtfelder + Optionen)

Der Benutzer gibt im Config Flow mindestens an:

1. **Internetanbieter (ISP)**  
2. **Gebuchten Tarif** (mind./normal/max Download/Upload)  
3. **Routertyp** (z. B. FRITZ!Box, OpenWRT, UniFi, Sonstige)

Optionale Schritte:
- Standort/Region (PLZ oder Bundesland) für Störungsfilter
- Messintervall (Speedtest, Ping, Statuschecks)
- Opt-in für externe Quellen/Anonymisierung
- Auswahl bevorzugter Zielserver
- **Test-Adressen verwalten:** vorgeschlagene Standardziele + manuell ergänzbare Ziele (IP, FQDN oder URL), inkl. Aktivieren/Deaktivieren und Priorisierung
- **Dienststatus-Quellen auswählen (Checkboxen):** vordefinierte Dienste/Kategorien (z. B. Amazon, Google, Microsoft, Netflix, Spotify, Discord, WhatsApp, YouTube, OpenAI, Claude, GitHub) einzeln aktivierbar

Wichtig: Routertyp steuert optionale Adapterpfade (z. B. FRITZ!Box-nahe Datenerhebung analog Home-Assistant-FRITZ-Integration).

---

## 3.3 Datenquellen & Architektur

### Lokale Daten
- Router-Adapter (API/SNMP je Typ)
- Speedtest-Quelle(n) (lokal via Agent/Add-on empfohlen)
- ICMP/TCP/HTTPS/DNS-Checks
- Interface-/WAN-Status

### Externe Daten
- ISP-Störungsseiten (wenn technisch/rechtlich zulässig)
- Statusaggregatoren (z. B. Downdetector, verfügbare RSS/Statusfeeds)
- Globale Dienste (Cloudflare, AWS, Azure, GCP, DNS-Anbieter)

### Konfigurierbare Dienst-Ausfallquellen (Setup per Checkbox)

Vorgesehene Quellenstrategie je Dienst:
1. **Primär:** offizielle Statusquellen des Dienstes (API, JSON, RSS/Atom, offizielles Status-Dashboard)
2. **Sekundär:** Statuspage.io-basierte Seiten (inkl. standardisierter Komponenten-/Incident-Daten)
3. **Fallback:** ausgewählte Aggregatoren/Feeds mit klarer Kennzeichnung geringerer Verlässlichkeit

Beispielhafte Zuordnung für den initialen Katalog (im Config Flow auswählbar):

| Dienst/Kategorie | Primärquelle (bevorzugt) | Alternative/Fallback |
|---|---|---|
| Amazon (AWS) | Offizielles AWS Service Health/Status Dashboard | Statuspage-Feed, falls vorhanden |
| Google (inkl. YouTube) | Google Cloud/Workspace/YouTube Statusseiten | RSS/Atom-Feeds der Statusseiten |
| Microsoft | Azure-/Microsoft-365-Statusquellen | öffentliche Statusseiten je Produkt |
| Netflix | Offizielles Netflix-Statusdashboard | Statuspage.io-Daten, falls genutzt |
| Spotify | Offizielle Spotify-Statusseite | Statuspage.io-Daten, falls genutzt |
| Discord | Offizielle Discord-Statusseite | Statuspage.io-Daten, falls genutzt |
| WhatsApp | Offizielle Meta/WhatsApp-Störungsmeldungen (falls öffentlich) | verlässliche Incident-Feeds mit Kennzeichnung |
| OpenAI | Offizielle OpenAI-Statusseite | Statuspage.io-Daten, falls genutzt |
| Claude (Anthropic) | Offizielle Anthropic-Statusseite | Statuspage.io-Daten, falls genutzt |
| GitHub | Offizielle GitHub-Statusseite | Statuspage.io API/Feed |

Hinweis zur Umsetzung:
- Quellen werden vor Aktivierung technisch/rechtlich validiert (Verfügbarkeit, Rate Limits, Nutzungsbedingungen).
- Im Config Flow werden Dienste als Checkboxen angezeigt; pro aktivem Dienst wird die bestverfügbare Quelle gemäß Priorität genutzt.
- Optionaler Expertenmodus: Quelle pro Dienst manuell überschreiben.

### Architekturprinzip
- Messausführung nicht schwergewichtig im HA-Core
- bevorzugt: begleitender Agent/Add-on liefert Ergebnisse per lokaler Schnittstelle (REST/MQTT)
- Integration fokussiert auf Orchestrierung, Normalisierung, Bewertung, Entitäten, Dashboard, Report

---

## 3.4 Störungs- und Abhängigkeitsmonitoring

ISP:
- `sensor.isp_stoerung_status`
- `sensor.isp_stoerung_region`

Globale Dienste:
- `binary_sensor.cloudflare_status`
- `sensor.aws_latency`
- `sensor.dns_resolve_time_*`

Heuristiken:
- Korrelation lokaler Qualitätsabfälle mit externen Statusereignissen
- Kennzeichnung „vermutlich lokal / providerseitig / global“

---

## 4) Integriertes Dashboard (bei Installation verfügbar)

Ziel: out-of-the-box Dashboard, automatisch bereitgestellt (analog etablierter Integrationen wie FWCAM).

Inhalte:
- KPI-Karten (Download/Upload/Ping/Jitter/Verfügbarkeit/Score)
- Zeitreihen (24h/7d/30d)
- Tabellenansicht (Messfenster, SLA-Verstöße, Ausfälle)
- SLA-Ampel (grün/gelb/rot)
- Ausfall-Timeline
- „Provider-Beweis“-Bereich

PDF-Bericht:
- Exportierbarer Qualitäts-/Störungsbericht aus aggregierten Messdaten
- Enthält Tarifbezug, Messfenster, Verstöße, Statistik und Ereignisliste
- Download direkt über Integration (Service oder UI-Aktion)

---

## 5) Automationen, Events, Benachrichtigungen

Beispiele:
- Ping > X ms für Y Minuten
- Paketverlust > 2 %
- Download < 60 % der Tarif-Referenz
- wiederholte SLA-Verletzung im Monat

Ausgaben:
- Home-Assistant-Events
- Push/Notify
- optional E-Mail-Monatsreport
- optional kontrollierter Router-Reconnect (deaktiviert per Default)

---

## 6) Datenschutz & Sicherheit

- Standard: lokale Verarbeitung und Speicherung
- externe Checks nur nach transparentem Opt-in
- keine ungewollte Weitergabe von Messhistorien
- klarer Diagnostikexport ohne Secrets
- Timeouts/Retry/Circuit-Breaker für externe Endpunkte

---

## 7) Erweiterungen (zusätzlich empfohlen)

1. **LAN-vs-WLAN-Vergleich** pro Messzyklus  
2. **Endgeräte-Qualität** (kritische Clients als separate Sensorgruppen)  
3. **Traceroute-Analyse** zur Engpasslokalisierung  
4. **Quality Score (0–100)** aus Bandbreite, Stabilität, Verfügbarkeit  
5. **Vertrags-Monitoring** inkl. Nachweisdatenexport  
6. **Anomalieerkennung** (historischer Baseline-Vergleich)  
7. **Wartungsfenster-Modus** zur Unterdrückung falscher Alarme  
8. **Mehranschlussfähigkeit** (Fallback LTE/5G/zweiter WAN-Link)

---

## 8) Entscheidungen vor Umsetzung/Implementierung

| Bereich | Offene Entscheidung | Optionen | Empfehlung (Start) | Auswirkung |
|---|---|---|---|---|
| Messausführung | Wo laufen aktive Speedtests/Pings? | HA direkt / Add-on oder externer Agent | Add-on oder externer Agent | Stabilität, Ressourcen, Wartbarkeit |
| Speedtest-Backend | Welche Engine wird genutzt? | Abstraktionsschicht + austauschbares Backend | Abstraktionsschicht + austauschbares Backend | Genauigkeit, Lizenz, Abhängigkeiten |
| BNetzA-Abbildung | Welche Regelmenge wird initial umgesetzt? | erweitert (Perzentile + Zeitfenster) | erweitert, aber modular | Vergleichbarkeit, Komplexität |
| Routerintegration | Welche Router zuerst nativ? | FRITZ!Box / OpenWRT / UniFi | FRITZ!Box zuerst, danach Adaptermodell | Time-to-market, Datenqualität |
| ISP-Störungsdaten | Welche Quellen sind rechtlich/technisch robust? | bevorzugt API/Feed, Scraping nur fallback | bevorzugt API/Feed, Scraping nur fallback | Zuverlässigkeit, Compliance |
| Dienststatus-Katalog | Welche externen Dienste sind im Setup auswählbar? | fester Startkatalog + später erweiterbar | Startkatalog (Amazon, Google/YouTube, Microsoft, Netflix, Spotify, Discord, WhatsApp, OpenAI, Claude, GitHub) | Nutzwert, Pflegeaufwand, API-Abhängigkeiten |
| Regionserkennung | Wie wird regional gefiltert? | manuelle Angabe im Config Flow | manuelle Angabe im Config Flow | Präzision, Datenschutz |
| Dashboard-Bereitstellung | Wie „auto-installiert“ bereitstellen? | Dashboard-JSON + Setup-Service | Dashboard-JSON + Setup-Service | UX, Wartung |
| PDF-Export | Wie wird PDF erzeugt? | HTML→PDF lokal im Add-on/Agent | lokal im Add-on/Agent | Sicherheit, Portabilität |
| Datenspeicherung | Wo liegen Roh- und Aggregatdaten? | Recorder + optional InfluxDB | Recorder + optional InfluxDB | Historie, Performance |
| Scoring-Modell | Wie wird der 0–100 Score gewichtet? | statische Defaults + konfigurierbar | statische Defaults + konfigurierbar | Verständlichkeit, Vergleichbarkeit |
| Alarmstrategie | Schwellwerte global oder profilbasiert? | globale Defaults + Expertenmodus | globale Defaults + Expertenmodus | Einfache Erstkonfiguration, später feinere Profile zur Reduktion von Fehlalarmen |
| Multi-WAN | Wird Redundanz früh unterstützt? | später (Phase 2) | später (Phase 2) | Scope, Architektur |

---

## 9) Umsetzungsphasen (empfohlen)

1. **MVP**
   - Config Flow (ISP, Tarif, Routertyp)
   - Basis-Sensoren (Speed, Ping, Verlust, Verfügbarkeit)
   - Basis-Dashboard
2. **BNetzA+/SLA**
   - Qualitätsklasse, Tarifquote, Verstoßlogik, Monatsreport
3. **Störungs-Ökosystem**
   - ISP-/Globalstatus-Korrelation
4. **Advanced**
   - Traceroute, LAN/WLAN-Vergleich, Endgerätesicht, Multi-WAN

---

## 10) Referenzen

- Home Assistant FRITZ-Integration (Routerbezug):  
  https://github.com/home-assistant/core/tree/dev/homeassistant/components/fritz
- Breitbandmessung-Automat (BNetzA-orientierte Messidee):  
  https://github.com/FlorianZimmer/Breitbandmessung-Automat
- Beispiel einer Integration mit eigenem Dashboardansatz:  
  https://github.com/northpower25/HA-Fuel-Watcher-Car-Advanced-Manager-FWCAM
