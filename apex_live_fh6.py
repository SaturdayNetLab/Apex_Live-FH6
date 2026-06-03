#!/usr/bin/env python3
"""
APEX LIVE  -  Forza Horizon 6 Live-Telemetrie-Dashboard
=======================================================
Lokales Programm. Keine externen Pakete noetig (nur Python-Standardbibliothek).

WAS ES MACHT
  - Lauscht auf dem UDP-Port, an den FH6 "Data Out" sendet
  - Parst das feste 324-Byte-FH6-Paket (inkl. der 12 Horizon-Extra-Bytes)
  - Serviert ein Racing-Dashboard lokal im Browser und streamt die Werte live (SSE)

EINRICHTUNG IN FORZA HORIZON 6
  Einstellungen -> HUD & Gameplay -> Data Out:
    Data Out            : Ein
    Data Out IP Address : 127.0.0.1
    Data Out IP Port    : 5607        (oder dein Wunschport, NICHT 5200-5300)

START
    python apex_live_fh6.py                 # Standard: UDP 5607, Web 8000
    python apex_live_fh6.py 5607 8000       # UDP-Port, Web-Port frei waehlbar

Dann im Browser:  http://localhost:8000   (oeffnet sich automatisch)
Beenden: Strg + C
"""

import socket
import struct
import threading
import json
import time
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# Konfiguration (per Kommandozeile ueberschreibbar)
# ---------------------------------------------------------------------------
UDP_PORT = 5607
HTTP_PORT = 8000
def _port_arg(i, default):
    if len(sys.argv) > i:
        try:
            p = int(sys.argv[i])
            if not (1 <= p <= 65535):
                raise ValueError
            return p
        except ValueError:
            print(f"[FEHLER] Ungueltiger Port '{sys.argv[i]}'. Erlaubt: 1-65535.")
            print(f"         Aufruf:  python {sys.argv[0]} [UDP-Port] [Web-Port]")
            sys.exit(1)
    return default
UDP_PORT = _port_arg(1, UDP_PORT)
HTTP_PORT = _port_arg(2, HTTP_PORT)
if UDP_PORT == HTTP_PORT:
    print("[FEHLER] UDP-Port und Web-Port muessen unterschiedlich sein.")
    sys.exit(1)

LATEST = {}                 # zuletzt empfangenes, geparstes Paket
LOCK = threading.Lock()     # schuetzt LATEST gegen gleichzeitigen Zugriff

CLASS_NAMES = {0: "D", 1: "C", 2: "B", 3: "A", 4: "S1", 5: "S2", 6: "X"}
DT_NAMES = {0: "FWD", 1: "RWD", 2: "AWD"}

# ---------------------------------------------------------------------------
# PARSER  -  exakte FH6-Byte-Offsets (Little-Endian)
#
# Aufbau (offiziell dokumentiert):
#   0   .. 231  "Sled" (identisch zu Forza Motorsport)
#   232 .. 243  FH6-NEU: CarGroup, SmashableVelDiff, SmashableMass  (3 x 4 Byte)
#   244 .. 322  "Dash" (gegenueber FM um +12 Byte verschoben)
#   323         ein Trailing-Byte  ->  Gesamtgroesse 324 Byte
# ---------------------------------------------------------------------------
def parse(buf):
    if len(buf) < 324:
        return None
    g = lambda fmt, off: struct.unpack_from("<" + fmt, buf, off)[0]
    d = {}
    # --- Sled ---
    d["isRaceOn"] = g("i", 0)
    d["rpmMax"]   = g("f", 8)
    d["rpmIdle"]  = g("f", 12)
    d["rpm"]      = g("f", 16)
    d["accelX"]   = g("f", 20)   # lateral (+rechts)
    d["accelY"]   = g("f", 24)   # vertikal
    d["accelZ"]   = g("f", 28)   # laengs (+vorwaerts)
    d["yaw"]      = g("f", 56)
    d["pitch"]    = g("f", 60)
    d["roll"]     = g("f", 64)
    # normalisierter Federweg (0=ausgefedert .. 1=voll komprimiert)
    d["suspFL"] = g("f", 68); d["suspFR"] = g("f", 72)
    d["suspRL"] = g("f", 76); d["suspRR"] = g("f", 80)
    # Schlupf laengs (slip ratio)
    d["slipFL"] = g("f", 84); d["slipFR"] = g("f", 88)
    d["slipRL"] = g("f", 92); d["slipRR"] = g("f", 96)
    # Schraeglaufwinkel (slip angle)
    d["angFL"] = g("f", 164); d["angFR"] = g("f", 168)
    d["angRL"] = g("f", 172); d["angRR"] = g("f", 176)
    # kombinierter Schlupf
    d["combFL"] = g("f", 180); d["combFR"] = g("f", 184)
    d["combRL"] = g("f", 188); d["combRR"] = g("f", 192)
    # Fahrzeug-Stammdaten
    d["carOrdinal"] = g("i", 212)   # eindeutige Fahrzeug-ID (kein Klartext-Name im Stream)
    d["carClass"]   = g("i", 216)
    d["pi"]         = g("i", 220)
    d["drivetrain"] = g("i", 224)
    d["cyl"]        = g("i", 228)
    # 232/236/240 = FH6-Extrafelder (CarGroup, SmashableVelDiff, SmashableMass) -> uebersprungen
    # --- Dash (ab 244) ---
    d["posX"] = g("f", 244)   # Welt-Koordinaten in Metern
    d["posY"] = g("f", 248)   # Hoehe
    d["posZ"] = g("f", 252)
    d["speed"]  = g("f", 256)   # m/s
    d["power"]  = g("f", 260)   # Watt
    d["torque"] = g("f", 264)   # Nm
    d["tempFL"] = g("f", 268); d["tempFR"] = g("f", 272)
    d["tempRL"] = g("f", 276); d["tempRR"] = g("f", 280)
    d["boost"]    = g("f", 284)
    d["fuel"]     = g("f", 288)  # 0..1
    d["distance"] = g("f", 292)  # Meter
    d["bestLap"]  = g("f", 296)
    d["lastLap"]  = g("f", 300)
    d["curLap"]   = g("f", 304)
    d["raceTime"] = g("f", 308)
    d["lap"]      = g("H", 312)
    d["pos"]      = g("B", 314)
    d["accel"]    = g("B", 315)  # 0..255
    d["brake"]    = g("B", 316)
    d["clutch"]   = g("B", 317)
    d["hbrake"]   = g("B", 318)
    d["gear"]     = g("B", 319)
    d["steer"]    = g("b", 320)  # -127..127
    return d


def udp_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", UDP_PORT))
    except OSError as e:
        print(f"\n[FEHLER] UDP-Port {UDP_PORT} laesst sich nicht oeffnen: {e}")
        print(f"         Laeuft schon ein anderes Telemetrie-Tool auf diesem Port?")
        print(f"         Anderen Port waehlen:  python {sys.argv[0]} <UDP-Port> <Web-Port>\n")
        import os
        os._exit(1)
    print(f"[UDP] lausche auf Port {UDP_PORT} ... (in FH6 Data Out aktivieren)")
    while True:
        try:
            data, _ = sock.recvfrom(2048)
        except OSError:
            continue
        p = parse(data)
        if p:
            p["recv"] = time.time()
            with LOCK:
                LATEST.clear()
                LATEST.update(p)


# ---------------------------------------------------------------------------
# HTTP + SSE  -  serviert das Dashboard und streamt die Live-Werte
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass  # ruhig halten

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    with LOCK:
                        snap = dict(LATEST)
                    if snap:
                        snap["_age"] = round(time.time() - snap.get("recv", 0), 3)
                    else:
                        snap = {"_age": 999}
                    msg = "data: " + json.dumps(snap) + "\n\n"
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(1 / 60)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


def main():
    t = threading.Thread(target=udp_loop, daemon=True)
    t.start()
    try:
        server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    except OSError as e:
        print(f"\n[FEHLER] Web-Port {HTTP_PORT} laesst sich nicht oeffnen: {e}")
        print(f"         Anderen Port waehlen:  python {sys.argv[0]} {UDP_PORT} <Web-Port>\n")
        return
    url = f"http://localhost:{HTTP_PORT}"
    print("=" * 58)
    print("  APEX LIVE  -  Forza Horizon 6 Telemetrie")
    print("=" * 58)
    print(f"  Dashboard : {url}")
    print(f"  UDP-Port  : {UDP_PORT}   (in FH6: Data Out IP 127.0.0.1)")
    print("  Beenden   : Strg + C")
    print("=" * 58)

    def open_browser():
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Timer(1.0, open_browser).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbeendet.")
    finally:
        server.server_close()


# ---------------------------------------------------------------------------
# DASHBOARD  (HTML/CSS/JS, eingebettet)
# ---------------------------------------------------------------------------
PAGE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APEX LIVE · FH6 Telemetrie</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0A0B0D; --panel:#121419; --panel2:#171A20; --line:#23262E; --lineSoft:#1B1E24;
    --txt:#E7E9EC; --dim:#8A8F99; --faint:#5A5F6A;
    --accent:#FF3326; --data:#1FE3C6; --warn:#FFB020; --good:#46D17B; --cold:#3FA9FF;
  }
  *{box-sizing:border-box;}
  body{
    margin:0;background:var(--bg);color:var(--txt);font-family:'Chakra Petch',system-ui,sans-serif;
    background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),
                     linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);
    background-size:46px 46px;-webkit-font-smoothing:antialiased;min-height:100vh;
  }
  .mono{font-family:'IBM Plex Mono',monospace;}
  .wrap{max-width:1180px;margin:0 auto;padding:14px 16px 60px;}

  /* top bar */
  .top{display:flex;align-items:center;gap:14px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:16px;}
  .logo{font-weight:700;font-size:22px;letter-spacing:.06em;text-transform:uppercase;}
  .logo .ap{color:var(--accent);}
  .logo small{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--dim);letter-spacing:.16em;margin-left:8px;}
  .conn{display:flex;align-items:center;gap:7px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim);}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--faint);transition:background .2s,box-shadow .2s;}
  .dot.on{background:var(--good);box-shadow:0 0 10px var(--good);}
  .dot.wait{background:var(--warn);box-shadow:0 0 10px var(--warn);}
  .spacer{flex:1;}
  .badges{display:flex;gap:7px;flex-wrap:wrap;}
  .badge{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.06em;padding:5px 9px;border-radius:7px;
         background:var(--panel2);border:1px solid var(--line);color:var(--dim);text-transform:uppercase;}
  .badge b{color:var(--data);font-weight:600;}
  .tbtn{background:transparent;border:1px solid var(--line);color:var(--dim);padding:7px 12px;border-radius:8px;
        font-family:'Chakra Petch';font-weight:600;font-size:12px;letter-spacing:.06em;text-transform:uppercase;cursor:pointer;transition:.15s;}
  .tbtn:hover{border-color:var(--dim);color:var(--txt);}
  .tbtn.on{border-color:var(--accent);color:var(--accent);}

  /* hero */
  .hero{display:grid;grid-template-columns:300px 1fr;gap:16px;margin-bottom:16px;}
  @media(max-width:760px){.hero{grid-template-columns:1fr;}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;position:relative;overflow:hidden;}
  .card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent);opacity:.85;}
  .speedo{display:flex;flex-direction:column;align-items:center;justify-content:center;}
  #gauge{width:268px;height:268px;max-width:100%;}
  .digi{display:none;flex-direction:column;align-items:center;justify-content:center;height:268px;}
  .digi .big{font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:84px;line-height:.9;color:var(--data);}
  .digi .unit{color:var(--dim);letter-spacing:.2em;font-size:14px;text-transform:uppercase;margin-top:6px;}
  body.mode-digi #gauge{display:none;}
  body.mode-digi .digi{display:flex;}

  .rpmwrap{display:flex;flex-direction:column;gap:14px;}
  .rpmtop{display:flex;align-items:center;gap:18px;}
  .gear{font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:72px;line-height:.8;min-width:78px;text-align:center;
        border:1px solid var(--line);border-radius:12px;padding:8px 4px;background:var(--panel2);}
  .gearstat{flex:1;}
  .rpmnum{font-family:'IBM Plex Mono',monospace;font-size:30px;font-weight:600;color:var(--data);}
  .rpmnum small{font-size:13px;color:var(--dim);letter-spacing:.12em;}
  .shift{display:flex;gap:5px;margin-top:8px;}
  .shift span{flex:1;height:6px;border-radius:3px;background:var(--lineSoft);transition:background .05s;}
  .rpmbar{height:24px;border-radius:7px;background:var(--panel2);border:1px solid var(--line);overflow:hidden;position:relative;}
  .rpmfill{height:100%;width:0;background:linear-gradient(90deg,var(--data),var(--data) 70%,var(--warn) 88%,var(--accent));transition:width .05s;}
  .redzone{position:absolute;top:0;bottom:0;right:0;width:8%;background:rgba(255,51,38,.18);border-left:1px solid var(--accent);}
  .quick{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:4px;}
  .q{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:9px 10px;}
  .q .l{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);}
  .q .v{font-family:'IBM Plex Mono',monospace;font-size:19px;font-weight:600;color:var(--txt);margin-top:2px;}

  /* tabs */
  .tabs{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:14px;}
  .panel{display:none;}
  .panel.on{display:block;animation:fade .25s;}
  @keyframes fade{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:none;}}

  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
  .grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
  @media(max-width:680px){.grid4{grid-template-columns:1fr 1fr;}.grid2{grid-template-columns:1fr;}}
  .kv{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed var(--lineSoft);}
  .kv:last-child{border-bottom:none;}
  .kv .k{font-size:13px;color:var(--dim);}
  .kv .v{font-family:'IBM Plex Mono',monospace;font-size:16px;color:var(--data);font-weight:500;}
  .ch{font-size:12px;letter-spacing:.16em;text-transform:uppercase;font-weight:700;margin:0 0 10px;display:flex;align-items:center;gap:8px;}
  .ch::before{content:"";width:12px;height:2px;background:var(--accent);}

  /* tires */
  .carview{display:grid;grid-template-columns:1fr 80px 1fr;grid-template-rows:auto auto;gap:12px 0;align-items:center;}
  .tire{background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:12px;text-align:center;}
  .tire .pos{font-size:10px;letter-spacing:.14em;color:var(--faint);text-transform:uppercase;}
  .tire .tmp{font-family:'IBM Plex Mono',monospace;font-size:26px;font-weight:600;margin:4px 0;}
  .tire .sl{font-size:11px;color:var(--dim);}
  .tire .bar{height:5px;border-radius:3px;background:var(--lineSoft);margin-top:7px;overflow:hidden;}
  .tire .bar i{display:block;height:100%;width:0;background:var(--accent);}
  .chassis{display:flex;align-items:center;justify-content:center;color:var(--faint);font-size:10px;letter-spacing:.1em;writing-mode:vertical-rl;text-transform:uppercase;}

  /* gforce */
  .gbox{display:flex;flex-direction:column;align-items:center;}
  #gforce{width:200px;height:200px;}
  .gnums{display:flex;gap:18px;margin-top:6px;}
  .gnums div{text-align:center;}
  .gnums .l{font-size:10px;color:var(--dim);letter-spacing:.1em;text-transform:uppercase;}
  .gnums .v{font-family:'IBM Plex Mono',monospace;font-size:18px;color:var(--data);}

  /* inputs */
  .inbars{display:flex;gap:16px;align-items:flex-end;justify-content:center;height:200px;}
  .ibar{display:flex;flex-direction:column;align-items:center;gap:8px;height:100%;}
  .ibar .col{width:34px;flex:1;background:var(--panel2);border:1px solid var(--line);border-radius:8px;position:relative;overflow:hidden;display:flex;align-items:flex-end;}
  .ibar .col i{display:block;width:100%;height:0%;transition:height .05s;}
  .ibar .lab{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);}
  .steerwrap{margin-top:14px;}
  .steerbar{height:10px;border-radius:5px;background:var(--panel2);border:1px solid var(--line);position:relative;}
  .steerknob{position:absolute;top:50%;left:50%;width:14px;height:14px;border-radius:50%;background:var(--data);transform:translate(-50%,-50%);transition:left .05s;box-shadow:0 0 10px var(--data);}
  .steercenter{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--faint);}

  /* suspension */
  .susp{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
  .scorner{background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:12px;}
  .scorner .pos{font-size:10px;letter-spacing:.14em;color:var(--faint);text-transform:uppercase;}
  .scorner .track{height:90px;border-radius:8px;background:var(--lineSoft);margin-top:8px;position:relative;overflow:hidden;}
  .scorner .track i{position:absolute;left:0;right:0;bottom:0;background:linear-gradient(180deg,var(--data),#119a86);transition:height .05s;}
  .scorner .pct{font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--dim);margin-top:6px;text-align:center;}

  .note{font-size:11px;color:var(--faint);margin-top:12px;line-height:1.5;}
  .waiting{text-align:center;color:var(--dim);padding:40px 10px;font-size:14px;letter-spacing:.04em;}
  /* Auto-Namensfeld */
  .carname-badge{display:inline-flex;align-items:center;gap:6px;padding:3px 8px 3px 9px;}
  .carname-badge .ord{color:var(--faint);font-size:10px;}
  .carname-badge input{
    width:140px;background:transparent;border:none;border-bottom:1px solid var(--line);
    color:var(--data);font-family:'IBM Plex Mono',monospace;font-size:12px;font-weight:600;
    padding:1px 2px;border-radius:0;letter-spacing:.02em;
  }
  .carname-badge input:focus{outline:none;border-bottom-color:var(--accent);box-shadow:none;}
  .carname-badge input::placeholder{color:var(--faint);font-weight:400;letter-spacing:.04em;}

  /* Karte */
  .mapbar{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:12px;}
  .mapbar .mchk{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--dim);letter-spacing:.04em;text-transform:uppercase;cursor:pointer;}
  .mapbar .mchk input{width:auto;}
  .mapbar .mrange{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim);letter-spacing:.04em;text-transform:uppercase;}
  .mapbar .mrange input[type=range]{width:140px;}
  .mapbar .mhint{font-size:12px;color:var(--dim);margin-left:auto;}
  .mapbar .mhint b{color:var(--data);}
  .mapcanvaswrap{position:relative;width:100%;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#0d0f13;}
  #map{display:block;width:100%;height:auto;}
  .mapwait{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--faint);font-size:14px;letter-spacing:.04em;pointer-events:none;}
  .mapwait.hide{display:none;}
  details.mapimg{margin-top:12px;}
  .mapimgrow{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:10px;}
  .mapimgrow input[type=number]{width:90px;}
  .mapimgrow input[type=file]{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--dim);max-width:100%;}
  .tbtn.mapload{border-color:var(--data);color:var(--data);}
  .tbtn.mapload:hover{background:var(--data);color:#06231f;box-shadow:0 0 16px rgba(31,227,198,.35);}
  .mapimgrow .mrange{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim);letter-spacing:.04em;text-transform:uppercase;}
  .mapimgrow .mrange input[type=range]{width:120px;}

  /* Schaltpunkt */
  .shiftnow{display:none;margin-left:10px;font-family:'Chakra Petch',sans-serif;font-weight:700;font-size:13px;
    letter-spacing:.14em;color:#fff;background:var(--accent);padding:2px 10px;border-radius:6px;vertical-align:middle;
    box-shadow:0 0 16px rgba(255,51,38,.6);}
  .shiftnow.on{display:inline-block;}
  .shiftnow.blink{animation:shiftblink .12s steps(2) infinite;}
  @keyframes shiftblink{0%{opacity:1;}100%{opacity:.25;}}
  .shiftmark{position:absolute;top:-2px;bottom:-2px;width:3px;background:#fff;box-shadow:0 0 8px #fff;left:95%;opacity:.85;}
  .shiftrow{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:4px 0 2px;}
  .shiftrow .mrange{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--dim);letter-spacing:.1em;text-transform:uppercase;}
  .shiftrow .mrange input[type=range]{width:120px;}
  .shifthint{font-size:11px;color:var(--dim);letter-spacing:.04em;}
  .shifthint b{color:var(--data);}

  /* Rennen-Tab */
  .racehead{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:8px;}
  .racestatus{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);font-weight:600;display:flex;align-items:center;gap:8px;}
  .racestatus.active{color:var(--good);}
  .racestatus.active::before{content:"";width:9px;height:9px;border-radius:50%;background:var(--good);box-shadow:0 0 10px var(--good);}
  .racestatus.frozen::before{content:"";width:9px;height:9px;border-radius:50%;background:var(--warn);}
  .racecar{font-size:16px;font-weight:600;letter-spacing:.02em;color:var(--txt);margin-bottom:12px;}
  .racecar small{color:var(--dim);font-weight:400;}
</style>
</head>
<body class="mode-analog">
<div class="wrap">

  <div class="top">
    <div class="logo"><span class="ap">APEX</span> LIVE<small>FH6 TELEMETRY</small></div>
    <div class="conn"><span class="dot" id="dot"></span><span id="connTxt">warte auf Daten…</span></div>
    <div class="spacer"></div>
    <div class="badges">
      <span class="badge carname-badge" title="Fahrzeug-ID aus dem Stream; Name selbst vergeben — wird pro Auto gemerkt">
        <span id="carOrd" class="ord">#–</span>
        <input id="carName" placeholder="Modell benennen…" autocomplete="off" spellcheck="false">
      </span>
      <span class="badge">Klasse <b id="bClass">–</b></span>
      <span class="badge">PI <b id="bPI">–</b></span>
      <span class="badge" id="bDT">–</span>
    </div>
    <button class="tbtn on" id="toggleSpeedo">Tacho: Analog</button>
    <button class="tbtn" id="toggleTemp">°C</button>
  </div>

  <!-- HERO -->
  <div class="hero">
    <div class="card speedo">
      <canvas id="gauge" width="536" height="536"></canvas>
      <div class="digi"><div class="big mono" id="digiSpeed">0</div><div class="unit">km/h</div></div>
    </div>

    <div class="card rpmwrap">
      <div class="rpmtop">
        <div class="gear mono" id="gear">N</div>
        <div class="gearstat">
          <div class="rpmnum mono"><span id="rpm">0</span> <small>/ <span id="rpmMax">0</span> RPM</small>
            <span class="shiftnow" id="shiftNow">SCHALTEN</span>
          </div>
          <div class="shift" id="shift">
            <span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span>
          </div>
        </div>
      </div>
      <div class="rpmbar"><div class="rpmfill" id="rpmfill"></div><div class="shiftmark" id="shiftMark"></div></div>
      <div class="shiftrow">
        <label class="mrange">Schaltpunkt <input type="range" id="shiftPct" min="80" max="100" step="1" value="95"></label>
        <span class="shifthint">bei <b id="shiftRpm" class="mono">–</b> RPM · Peak-Power @ <b id="peakRpm" class="mono">–</b></span>
      </div>
      <div class="quick">
        <div class="q"><div class="l">Leistung</div><div class="v"><span id="ps">0</span> PS</div></div>
        <div class="q"><div class="l">Drehmoment</div><div class="v"><span id="nm">0</span> Nm</div></div>
        <div class="q"><div class="l">Boost</div><div class="v"><span id="boost">0.0</span></div></div>
        <div class="q"><div class="l">Tempo</div><div class="v"><span id="kmh">0</span></div></div>
      </div>
    </div>
  </div>

  <!-- TABS -->
  <div class="tabs" id="tabs">
    <button class="tbtn on" data-tab="tires">Reifen</button>
    <button class="tbtn" data-tab="chassis">Fahrwerk</button>
    <button class="tbtn" data-tab="inputs">Eingaben</button>
    <button class="tbtn" data-tab="drive">Antrieb</button>
    <button class="tbtn" data-tab="race">Rennen</button>
    <button class="tbtn" data-tab="map">Karte</button>
  </div>

  <!-- REIFEN -->
  <div class="panel on" data-panel="tires">
    <div class="card">
      <div class="ch">Reifen — Temperatur &amp; Grip</div>
      <div class="carview">
        <div class="tire" id="tFL"></div><div class="chassis">Front</div><div class="tire" id="tFR"></div>
        <div class="tire" id="tRL"></div><div class="chassis">Heck</div><div class="tire" id="tRR"></div>
      </div>
      <div class="note">Temperatur als Spielwert (≈ °F, per Schalter °C). Optimal ist grün. Balken = kombinierter Schlupf (rot = Grenzbereich/Durchdrehen). <b style="color:var(--warn)">Tipp:</b> vorne deutlich mehr Schlupf als hinten = Untersteuern.</div>
    </div>
  </div>

  <!-- FAHRWERK -->
  <div class="panel" data-panel="chassis">
    <div class="grid2">
      <div class="card">
        <div class="ch">G-Kräfte</div>
        <div class="gbox">
          <canvas id="gforce" width="400" height="400"></canvas>
          <div class="gnums">
            <div><div class="l">Längs</div><div class="v"><span id="gLong">0.00</span> g</div></div>
            <div><div class="l">Quer</div><div class="v"><span id="gLat">0.00</span> g</div></div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="ch">Federweg (normalisiert)</div>
        <div class="susp">
          <div class="scorner" id="sFL"></div><div class="scorner" id="sFR"></div>
          <div class="scorner" id="sRL"></div><div class="scorner" id="sRR"></div>
        </div>
        <div class="note">Voller Ausschlag (100 %) = Federung schlägt durch → höher legen oder Federn härter.</div>
      </div>
    </div>
  </div>

  <!-- EINGABEN -->
  <div class="panel" data-panel="inputs">
    <div class="card">
      <div class="ch">Fahrer-Eingaben</div>
      <div class="inbars">
        <div class="ibar"><div class="col"><i id="iThrottle" style="background:var(--good)"></i></div><div class="lab">Gas</div></div>
        <div class="ibar"><div class="col"><i id="iBrake" style="background:var(--accent)"></i></div><div class="lab">Bremse</div></div>
        <div class="ibar"><div class="col"><i id="iClutch" style="background:var(--data)"></i></div><div class="lab">Kupplung</div></div>
        <div class="ibar"><div class="col"><i id="iHand" style="background:var(--warn)"></i></div><div class="lab">Handbremse</div></div>
      </div>
      <div class="steerwrap">
        <div class="ch" style="margin-bottom:8px">Lenkung</div>
        <div class="steerbar"><div class="steercenter"></div><div class="steerknob" id="steerKnob"></div></div>
      </div>
    </div>
  </div>

  <!-- ANTRIEB -->
  <div class="panel" data-panel="drive">
    <div class="grid2">
      <div class="card">
        <div class="ch">Motor</div>
        <div class="kv"><span class="k">Drehzahl</span><span class="v"><span id="dRpm">0</span> RPM</span></div>
        <div class="kv"><span class="k">Leerlauf / Limit</span><span class="v"><span id="dIdle">0</span> / <span id="dMax">0</span></span></div>
        <div class="kv"><span class="k">Leistung</span><span class="v"><span id="dPs">0</span> PS</span></div>
        <div class="kv"><span class="k">Drehmoment</span><span class="v"><span id="dNm">0</span> Nm</span></div>
        <div class="kv"><span class="k">Boost</span><span class="v"><span id="dBoost">0.0</span></span></div>
      </div>
      <div class="card">
        <div class="ch">Fahrzeug</div>
        <div class="kv"><span class="k">Geschwindigkeit</span><span class="v"><span id="dKmh">0</span> km/h</span></div>
        <div class="kv"><span class="k">Gang</span><span class="v" id="dGear">N</span></div>
        <div class="kv"><span class="k">Antrieb</span><span class="v" id="dDT">–</span></div>
        <div class="kv"><span class="k">Zylinder</span><span class="v" id="dCyl">–</span></div>
        <div class="kv"><span class="k">Klasse / PI</span><span class="v"><span id="dClass">–</span> / <span id="dPI">–</span></span></div>
      </div>
    </div>
  </div>

  <!-- RENNEN -->
  <div class="panel" data-panel="race">
    <div class="racehead">
      <span class="racestatus" id="rStatus">Noch kein Rennen erfasst</span>
      <button class="tbtn" id="rDownload">Als TXT speichern</button>
    </div>
    <div class="racecar" id="rCar">–</div>
    <div class="grid4">
      <div class="card"><div class="ch">Runde</div><div class="v mono" style="font-size:28px" id="rLap">–</div></div>
      <div class="card"><div class="ch">Position</div><div class="v mono" style="font-size:28px" id="rPos">–</div></div>
      <div class="card"><div class="ch">Distanz</div><div class="v mono" style="font-size:28px" id="rDist">0.0 km</div></div>
      <div class="card"><div class="ch">Tank</div><div class="v mono" style="font-size:28px" id="rFuel">– %</div></div>
    </div>
    <div class="grid4" style="margin-top:12px">
      <div class="card"><div class="ch">Aktuell</div><div class="v mono" style="font-size:24px" id="rCur">--:--</div></div>
      <div class="card"><div class="ch">Letzte</div><div class="v mono" style="font-size:24px" id="rLast">--:--</div></div>
      <div class="card"><div class="ch">Beste</div><div class="v mono" style="font-size:24px;color:var(--good)" id="rBest">--:--</div></div>
      <div class="card"><div class="ch">Rennzeit</div><div class="v mono" style="font-size:24px" id="rTime">--:--</div></div>
    </div>
    <div class="grid4" style="margin-top:12px">
      <div class="card"><div class="ch">Topspeed</div><div class="v mono" style="font-size:24px" id="rTop">– km/h</div></div>
      <div class="card"><div class="ch">Max. Quer-G</div><div class="v mono" style="font-size:24px" id="rMaxG">– g</div></div>
      <div class="card"><div class="ch">Max. Drehzahl</div><div class="v mono" style="font-size:24px" id="rMaxRpm">– RPM</div></div>
      <div class="card"><div class="ch">Erfasst</div><div class="v mono" style="font-size:16px" id="rWhen">–</div></div>
    </div>
    <div class="note">Das angezeigte Rennen bleibt eingefroren, bis ein neues Rennen startet. „Als TXT speichern" lädt eine Ergebnis-Datei zum Teilen herunter. Erkennung über das Renn-Flag des Spiels — am besten direkt nach Rennende speichern.</div>
  </div>

  <!-- KARTE -->
  <div class="panel" data-panel="map">
    <div class="card">
      <div class="ch">Karte — gefahrene Strecke (Live)</div>
      <div class="mapbar">
        <button class="tbtn mapload" id="mLoadBtn">📁 Karte hochladen</button>
        <input type="file" id="mFile" accept="image/*" hidden>
        <label class="mchk"><input type="checkbox" id="mFollow" checked> Auto folgen</label>
        <label class="mrange">Zoom <input type="range" id="mZoom" min="0.05" max="2.5" step="0.01" value="0.35"></label>
        <button class="tbtn" id="mClear">Spur löschen</button>
        <span class="mhint">Höhe: <b id="mAlt" class="mono">–</b> m</span>
      </div>
      <div class="mapcanvaswrap">
        <canvas id="map" width="1040" height="560"></canvas>
        <div class="mapwait" id="mapWait">Lade eine Karte hoch oder fahr los — die Strecke zeichnet sich live.</div>
      </div>
      <details class="adv mapimg">
        <summary>Kartenbild ausrichten (Deckkraft, Maßstab, Versatz)</summary>
        <div class="mapimgrow">
          <button class="tbtn" id="mImgCenter">Bild auf Auto zentrieren</button>
          <button class="tbtn" id="mImgClear">Bild entfernen</button>
        </div>
        <div class="mapimgrow">
          <label class="mrange">Deckkraft <input type="range" id="mOpac" min="0" max="1" step="0.02" value="0.55"></label>
          <label class="mrange">Maßstab (m/Pixel) <input type="number" id="mMpp" value="1.0" min="0.05" max="50" step="0.05"></label>
        </div>
        <div class="mapimgrow">
          <label class="mrange">Versatz Ost (X) <input type="number" id="mImgX" value="0" step="5"></label>
          <label class="mrange">Versatz Nord (Z) <input type="number" id="mImgZ" value="0" step="5"></label>
        </div>
        <div class="mhint">Screenshot deiner In-Game-Karte: Maßstab und Versatz justieren, bis die Straßen auf deiner gefahrenen Spur liegen. Bild und Einstellungen bleiben nur lokal im Browser gespeichert.</div>
      </details>
      <div class="note">Spur färbt sich nach Tempo (grün langsam → rot schnell). Bei Schnellreise/Pause beginnt automatisch ein neuer Abschnitt, damit keine Linie quer über die Karte gezogen wird.</div>
    </div>
  </div>

</div>

<script>
"use strict";
// ---- Zustand ----
let T = null;
let tempUnit = "C";   // C | F
let live = false;
let lastGear = null;  // zuletzt gueltiger Gang (haelt waehrend des Schaltvorgangs)
const FRESH_S = 1.5;  // Pakete gelten so lange als "live" (Sekunden)

// ---- SSE ----
const es = new EventSource("/stream");
es.onmessage = (e) => { try { T = JSON.parse(e.data); } catch (_) {} };

// ---- Helpers ----
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 0) => (n == null || isNaN(n)) ? "–" : Number(n).toFixed(d);
function lapFmt(s) {
  if (s == null || s <= 0 || isNaN(s)) return "--:--";
  const m = Math.floor(s / 60), r = (s - m * 60);
  return m + ":" + r.toFixed(3).padStart(6, "0");
}
function tempColor(f) {                 // Schwellen in °F
  if (f == null || isNaN(f)) return "var(--faint)";
  if (f < 140) return "var(--cold)";
  if (f < 210) return "var(--good)";
  if (f < 255) return "var(--warn)";
  return "var(--accent)";
}
function showTemp(f) {
  if (f == null || isNaN(f)) return "–";
  return tempUnit === "C" ? ((f - 32) * 5 / 9).toFixed(0) + "°C" : f.toFixed(0) + "°F";
}

// ---- Toggles ----
$("toggleSpeedo").addEventListener("click", () => {
  const analog = document.body.classList.toggle("mode-digi");
  $("toggleSpeedo").textContent = "Tacho: " + (analog ? "Digital" : "Analog");
  $("toggleSpeedo").classList.toggle("on");
});
$("toggleTemp").addEventListener("click", () => {
  tempUnit = tempUnit === "C" ? "F" : "C";
  $("toggleTemp").textContent = tempUnit === "C" ? "°C" : "°F";
});
let currentTab = "tires";
$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tab]"); if (!b) return;
  document.querySelectorAll("#tabs .tbtn").forEach(x => x.classList.remove("on"));
  b.classList.add("on");
  currentTab = b.dataset.tab;
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("on", p.dataset.panel === currentTab));
});

// ---- localStorage (sicher gekapselt; faellt geraeuschlos aus, wenn nicht verfuegbar) ----
function lsGet(k){ try { return localStorage.getItem(k); } catch(e){ return null; } }
function lsSet(k,v){ try { localStorage.setItem(k,v); } catch(e){} }
function lsDel(k){ try { localStorage.removeItem(k); } catch(e){} }

// ---- Auto-Modellname: lernt den Namen pro Fahrzeug-ID ----
let curOrdinal = null;
const carNameInput = $("carName");
carNameInput.addEventListener("input", () => {
  if (curOrdinal == null) return;
  const v = carNameInput.value.trim();
  if (v) lsSet("carname:" + curOrdinal, v); else lsDel("carname:" + curOrdinal);
});
function updateCarName(ord) {
  if (ord == null || ord === 0 || ord === curOrdinal) return;
  curOrdinal = ord;
  $("carOrd").textContent = "#" + ord;
  peakPower = 0; peakPowerRpm = 0;     // Peak-Power-Lernen fuer neues Auto zuruecksetzen
  if (document.activeElement !== carNameInput) {
    carNameInput.value = lsGet("carname:" + ord) || "";
  }
}

// ---- Schaltpunkt-Lernen + Regler ----
let peakPower = 0, peakPowerRpm = 0;
let shiftPct = 95;
(function(){ const s = lsGet("shiftpct"); if (s){ shiftPct = parseInt(s)||95; $("shiftPct").value = shiftPct; } })();
$("shiftPct").addEventListener("input", e => { shiftPct = parseInt(e.target.value)||95; lsSet("shiftpct", shiftPct); });

// ---- Rennen erfassen, einfrieren, exportieren ----
const CLS = {0:"D",1:"C",2:"B",3:"A",4:"S1",5:"S2",6:"X"};
const DT  = {0:"FWD",1:"RWD",2:"AWD"};
let raceActive = false;
let race = null;                         // aktueller / letzter Renn-Snapshot (eingefroren bis neues Rennen)
function blankRace(){
  return { startedAt:Date.now(), car:"", ord:null, cls:"–", pi:"–", dt:"–",
           lap:0, pos:0, distance:0, fuel:1, bestLap:0, lastLap:0, curLap:0, raceTime:0,
           topSpeed:0, maxLatG:0, maxRpm:0, _lastRt:0 };
}
function updateRace(d, fresh){
  const inRace = fresh && d && d.isRaceOn === 1;
  const rt = (d && d.raceTime != null) ? d.raceTime : 0;
  if (inRace){
    const reset = race && (rt + 1.5 < race._lastRt);   // Rennzeit sprang zurueck -> neues/neugestartetes Rennen
    if (!raceActive || reset || !race){ race = blankRace(); }
    raceActive = true;
    const kmh = (d.speed||0)*3.6;
    race.topSpeed = Math.max(race.topSpeed, kmh);
    race.maxLatG  = Math.max(race.maxLatG, Math.abs((d.accelX||0)/9.80665));
    race.maxRpm   = Math.max(race.maxRpm, d.rpm||0);
    race.lap      = Math.max(race.lap, d.lap||0);
    race.raceTime = Math.max(race.raceTime, rt);
    race.distance = Math.max(race.distance, d.distance||0);
    if (d.pos) race.pos = d.pos;
    if (d.bestLap) race.bestLap = d.bestLap;
    if (d.lastLap) race.lastLap = d.lastLap;
    race.curLap = d.curLap || 0;
    if (d.fuel != null) race.fuel = d.fuel;
    race.ord = curOrdinal;
    race.car = (carNameInput.value.trim()) || (curOrdinal ? ("#"+curOrdinal) : "—");
    race.cls = CLS[d.carClass] ?? "–"; race.pi = d.pi || "–"; race.dt = DT[d.drivetrain] ?? "–";
    race._lastRt = rt;
  } else if (raceActive){
    raceActive = false;                  // Rennen endet -> Snapshot bleibt stehen
  }
  renderRaceTab();
}
function renderRaceTab(){
  const st = $("rStatus");
  if (!race){ st.className = "racestatus"; st.textContent = "Noch kein Rennen erfasst"; return; }
  if (raceActive){ st.className = "racestatus active"; st.textContent = "Aktuelles Rennen läuft"; }
  else { st.className = "racestatus frozen"; st.textContent = "Letztes Rennen (eingefroren)"; }
  $("rCar").innerHTML = race.car + ` <small>· Klasse ${race.cls} · PI ${race.pi} · ${race.dt}</small>`;
  $("rLap").textContent  = (race.lap + 1);
  $("rPos").textContent  = race.pos ? ("P" + race.pos) : "–";
  $("rDist").textContent = (race.distance/1000).toFixed(2) + " km";
  $("rFuel").textContent = Math.round(race.fuel*100) + " %";
  $("rCur").textContent  = lapFmt(race.curLap);
  $("rLast").textContent = lapFmt(race.lastLap);
  $("rBest").textContent = lapFmt(race.bestLap);
  $("rTime").textContent = lapFmt(race.raceTime);
  $("rTop").textContent    = Math.round(race.topSpeed) + " km/h";
  $("rMaxG").textContent   = race.maxLatG.toFixed(2) + " g";
  $("rMaxRpm").textContent = Math.round(race.maxRpm) + " RPM";
  const dt = new Date(race.startedAt);
  $("rWhen").textContent = dt.toLocaleDateString() + " " + dt.toLocaleTimeString().slice(0,5);
}
function raceToText(){
  if (!race) return "Noch kein Rennen erfasst.";
  const pad = s => String(s).padEnd(16);
  const L = [];
  L.push("=== APEX LIVE · Forza Horizon 6 — Rennergebnis ===");
  L.push("Datum:   " + new Date(race.startedAt).toLocaleString());
  L.push("Auto:    " + race.car + "  (Klasse " + race.cls + " · PI " + race.pi + " · " + race.dt + ")");
  L.push("");
  L.push(pad("Runden:")        + (race.lap + 1));
  L.push(pad("Beste Runde:")   + lapFmt(race.bestLap));
  L.push(pad("Letzte Runde:")  + lapFmt(race.lastLap));
  L.push(pad("Rennzeit:")      + lapFmt(race.raceTime));
  L.push(pad("Position:")      + (race.pos ? "P" + race.pos : "—"));
  L.push(pad("Distanz:")       + (race.distance/1000).toFixed(2) + " km");
  L.push("");
  L.push(pad("Topspeed:")      + Math.round(race.topSpeed) + " km/h");
  L.push(pad("Max. Quer-G:")   + race.maxLatG.toFixed(2) + " g");
  L.push(pad("Max. Drehzahl:") + Math.round(race.maxRpm) + " RPM");
  L.push("");
  L.push("— erstellt mit APEX LIVE (FH6 Telemetrie)");
  return L.join("\n");
}
$("rDownload").addEventListener("click", () => {
  if (!race) return;
  try {
    const blob = new Blob([raceToText()], {type:"text/plain;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const stamp = new Date(race.startedAt).toISOString().slice(0,16).replace(/[:T]/g,"-");
    a.href = url; a.download = "apex-rennen-" + stamp + ".txt";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch(e){ /* in eingeschraenkten Umgebungen evtl. nicht verfuegbar */ }
});

// ---- Karte ----
const mapCv = $("map");
const mc = mapCv.getContext("2d");
const view = { cx:0, cz:0, zoom:0.35, follow:true, haveData:false };
let segments = [];          // Liste von Abschnitten; jeder Abschnitt = Liste von {x,z,spd}
let curSeg = null, lastPt = null, wasFresh = 0, totalPoints = 0;
const MAX_POINTS = 20000;
const mapImg = { el:null, opacity:0.55, mpp:1.0, x:0, z:0 };

function speedColor(kmh){
  const t = Math.max(0, Math.min(1, kmh/300));
  let r,g,b;
  if (t < 0.5){ const u=t/0.5; r=70+(255-70)*u; g=209+(176-209)*u; b=123+(32-123)*u; }
  else { const u=(t-0.5)/0.5; r=255; g=176+(51-176)*u; b=32+(38-32)*u; }
  return `rgb(${r|0},${g|0},${b|0})`;
}
const BUCKETS = 12;
const bucketColor = Array.from({length:BUCKETS}, (_,i)=>speedColor(i*25+12));
function bucket(kmh){ return Math.min(BUCKETS-1, Math.max(0, Math.floor((kmh||0)/25))); }

function newSegment(){
  curSeg = []; segments.push(curSeg);
  while (segments.length > 250){ totalPoints -= segments.shift().length; }
  if (totalPoints < 0) totalPoints = 0;
}

function mapAddPoint(d){
  const freshNow = !!d && d._age != null && d._age < FRESH_S;
  if (!freshNow){ wasFresh = 0; return; }      // Pakete pausiert (Menü/Pause) -> Abschnitt endet
  const x = d.posX||0, z = d.posZ||0, spd = (d.speed||0)*3.6;
  view.haveData = true;
  let jump = false;
  if (lastPt){ const dx=x-lastPt.x, dz=z-lastPt.z; jump = (dx*dx+dz*dz) > (200*200); }
  if (!curSeg || wasFresh !== 1 || jump){ newSegment(); lastPt = null; }  // neuer Abschnitt nach Pause/Sprung
  if (!lastPt || ((x-lastPt.x)**2 + (z-lastPt.z)**2) > 4){   // Punkt erst ab ~2 m Abstand
    curSeg.push({x,z,spd}); lastPt = {x,z}; totalPoints++;
    if (totalPoints > MAX_POINTS && segments.length > 1){ totalPoints -= segments[0].length; segments.shift(); }
  }
  wasFresh = 1;
}

function mapResize(){
  const dpr = window.devicePixelRatio || 1;
  const wCss = mapCv.clientWidth || 0;
  const hCss = Math.round(wCss * 560/1040);
  if (wCss > 0 && (mapCv.width !== Math.round(wCss*dpr) || mapCv.height !== Math.round(hCss*dpr))){
    mapCv.width = Math.round(wCss*dpr); mapCv.height = Math.round(hCss*dpr);
  }
  return {dpr, W:wCss, H:hCss};
}
function w2s(wx,wz,W,H){ return [ (wx-view.cx)*view.zoom + W/2, -(wz-view.cz)*view.zoom + H/2 ]; }

function drawMap(d){
  if (mapCv.clientWidth <= 0) return;                 // Tab nicht sichtbar
  const {dpr,W,H} = mapResize();
  const fresh = !!d && d._age != null && d._age < FRESH_S;
  mc.setTransform(dpr,0,0,dpr,0,0);
  mc.clearRect(0,0,W,H);
  if (view.follow && fresh){ view.cx = d.posX||0; view.cz = d.posZ||0; }

  if (mapImg.el){
    const [ix,iy] = w2s(mapImg.x, mapImg.z, W, H);
    const iw = mapImg.el.naturalWidth  * mapImg.mpp * view.zoom;
    const ih = mapImg.el.naturalHeight * mapImg.mpp * view.zoom;
    mc.globalAlpha = mapImg.opacity; mc.drawImage(mapImg.el, ix, iy, iw, ih); mc.globalAlpha = 1;
  }

  mc.lineWidth = 2.5; mc.lineJoin = "round"; mc.lineCap = "round";
  for (const seg of segments){
    if (seg.length < 2) continue;
    let curB = bucket(seg[0].spd);
    mc.strokeStyle = bucketColor[curB];
    mc.beginPath();
    let p = w2s(seg[0].x, seg[0].z, W, H); mc.moveTo(p[0], p[1]);
    for (let i=1;i<seg.length;i++){
      const b = bucket(seg[i].spd);
      p = w2s(seg[i].x, seg[i].z, W, H);
      mc.lineTo(p[0], p[1]);
      if (b !== curB){ mc.stroke(); mc.beginPath(); mc.moveTo(p[0], p[1]); curB = b; mc.strokeStyle = bucketColor[curB]; }
    }
    mc.stroke();
  }

  if (fresh){
    const p = w2s(d.posX||0, d.posZ||0, W, H);
    mc.fillStyle = "#fff"; mc.beginPath(); mc.arc(p[0], p[1], 5, 0, 7); mc.fill();
    mc.lineWidth = 2; mc.strokeStyle = "#FF3326"; mc.beginPath(); mc.arc(p[0], p[1], 8.5, 0, 7); mc.stroke();
  }
  $("mapWait").classList.toggle("hide", view.haveData || !!mapImg.el);
}

// Karten-Bedienelemente
$("mFollow").addEventListener("change", e => view.follow = e.target.checked);
$("mZoom").addEventListener("input", e => view.zoom = parseFloat(e.target.value) || 0.35);
$("mClear").addEventListener("click", () => { segments = []; curSeg = null; lastPt = null; totalPoints = 0; view.haveData = false; });
function saveImgCfg(){ lsSet("mapimgcfg", JSON.stringify({opacity:mapImg.opacity, mpp:mapImg.mpp, x:mapImg.x, z:mapImg.z})); }
$("mOpac").addEventListener("input", e => { mapImg.opacity = parseFloat(e.target.value); saveImgCfg(); });
$("mMpp").addEventListener("input",  e => { mapImg.mpp = parseFloat(e.target.value) || 1; saveImgCfg(); });
$("mImgX").addEventListener("input", e => { mapImg.x = parseFloat(e.target.value) || 0; saveImgCfg(); });
$("mImgZ").addEventListener("input", e => { mapImg.z = parseFloat(e.target.value) || 0; saveImgCfg(); });
$("mImgCenter").addEventListener("click", () => {
  if (T && T._age != null && T._age < FRESH_S && mapImg.el){
    mapImg.x = (T.posX||0) - mapImg.el.naturalWidth  * mapImg.mpp / 2;
    mapImg.z = (T.posZ||0) + mapImg.el.naturalHeight * mapImg.mpp / 2;
    $("mImgX").value = Math.round(mapImg.x); $("mImgZ").value = Math.round(mapImg.z); saveImgCfg();
  }
});
$("mImgClear").addEventListener("click", () => { mapImg.el = null; lsDel("mapimgdata"); $("mFile").value = ""; });
$("mLoadBtn").addEventListener("click", () => $("mFile").click());
$("mFile").addEventListener("change", e => {
  const f = e.target.files && e.target.files[0]; if (!f) return;
  const rd = new FileReader();
  rd.onload = () => {
    const im = new Image();
    im.onload = () => { mapImg.el = im; try { if (rd.result.length < 4*1024*1024) lsSet("mapimgdata", rd.result); } catch(_){} };
    im.src = rd.result;
  };
  rd.readAsDataURL(f);
});
// persistierte Bild-Einstellungen + Bild laden
(function loadImgCfg(){
  try {
    const raw = lsGet("mapimgcfg");
    if (raw){ const c = JSON.parse(raw); mapImg.opacity=c.opacity??0.55; mapImg.mpp=c.mpp??1; mapImg.x=c.x??0; mapImg.z=c.z??0;
      $("mOpac").value=mapImg.opacity; $("mMpp").value=mapImg.mpp; $("mImgX").value=mapImg.x; $("mImgZ").value=mapImg.z; }
    const url = lsGet("mapimgdata");
    if (url){ const im = new Image(); im.onload = () => { mapImg.el = im; }; im.src = url; }
  } catch(e){}
})();

// ---- Canvas: analoger Tacho ----
const gc = $("gauge").getContext("2d");
const MAXKMH = 340;
function drawGauge(kmh) {
  const dpr = window.devicePixelRatio || 1, size = 268;
  const cv = $("gauge");
  if (cv.width !== size * dpr) { cv.width = size * dpr; cv.height = size * dpr; cv.style.width = size + "px"; cv.style.height = size + "px"; }
  gc.setTransform(dpr, 0, 0, dpr, 0, 0);
  gc.clearRect(0, 0, size, size);
  const cx = size / 2, cy = size / 2, R = size / 2 - 14;
  const a0 = Math.PI * 0.75, a1 = Math.PI * 2.25;   // -135° .. +135°
  // Skala-Hintergrund
  gc.lineWidth = 12; gc.strokeStyle = "#1B1E24"; gc.lineCap = "round";
  gc.beginPath(); gc.arc(cx, cy, R, a0, a1); gc.stroke();
  // gefüllter Bogen
  const frac = Math.max(0, Math.min(1, kmh / MAXKMH));
  const ae = a0 + (a1 - a0) * frac;
  const grad = gc.createLinearGradient(0, 0, size, size);
  grad.addColorStop(0, "#1FE3C6"); grad.addColorStop(.8, "#1FE3C6"); grad.addColorStop(1, "#FF3326");
  gc.strokeStyle = grad; gc.lineWidth = 12;
  gc.beginPath(); gc.arc(cx, cy, R, a0, ae); gc.stroke();
  // Ticks + Labels
  gc.fillStyle = "#8A8F99"; gc.font = "11px 'IBM Plex Mono'"; gc.textAlign = "center"; gc.textBaseline = "middle";
  for (let v = 0; v <= MAXKMH; v += 20) {
    const a = a0 + (a1 - a0) * (v / MAXKMH);
    const big = v % 40 === 0;
    const r1 = R - 18, r2 = R - (big ? 30 : 25);
    gc.strokeStyle = big ? "#5A5F6A" : "#33373F"; gc.lineWidth = big ? 2 : 1;
    gc.beginPath();
    gc.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
    gc.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2);
    gc.stroke();
    if (big && v % 40 === 0) {
      const rl = R - 44;
      gc.fillText(v, cx + Math.cos(a) * rl, cy + Math.sin(a) * rl);
    }
  }
  // Nadel
  const na = a0 + (a1 - a0) * frac;
  gc.strokeStyle = "#FF3326"; gc.lineWidth = 3; gc.lineCap = "round";
  gc.beginPath(); gc.moveTo(cx - Math.cos(na) * 16, cy - Math.sin(na) * 16);
  gc.lineTo(cx + Math.cos(na) * (R - 22), cy + Math.sin(na) * (R - 22)); gc.stroke();
  gc.fillStyle = "#FF3326"; gc.beginPath(); gc.arc(cx, cy, 7, 0, 7); gc.fill();
  // Zentral-Zahl
  gc.fillStyle = "#E7E9EC"; gc.textAlign = "center";
  gc.font = "600 46px 'IBM Plex Mono'";
  gc.fillText(Math.round(kmh), cx, cy + 40);
  gc.fillStyle = "#8A8F99"; gc.font = "11px 'IBM Plex Mono'";
  gc.fillText("km/h", cx, cy + 66);
}

// ---- Canvas: G-Kraft-Diagramm ----
const fgc = $("gforce").getContext("2d");
function drawG(lat, lon) {
  const dpr = window.devicePixelRatio || 1, size = 200, cv = $("gforce");
  if (cv.width !== size * dpr) { cv.width = size * dpr; cv.height = size * dpr; cv.style.width = size + "px"; cv.style.height = size + "px"; }
  fgc.setTransform(dpr, 0, 0, dpr, 0, 0);
  fgc.clearRect(0, 0, size, size);
  const cx = size / 2, cy = size / 2, R = size / 2 - 10, SCALE = 2.0; // ±2g voller Ausschlag
  fgc.strokeStyle = "#23262E"; fgc.lineWidth = 1;
  for (const rr of [R, R * 0.66, R * 0.33]) { fgc.beginPath(); fgc.arc(cx, cy, rr, 0, 7); fgc.stroke(); }
  fgc.beginPath(); fgc.moveTo(cx - R, cy); fgc.lineTo(cx + R, cy); fgc.moveTo(cx, cy - R); fgc.lineTo(cx, cy + R); fgc.stroke();
  const px = cx + Math.max(-1, Math.min(1, lat / SCALE)) * R;
  const py = cy - Math.max(-1, Math.min(1, lon / SCALE)) * R;  // +Längs (Beschl.) nach oben
  fgc.fillStyle = "#1FE3C6"; fgc.shadowColor = "#1FE3C6"; fgc.shadowBlur = 12;
  fgc.beginPath(); fgc.arc(px, py, 7, 0, 7); fgc.fill(); fgc.shadowBlur = 0;
}

// ---- Tile-Builder ----
function tireHTML(t) {
  const f = t.temp, comb = Math.min(1, Math.abs(t.comb || 0));
  return `<div class="pos">${t.pos}</div>
    <div class="tmp" style="color:${tempColor(f)}">${showTemp(f)}</div>
    <div class="sl">Schlupf ${fmt(t.slip,2)}</div>
    <div class="bar"><i style="width:${(comb*100).toFixed(0)}%;background:${comb>0.9?'var(--accent)':comb>0.6?'var(--warn)':'var(--good)'}"></i></div>`;
}
function suspHTML(pos, val) {
  const p = Math.max(0, Math.min(1, val || 0)) * 100;
  return `<div class="pos">${pos}</div><div class="track"><i style="height:${p.toFixed(0)}%"></i></div><div class="pct">${p.toFixed(0)} %</div>`;
}

// ---- Render-Loop ----
function render() {
  const d = T;
  const fresh = !!d && d._age != null && d._age < FRESH_S;
  live = fresh;

  // Verbindungsstatus — an frischen Paketen festgemacht, nicht an isRaceOn
  // (das Spiel sendet nur beim Fahren; frische Pakete = du fährst)
  const dot = $("dot");
  if (fresh) {
    dot.className = "dot on"; $("connTxt").textContent = "live";
  } else {
    dot.className = "dot"; $("connTxt").textContent = "warte auf Daten…";
  }

  if (d) {
    const kmh = (d.speed || 0) * 3.6;
    const ps = (d.power || 0) / 735.499;
    const rpm = d.rpm || 0, rpmMax = d.rpmMax || 1;
    // Gang: 0=R, 1..10 Vorwaertsgaenge. Werte >10 (z.B. 11/255) sendet das Spiel
    // waehrend des Schaltvorgangs (kein Gang eingelegt) -> letzten echten Gang halten.
    if (d.gear != null && d.gear >= 0 && d.gear <= 10) lastGear = d.gear;
    const gearVal = lastGear;
    const gearTxt = (gearVal == null) ? "N" : (gearVal === 0 ? "R" : gearVal);

    // Tacho
    drawGauge(kmh);
    $("digiSpeed").textContent = Math.round(kmh);

    // RPM / Gang
    $("rpm").textContent = Math.round(rpm);
    $("rpmMax").textContent = Math.round(rpmMax);
    $("gear").textContent = gearTxt;

    // Peak-Power lernen (pro Auto): hoechste beobachtete Leistung + zugehoerige Drehzahl
    if (fresh && gearVal > 0 && (d.power||0) > peakPower && rpm > rpmMax*0.3){
      peakPower = d.power; peakPowerRpm = rpm;
    }
    // Schaltpunkt = % des Drehzahllimits (Regler)
    const shiftRpm = rpmMax * (shiftPct/100);
    $("shiftRpm").textContent = Math.round(shiftRpm);
    $("peakRpm").textContent = peakPowerRpm ? Math.round(peakPowerRpm) : "–";
    $("shiftMark").style.left = (shiftPct) + "%";

    // RPM-Balken (relativ zum Limit) + Schaltlichter (relativ zum Schaltpunkt)
    const frac = Math.max(0, Math.min(1, rpm / rpmMax));
    $("rpmfill").style.width = (frac * 100).toFixed(1) + "%";
    const lights = $("shift").children;
    const sFrac = Math.max(0, Math.min(1, rpm / shiftRpm));
    const lit = Math.round(sFrac * lights.length);
    const doShift = fresh && gearVal > 0 && rpm >= shiftRpm;
    for (let i = 0; i < lights.length; i++) {
      const on = i < lit;
      lights[i].style.background = on ? (i >= lights.length - 2 || sFrac > 0.98 ? "var(--accent)" : "var(--data)") : "var(--lineSoft)";
    }
    const sn = $("shiftNow");
    sn.classList.toggle("on", doShift);
    sn.classList.toggle("blink", doShift);

    // Quick-Werte
    $("ps").textContent = Math.round(ps);
    $("nm").textContent = Math.round(d.torque || 0);
    $("boost").textContent = fmt(d.boost, 1);
    $("kmh").textContent = Math.round(kmh);

    // Badges
    updateCarName(d.carOrdinal);
    $("bClass").textContent = ({0:"D",1:"C",2:"B",3:"A",4:"S1",5:"S2",6:"X"})[d.carClass] ?? "–";
    $("bPI").textContent = d.pi || "–";
    $("bDT").textContent = ({0:"FWD",1:"RWD",2:"AWD"})[d.drivetrain] ?? "–";
    $("mAlt").textContent = (d.posY != null) ? Math.round(d.posY) : "–";

    // Reifen
    $("tFL").innerHTML = tireHTML({pos:"V-L",temp:d.tempFL,slip:d.slipFL,comb:d.combFL});
    $("tFR").innerHTML = tireHTML({pos:"V-R",temp:d.tempFR,slip:d.slipFR,comb:d.combFR});
    $("tRL").innerHTML = tireHTML({pos:"H-L",temp:d.tempRL,slip:d.slipRL,comb:d.combRL});
    $("tRR").innerHTML = tireHTML({pos:"H-R",temp:d.tempRR,slip:d.slipRR,comb:d.combRR});

    // Fahrwerk
    const gLat = (d.accelX || 0) / 9.80665, gLon = (d.accelZ || 0) / 9.80665;
    drawG(gLat, gLon);
    $("gLat").textContent = fmt(gLat, 2);
    $("gLong").textContent = fmt(gLon, 2);
    $("sFL").innerHTML = suspHTML("V-L", d.suspFL);
    $("sFR").innerHTML = suspHTML("V-R", d.suspFR);
    $("sRL").innerHTML = suspHTML("H-L", d.suspRL);
    $("sRR").innerHTML = suspHTML("H-R", d.suspRR);

    // Eingaben
    const pct = v => Math.max(0, Math.min(100, (v || 0) / 255 * 100)).toFixed(0) + "%";
    $("iThrottle").style.height = pct(d.accel);
    $("iBrake").style.height = pct(d.brake);
    $("iClutch").style.height = pct(d.clutch);
    $("iHand").style.height = pct(d.hbrake);
    $("steerKnob").style.left = Math.max(0, Math.min(100, 50 + (d.steer || 0) / 127 * 50)) + "%";

    // Antrieb-Tab
    $("dRpm").textContent = Math.round(rpm);
    $("dIdle").textContent = Math.round(d.rpmIdle || 0);
    $("dMax").textContent = Math.round(rpmMax);
    $("dPs").textContent = Math.round(ps);
    $("dNm").textContent = Math.round(d.torque || 0);
    $("dBoost").textContent = fmt(d.boost, 1);
    $("dKmh").textContent = Math.round(kmh);
    $("dGear").textContent = gearTxt;
    $("dDT").textContent = ({0:"FWD",1:"RWD",2:"AWD"})[d.drivetrain] ?? "–";
    $("dCyl").textContent = d.cyl || "–";
    $("dClass").textContent = ({0:"D",1:"C",2:"B",3:"A",4:"S1",5:"S2",6:"X"})[d.carClass] ?? "–";
    $("dPI").textContent = d.pi || "–";
  }

  // Rennen erfassen/einfrieren (eigenes Snapshot-System)
  updateRace(d, fresh);

  // Karte: Punkte immer sammeln (auch auf anderen Tabs), nur bei aktivem Tab zeichnen
  mapAddPoint(d);
  if (currentTab === "map") drawMap(d);

  requestAnimationFrame(render);
}
requestAnimationFrame(render);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
