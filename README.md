# APEX LIVE — Forza Horizon 6 Telemetrie-Dashboard

Ein lokales Live-Telemetrie-Dashboard für Forza Horizon 6. Eine einzelne Python-Datei, keine externen Pakete, kein Konto, keine Cloud. Das Spiel sendet seine Fahrdaten ("Data Out") per UDP an dein eigenes Gerät; das Programm wertet sie aus und zeigt ein Dashboard im Browser an.

**Sprache / Language:** [Deutsch](#deutsch) · [English](#english)

---

## Deutsch

### Was ist das

Forza Horizon 6 kann während der Fahrt Telemetriedaten über das Netzwerk senden (Funktion "Data Out"). Dieses Programm empfängt diese Daten, zerlegt das Datenpaket und stellt die Werte live in einem Browser-Dashboard dar: Geschwindigkeit (analoger oder digitaler Tacho), Drehzahl mit Schaltpunkt-Anzeige, Reifentemperaturen und Grip, G-Kräfte, Federwege, Fahrer-Eingaben, Motordaten, Renn-Informationen und eine selbst gezeichnete Streckenkarte.

### Wie es funktioniert (wichtig)

Das Spiel **sendet** die Daten an genau einen Empfänger. Dieses Programm **ist** der Empfänger und muss auf einem Rechner laufen. Der Browser (auch auf dem Handy) ist nur die Anzeige, nicht der Empfänger — ein Browser allein kann keine rohen UDP-Pakete empfangen. Es braucht also immer dieses kleine Programm dazwischen.

### Voraussetzungen

- Python 3.7 oder neuer
- Keine zusätzlichen Pakete (es wird ausschließlich die Standardbibliothek verwendet)
- Forza Horizon 6 auf einem PC oder einer physischen Xbox-Konsole im selben Netzwerk

### Einrichtung in Forza Horizon 6

Im Spiel: **Einstellungen → HUD & Gameplay → Data Out**

| Einstellung | Wert |
|---|---|
| Data Out | Ein |
| Data Out IP Address | `127.0.0.1` (wenn das Programm auf demselben PC läuft) |
| Data Out IP Port | `5607` (oder ein anderer Port; **nicht** 5200–5300) |

`127.0.0.1` bedeutet "dieser Rechner". Wenn der Empfänger auf einem anderen Gerät im Netzwerk läuft (z. B. einem Heimserver), trägst du stattdessen dessen lokale IP-Adresse ein (z. B. `192.168.x.x`).

### Starten

Im Terminal in den Ordner mit der Datei wechseln, dann:

```bash
python apex_live_fh6.py
```

Falls `python` nicht funktioniert, `python3` (macOS/Linux) bzw. `py` (Windows) versuchen.

Eigene Ports angeben (UDP-Port, dann Web-Port):

```bash
python apex_live_fh6.py 5607 8000
```

Nach dem Start öffnet sich der Browser automatisch auf `http://localhost:8000`. Das Terminal-Fenster offen lassen — das ist das laufende Programm.

**Beenden:** im Terminal `Strg + C`.

### Anzeige auf dem Handy oder Tablet

Das Dashboard ist im gesamten Heimnetz erreichbar. Voraussetzung: dasselbe WLAN.

1. Lokale IP des Rechners herausfinden (Windows: `ipconfig`, die IPv4-Adresse wie `192.168.x.x`; macOS/Linux: `ifconfig` oder `ip addr`).
2. Am Handy im Browser `http://192.168.x.x:8000` öffnen.

Das Handy zeigt dann nur an. Empfangen und auswerten tut weiterhin der Rechner, auf dem das Programm läuft.

### Funktionen

- Tacho, umschaltbar zwischen analoger Nadel und großer Digitalanzeige
- Drehzahl mit Schaltlichtern, einstellbarem Schaltpunkt und mitgelernter Leistungsspitze
- Reifen: Temperatur (Farbskala) und kombinierter Schlupf pro Rad
- Fahrwerk: G-Kraft-Diagramm und Federwege pro Rad
- Fahrer-Eingaben: Gas, Bremse, Kupplung, Handbremse, Lenkung
- Antrieb: Drehzahl, Leistung, Drehmoment, Gang, Antriebsart, Zylinder
- Rennen: das letzte Rennen bleibt eingefroren, bis ein neues startet; Export als TXT-Datei zum Vergleichen
- Karte: deine gefahrene Strecke wird live gezeichnet (nach Tempo eingefärbt); optional kannst du privat ein eigenes Kartenbild hinterlegen
- Auto-Modell: das Spiel sendet keinen Namen, nur eine ID; du vergibst den Namen einmal selbst, das Programm merkt ihn sich pro Fahrzeug

### Wo es funktioniert — und wo nicht

| Plattform | Funktioniert? |
|---|---|
| PC (Steam / Microsoft Store) | Ja — Programm läuft auf demselben PC |
| Xbox-Konsole (physisch zu Hause) | Ja — Konsole sendet an einen Rechner/Server im selben Heimnetz |
| Xbox Cloud Gaming | Nein — siehe unten |

Bei **Xbox Cloud Gaming** läuft das Spiel auf einem Microsoft-Server, nicht bei dir zu Hause. Die Telemetrie würde das Rechenzentrum nie verlassen. Das ist eine Eigenschaft des Cloud-Streamings und betrifft jedes Telemetrie-Tool, nicht nur dieses.

### Alles läuft lokal

- Die Telemetrie verlässt dein Gerät bzw. dein Heimnetz nicht. Es gibt keinen Server im Internet, kein Konto, kein Tracking.
- Das Dashboard wird von deinem eigenen Rechner ausgeliefert.
- Ein hinterlegtes Kartenbild und vergebene Auto-Namen werden ausschließlich lokal im Browser gespeichert und nirgendwo hochgeladen.
- Einzige Ausnahme: Die Schriftart wird vom Google-Fonts-CDN geladen (rein kosmetisch). Ohne Internet fällt die Anzeige auf System-Schriften zurück und funktioniert voll.

### Fehlerbehebung

- **Dashboard bleibt auf "warte auf Daten":** Data Out im Spiel aktiv? Stimmt der Port im Spiel mit dem Programm überein? Das Spiel sendet nur **während der aktiven Fahrt** — nicht in Menüs, Pausen oder Wiederholungen.
- **Windows-Firewall fragt beim Start:** einmal erlauben. Das ist eine lokale Erlaubnis für das Programm, kein offener Port ins Internet.
- **Port belegt:** Läuft parallel ein anderes Telemetrie-Tool (z. B. SimHub) auf demselben Port? Dann einen anderen Port wählen, im Spiel und beim Programmstart.
- **Änderungen werden nicht sichtbar:** Programm beenden und neu starten, im Browser hart neu laden (`Strg + F5`).



### Hinweis

Kein offizielles Tool. Forza Horizon 6 ist eine Marke von Microsoft / Playground Games. Dieses Projekt steht in keiner Verbindung zu Microsoft oder Playground Games.

---

## English

A local live telemetry dashboard for Forza Horizon 6. A single Python file, no external packages, no account, no cloud. The game sends its driving data ("Data Out") over UDP to your own device; the program decodes it and shows a dashboard in your browser.

### What this is

Forza Horizon 6 can send telemetry over the network while you drive (the "Data Out" feature). This program receives that data, decodes the packet, and displays the values live in a browser dashboard: speed (analog or digital), engine RPM with a shift indicator, tire temperatures and grip, G-forces, suspension travel, driver inputs, engine data, race information, and a self-drawn track map.

### How it works (important)

The game **sends** the data to exactly one receiver. This program **is** the receiver and must run on a computer. The browser (including on a phone) is only the display, not the receiver — a browser alone cannot receive raw UDP packets. This small program is always required in between.

### Requirements

- Python 3.7 or newer
- No additional packages (standard library only)
- Forza Horizon 6 on a PC or a physical Xbox console on the same network

### Setup in Forza Horizon 6

In game: **Settings → HUD and Gameplay → Data Out**

| Setting | Value |
|---|---|
| Data Out | On |
| Data Out IP Address | `127.0.0.1` (if the program runs on the same PC) |
| Data Out IP Port | `5607` (or another port; **not** 5200–5300) |

`127.0.0.1` means "this computer". If the receiver runs on a different device on your network (for example a home server), enter that device's local IP instead (for example `192.168.x.x`).

### Running it

Open a terminal in the folder that contains the file, then:

```bash
python apex_live_fh6.py
```

If `python` does not work, try `python3` (macOS/Linux) or `py` (Windows).

Custom ports (UDP port, then web port):

```bash
python apex_live_fh6.py 5607 8000
```

The browser opens automatically at `http://localhost:8000`. Keep the terminal window open — that is the running program.

**Stop:** press `Ctrl + C` in the terminal.

### Viewing on a phone or tablet

The dashboard is reachable across your home network. Both devices must be on the same Wi-Fi.

1. Find the computer's local IP (Windows: `ipconfig`, the IPv4 address like `192.168.x.x`; macOS/Linux: `ifconfig` or `ip addr`).
2. On the phone, open `http://192.168.x.x:8000` in a browser.

The phone only displays. The computer running the program still does the receiving and decoding.

### Features

- Speedometer, switchable between an analog needle and a large digital readout
- RPM with shift lights, an adjustable shift point, and a learned power peak
- Tires: temperature (color scale) and combined slip per wheel
- Chassis: a G-force diagram and suspension travel per wheel
- Driver inputs: throttle, brake, clutch, handbrake, steering
- Drivetrain: RPM, power, torque, gear, drivetrain type, cylinders
- Race: the last race stays frozen until a new one begins; export as a TXT file for comparison
- Map: your driven track is drawn live (colored by speed); optionally you can add your own map image privately
- Car model: the game sends no name, only an ID; you name it once and the program remembers it per car

### Where it works — and where it does not

| Platform | Works? |
|---|---|
| PC (Steam / Microsoft Store) | Yes — program runs on the same PC |
| Xbox console (physical, at home) | Yes — console sends to a computer/server on the same home network |
| Xbox Cloud Gaming | No — see below |

With **Xbox Cloud Gaming** the game runs on a Microsoft server, not at your home. The telemetry would never leave the data center. This is a property of cloud streaming and affects every telemetry tool, not just this one.

### Everything runs locally

- The telemetry never leaves your device or home network. There is no internet server, no account, no tracking.
- The dashboard is served from your own computer.
- An added map image and any car names are stored only locally in your browser and are never uploaded.
- The only exception: the font is loaded from the Google Fonts CDN (purely cosmetic). Without internet the display falls back to system fonts and still works fully.

### Troubleshooting

- **Dashboard stays on "waiting for data":** Is Data Out enabled in game? Does the port in game match the program? The game only sends **while you are actively driving** — not in menus, pauses, or replays.
- **Windows Firewall prompt on start:** allow it once. This is a local permission for the program, not an open port to the internet.
- **Port in use:** Is another telemetry tool (such as SimHub) running on the same port? Choose a different port, both in game and when starting the program.
- **Changes not showing:** stop and restart the program, then hard-reload the browser (`Ctrl + F5`).


### Note

This is not an official tool. Forza Horizon 6 is a trademark of Microsoft / Playground Games. This project is not affiliated with Microsoft or Playground Games.
