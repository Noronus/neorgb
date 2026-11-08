# NeoRGB

RGB-Beleuchtung und Corsair-AIO-/Lüftersteuerung für Linux, in einem Dienst
und einer Oberfläche.

- **Corsair direkt:** iCUE Commander CORE / CORE XT / ST (Pumpe, Lüfter,
  Wassertemperatur, RGB), Lighting Node PRO / CORE, LS100, LT100
- **Lüfter und Pumpe:** Kurven nach Wasser-, CPU-, GPU- oder jedem anderen
  hwmon-Sensor, mit Hysterese, Glättung und begrenzter Regelgeschwindigkeit.
  Fester Wert pro Kanal möglich.
- **Ausfallsicher:** Die Kurven werden zusätzlich in der AIO gespeichert.
  Läuft NeoRGB nicht (Boot, Absturz, Dienst gestoppt), regelt die AIO selbst
  nach Wassertemperatur. Die Pumpe fällt nie unter 50 %. Ab 50 °C Wasser oder
  bei fehlendem Sensor gehen alle Kanäle auf 100 %.
- **Alles andere** (ASUS Aura, RAM, Tastatur, Maus) über einen privaten
  OpenRGB-Server, den NeoRGB selbst startet. In dessen Konfiguration sind die
  Corsair-Hubs abgeschaltet, damit nie zwei Programme gleichzeitig auf dasselbe
  Gerät zugreifen.

## Installieren

```sh
./install.sh
systemctl --user enable --now neorgbd
```

Danach liegt „NeoRGB“ im Startmenü. Kommandozeile: `neorgbctl status`.

Voraussetzungen: Python ≥ 3.11, PySide6 (`pyside6`), `openrgb` für die
Nicht-Corsair-Geräte und die OpenRGB-udev-Regeln (geben Zugriff auf
`/dev/hidraw*` und I²C).

## Lighting Nodes einrichten

Lighting Node PRO/CORE erkennen nicht, was angeschlossen ist. Unter
**Geräte** beim Kanal den Typ wählen (z. B. „RGB-LED-Streifen“) und
**LEDs zählen** drücken: Jedes Teil am Kanal leuchtet dann in einer eigenen
Farbe (Rot, Grün, Blau, …). Unten anklicken, wie viele Farben zu sehen sind,
fertig. Ist die Anzahl zu klein, behalten die LEDs dahinter ihre alte Farbe.
Dann leuchten Streifen nur teilweise.

Ist ein Kanal leer, fasst NeoRGB ihn nicht an. Er behält das Licht, das im
Hub gespeichert ist.

## Dateien

| Was | Wo |
|---|---|
| Einstellungen | `~/.config/neorgb/config.json` |
| Original-Hardwarekurven der AIO (vor dem ersten Schreiben) | `~/.config/neorgb/backup/` |
| privater OpenRGB-Server | `~/.config/neorgb/openrgb/` |
| Socket | `$XDG_RUNTIME_DIR/neorgb.sock` |

## Aufbau

```
neorgb/daemon.py          Dienst: Geräte-Threads, Effekte, Lüfterregelung, Socket-API
neorgb/devices/           Commander CORE, Lighting Node, OpenRGB-SDK-Client
neorgb/fancontrol.py      Kurven, Hysterese, Rampen, Failsafe
neorgb/effects.py         Software-Effekte
neorgb/gui/               PySide6/QML-Oberfläche
neorgb/cli.py             neorgbctl
```

Protokolle nach liquidctl, OpenLinkHub und OpenRGB (alle GPL). NeoRGB steht
unter GPL-3.0-or-later.
