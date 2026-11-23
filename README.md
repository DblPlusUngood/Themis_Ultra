# Bookoo Themis Ultra & Espresso Monitor – Home Assistant Integration

Home Assistant custom integration for the **Bookoo Themis Ultra** Bluetooth
scale and the **Bookoo Espresso Monitor** pressure sensor. Communication is
local over Bluetooth. The scale uses the bundled `aiobookoo-ultra` library.
The monitor uses Bookoo's published Espresso Monitor protocol.

Existing Themis Ultra config entries keep their entity unique IDs. An
Espresso Monitor is discovered and set up as its own device.

## Themis Ultra features

| Entity | Function | Firmware |
| --- | --- | --- |
| Weight sensor | Live beverage weight in grams | all supported versions |
| Flow rate sensor | Live flow in ml/s | all supported versions |
| Timer sensor | Scale timer in seconds | all supported versions |
| Battery sensor | Remaining battery level | all supported versions |
| Connected binary sensor | Bluetooth connection status | all supported versions |
| Tare / timer buttons | Tare, start, stop, reset, tare and start | all supported versions |
| Auto-off number | Automatic shutdown delay | all supported versions |
| Beeper level select | Beeper level from 0 to 5 | all supported versions |
| Flow smoothing controls | Configure flow-rate smoothing | all supported versions |
| Powder weight number | Read and set `0.1` to `999.0 g` | 4.0.0+ |
| Automatic mode event | Ready, started, stopped, exit ready and exit done | 4.0.0+ |
| Automatic mode sensors | Latest time, weight and result | 4.0.0+ |
| Shut down button | Turn off the scale; unavailable while charging | 4.0.0+ |

The automatic-mode result is the average flow rate in timing mode or the brew
ratio in ratio mode. The scale does not report which of these modes produced
the value, therefore this sensor intentionally has no unit.

Calibration and configuration of the scale's own automatic stop condition are
intentionally not exposed as Home Assistant entities.

## Installation via HACS

1. Open **HACS** and select **Integrations**.
2. Add this repository as a **custom repository**.
3. Install **Bookoo Themis & Espresso Monitor**.
4. Restart Home Assistant.
5. Add the Bookoo integration from **Settings > Devices & services**.

Requirements:

- Home Assistant 2024.1.0 or newer with Bluetooth support
- Bookoo Themis Ultra scale and/or Bookoo Espresso Monitor
- A local Bluetooth adapter or an ESPHome Bluetooth proxy (active connections)

## Espresso Monitor

The monitor is a BLE pressure sensor that sits on an espresso machine. It is
matched by the advertised name `BOOKOO_EM*` (also `BOOKOO ESPRESSO MONITOR`)
or service UUID `00000fff-0000-1000-8000-00805f9b34fb`.

| Entity | Function |
| --- | --- |
| Pressure sensor | Brew pressure in bar, updated at most once per second |
| Battery sensor | Remaining battery percentage |
| Connected binary sensor | Bluetooth connection status |
| Start extraction button | Ask the monitor to stream pressure |
| Stop extraction button | Ask the monitor to stop streaming |

The monitor only notifies after a start-extraction command, so connecting
sends that command. Stop leaves the link up and sends the stop command.
The next reconnect resumes whichever command was used last.

Home Assistant connects only while the scanner's last-seen time for a
connectable advertisement is still recent, including advertisements whose
payload has not changed. It drops the client when the link is lost, and a
connection that finishes during unload is released too. A sleeping monitor
therefore does not hold an ESPHome Bluetooth proxy connection slot. A failed
start or stop command is retried while that link stays up.
Live samples are pushed over GATT; the coordinator does not poll pressure.

Protocol source:
[BooKooCode/OpenSource – Espresso Monitor protocol](https://github.com/BooKooCode/OpenSource/blob/main/espresso_monitor/protocols.md)

Pressure is protocol bytes 5 and 6 of an `02 1B` notification (the fifth and
sixth bytes, indexes 4 and 5), as a big-endian unsigned 16-bit value of
bar × 100. Byte 7 is the battery percentage.
Values above 20 bar are ignored. The published protocol does not include a
zero or tare command, so none is exposed. This decode was checked against
the protocol table and the open-source BrewLog client. It has not been
confirmed on hardware in this repository.

## Firmware 4.0.0 compatibility

Version 0.1.2 implements the Bookoo Ultra protocol published on
12 August 2026. It corrects the unit-byte mapping and standby-time scaling and
adds powder-weight packets, automatic-mode settlement packets and the shutdown
command. The live numeric weight transmitted by the scale is always interpreted
as grams, as specified by Bookoo.

Firmware-4-only entities remain unknown when the scale does not send the new
packet types. The integration does not invent a firmware version or attempt a
firmware update because neither function is part of the published protocol.

Protocol source:
[BooKooCode/OpenSource – Ultra scale protocol](https://github.com/BooKooCode/OpenSource/blob/main/bookoo_ultra_scale/protocols.md)

---

## Deutsche Dokumentation

Diese benutzerdefinierte Home-Assistant-Integration bindet die
**Bookoo Themis Ultra** und den **Bookoo Espresso Monitor** lokal über
Bluetooth ein. Ab Version 0.1.2 wird die Waagen-Firmware 4.0.0 einschließlich
Pulvergewicht, Automatikereignissen, Abschlussdaten und Ausschaltbefehl
unterstützt. Ab Version 0.2.0 kommt der Espresso Monitor als eigenes Gerät
hinzu, mit Druck in bar, Batterie, Verbindungsstatus und Start-/Stopp-Befehl.
Ein Nullpunkt- oder Tara-Befehl ist im veröffentlichten Monitor-Protokoll
nicht enthalten. Bestehende Waagen-Einträge und Entitäts-IDs bleiben
unverändert.

### Neue Entitäten mit Firmware 4.0.0

- **Pulvergewicht:** aktuelles Pulvergewicht lesen und zwischen `0,1` und
  `999,0 g` einstellen
- **Automatikmodus-Ereignis:** bereit, gestartet, gestoppt, Bereitschaft
  verlassen und Ergebnis verlassen
- **Automatikmodus-Zeit:** zuletzt übertragene Zeit
- **Automatikmodus-Gewicht:** zuletzt übertragenes Gewicht
- **Automatikmodus-Ergebnis:** durchschnittlicher Flow im Zeitmodus oder Ratio
  im Ratio-Modus; ohne Einheit, da die Waage den aktiven Modus nicht meldet
- **Ausschalten:** schaltet die Waage aus; während des Ladens laut Hersteller
  nicht verfügbar

Kalibrierung und die automatische Stop-Bedingung der Waage werden bewusst nicht
als Home-Assistant-Entitäten angeboten. Die automatische Stop-Bedingung würde
nur festlegen, ob der interne Automatikmodus der Waage beim Ende des Flows oder
beim Entfernen der Tasse endet; sie stoppt nicht die Espressomaschine.

### Installation über HACS

1. **HACS** öffnen und **Integrationen** auswählen.
2. Dieses Repository als **benutzerdefiniertes Repository** hinzufügen.
3. **Bookoo Themis & Espresso Monitor** installieren.
4. Home Assistant neu starten.
5. Die Bookoo-Integration unter **Einstellungen > Geräte & Dienste**
   hinzufügen.

## Credits and license

This project is based on earlier work by Esojma-Silverbullet, makerwolf and the
Home Assistant community. It is licensed under the MIT License; see
[LICENSE](LICENSE).
