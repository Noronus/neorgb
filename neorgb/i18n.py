"""User interface languages.

The source texts are German.  ``EN`` maps each one to English; ``PATTERNS``
covers texts the daemon builds with numbers or names in them ("Lüfter 3",
"WLED unter 10.0.5.120 nicht erreichbar (...)").  The GUI installs a
QTranslator that calls ``translate()``, so QML's ``qsTr()`` and texts that
come from the daemon go through the same table.

Placeholders are Qt style (%1, %2) and stay in place; QML fills them with
``.arg()`` after translating.
"""

from __future__ import annotations

import re

LANGUAGES = {"de": "Deutsch", "en": "English"}

EN: dict[str, str] = {
    # ------------------------------------------------------------ main window
    "verbunden": "connected",
    "Dienst aus": "service off",
    "Übersicht": "Overview",
    "Kühlung": "Cooling",
    "Beleuchtung": "Lighting",
    "Geräte": "Devices",
    "Einstellungen": "Settings",
    "Wasser": "Liquid",
    "Der NeoRGB-Dienst startet …": "The NeoRGB service is starting …",
    "NeoRGB ist bis zum nächsten Neustart aus": "NeoRGB is off until the next restart",
    "Der NeoRGB-Dienst läuft nicht": "The NeoRGB service is not running",
    "Ohne ihn steuert die AIO wieder ihre gespeicherte Hardware-Kurve.":
        "Without it the AIO runs its stored hardware curve again.",
    "Dienst starten": "Start service",
    "Fertig": "Done",
    "jetzt": "now",
    "Kopiert": "Copied",

    # --------------------------------------------------------------- overview
    "%1 Geräte · %2 Lüfter/Pumpen · %3 Lichtzonen": "%1 devices · %2 fans/pumps · %3 lighting zones",
    "AIO-Kühlmittel": "AIO coolant",
    "Hotspot": "Hotspot",
    "%1 % Leistung": "%1 % power",
    "Temperaturen": "Temperatures",
    "letzte 10 Minuten": "last 10 minutes",
    "Lüfter & Pumpe": "Fans & pump",
    "Keine Lüftersteuerung gefunden": "No fan controller found",
    "Aktueller Effekt: %1": "Current effect: %1",
    "Bearbeiten": "Edit",
    "Helligkeit": "Brightness",

    # ---------------------------------------------------------------- cooling
    "Lüfter, Pumpe, Mainboard- und GPU-Lüfter folgen einer Kurve, laufen fest oder bleiben bei BIOS/GPU. "
    "Ziehe Punkte, Doppelklick fügt hinzu, Rechtsklick entfernt.":
        "Fans, pump, mainboard and GPU fans follow a curve, run at a fixed speed or stay with the BIOS/GPU. "
        "Drag points, double-click adds one, right-click removes it.",
    "rpm": "rpm",
    "Regelt sich selbst (Lüftersteuerung für dieses Gerät aus, siehe Geräte)":
        "Runs on its own (fan control is off for this device, see Devices)",
    "Nur Anzeige: keine Schreibrechte (siehe Geräte)": "Read-only: no write access (see Devices)",
    "Kurve": "Curve",
    "Fest": "Fixed",
    "Die Grafikkarte regelt selbst": "The graphics card controls itself",
    "Das Mainboard regelt nach BIOS-Einstellung": "The mainboard follows its BIOS settings",
    "Kurve: %1": "Curve: %1",
    "verwendet von %1": "used by %1",
    "von keinem Kanal verwendet": "not used by any channel",
    "Neue Kurve": "New curve",
    "Eigene %1": "Custom %1",
    "Löschen": "Delete",
    "Sensor": "Sensor",
    "Glätten": "Smoothing",
    "aus": "off",
    "4 Sekunden": "4 seconds",
    "8 Sekunden": "8 seconds",
    "15 Sekunden": "15 seconds",
    "30 Sekunden": "30 seconds",
    "Name": "Name",
    "Aktuell": "Now",
    "Verhalten": "Behaviour",
    "Gilt für alle Kurven": "Applies to all curves",
    "Hysterese (erst bei so viel Grad weniger langsamer werden)":
        "Hysteresis (slow down only after this many degrees less)",
    "Hochregeln höchstens (pro Sekunde)": "Speed up at most (per second)",
    "Runterregeln höchstens (pro Sekunde)": "Slow down at most (per second)",
    "Leistung, wenn der Sensor einer Kurve ausfällt": "Power when a curve's sensor fails",
    "Gilt nur für Kanäle, deren eigener Sensor fehlt. Die Pumpe läuft nie unter 50 %. "
    "Ab 50 °C Wasser gehen immer alle auf 100 %.":
        "Only for channels whose own sensor is missing. The pump never runs below 50 %. "
        "From 50 °C liquid, everything always goes to 100 %.",
    "Sensor gilt als ausgefallen nach": "Sensor counts as failed after",
    "Kurven in der AIO speichern": "Store curves in the AIO",
    "Läuft NeoRGB nicht (Boot, Absturz), regelt die AIO selbst nach Wassertemperatur. "
    "Kurven mit anderem Sensor werden dort durch „Ausgewogen“ ersetzt.":
        "When NeoRGB is not running (boot, crash), the AIO controls itself by liquid temperature. "
        "Curves with another sensor are replaced there by “Balanced”.",

    # curve, fan and sensor names from the daemon
    "Leise": "Quiet",
    "Ausgewogen": "Balanced",
    "Leistung": "Performance",
    "Pumpe ausgewogen": "Pump balanced",
    "CPU-Temperatur": "CPU temperature",
    "GPU-Hotspot": "GPU hotspot",
    "Pumpe": "Pump",
    "Lüfter %1": "Fan %1",
    "Grafikkarte": "Graphics card",
    "Grafikkarte (AMD)": "Graphics card (AMD)",
    "Wasser (AIO)": "Liquid (AIO)",
    "GPU (Hotspot)": "GPU (hotspot)",
    "Nur Anzeige: Overdrive ist aus (siehe Geräte)": "Read-only: overdrive is off (see Devices)",
    "Diese Kurve nutzt keinen GPU-Sensor. Die Karte regelt weiter selbst.":
        "This curve does not use a GPU sensor. The card keeps controlling itself.",
    "Kurve läuft in der Grafikkarte (Hotspot)": "Curve runs in the graphics card (hotspot)",
    "Keine Schreibrechte. Einmal ausführen, dann neu starten:": "No write access. Run this once, then reboot:",
    "Lüfter nur ablesbar: Der Kernel-Parameter ist gesetzt, aber der Treiber bietet keine Lüftersteuerung an.":
        "Fan is read-only: the kernel parameter is set, but the driver offers no fan control.",
    "Lüfter nur ablesbar: Overdrive ist eingetragen und greift nach dem nächsten Neustart.":
        "Fan is read-only: overdrive is configured and takes effect after the next reboot.",
    "Lüfter nur ablesbar. Das ist kein Befehl, sondern ein Kernel-Parameter: im Bootloader anhängen "
    "(GRUB: GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub), dann neu starten.":
        "Fan is read-only. This is not a command but a kernel parameter: add it in the boot loader "
        "(GRUB: GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub), then reboot.",

    # ---------------------------------------------------------------- devices
    "Wie der globale Effekt": "Same as the global effect",
    "Regenbogen-Welle": "Rainbow wave",
    "Regenbogen": "Rainbow",
    "Farbwechsel": "Colour shift",
    "Farbverlauf": "Gradient",
    "Pulsieren": "Pulse",
    "Farbwelle": "Colour wave",
    "Statisch": "Static",
    "Lauflicht": "Marquee",
    "Blinken": "Blink",
    "Nacheinander": "Sequential",
    "Aus": "Off",
    "Lighting Nodes erkennen nicht, was angeschlossen ist. Trag hier pro Kanal ein, was in welcher "
    "Reihenfolge dranhängt.":
        "Lighting Nodes cannot detect what is connected. Enter here, per channel, what hangs on it and in which order.",
    "WLED-Gerät hinzufügen": "Add WLED device",
    "IP-Adresse oder Hostname des WLED-Controllers. NeoRGB schickt ihm die Effekte per DDP.":
        "IP address or host name of the WLED controller. NeoRGB sends it the effects over DDP.",
    "z. B. 10.0.5.120": "e.g. 10.0.5.120",
    "Name (optional)": "Name (optional)",
    "Hinzufügen": "Add",
    "Ausgeschlossen: NeoRGB fasst dieses Gerät nicht an": "Excluded: NeoRGB does not touch this device",
    "Firmware %1": "Firmware %1",
    "Wieder einbinden": "Include again",
    "Ausschließen": "Exclude",
    "Lüfter und Pumpe regelt dann die AIO selbst nach ihrer gespeicherten Kurve. Die Einstellung bleibt auch nach Neustarts.":
        "The AIO then runs fans and pump on its stored curve. The setting survives restarts.",
    "Das Gerät behält sein eigenes Licht. Die Einstellung bleibt auch nach Neustarts.":
        "The device keeps its own lighting. The setting survives restarts.",
    "Lüfter von NeoRGB steuern": "Let NeoRGB control the fans",
    "Aus: Die AIO fährt ihre gespeicherte Kurve. Drehzahlen bleiben unter „Kühlung“ sichtbar.":
        "Off: the AIO runs its stored curve. Speeds stay visible under “Cooling”.",
    "Aus: Die Grafikkarte regelt selbst. Drehzahlen bleiben unter „Kühlung“ sichtbar.":
        "Off: the graphics card controls itself. Speeds stay visible under “Cooling”.",
    "Aus: Das BIOS regelt selbst. Drehzahlen bleiben unter „Kühlung“ sichtbar.":
        "Off: the BIOS is in control. Speeds stay visible under “Cooling”.",
    "Mindesthelligkeit": "Minimum brightness",
    "Kanal %1": "Channel %1",
    "Zählen beenden": "Stop counting",
    "LEDs zählen": "Count LEDs",
    "Aufblinken": "Flash",
    "Leeren": "Clear",
    "Jedes Teil an diesem Kanal leuchtet jetzt in einer eigenen Farbe (je %1 LEDs, Typ oben im Auswahlfeld). "
    "Schau ins Gehäuse und zähle die Farben in dieser Reihenfolge:":
        "Each part on this channel now lights up in its own colour (%1 LEDs each, type from the list above). "
        "Look into the case and count the colours in this order:",
    "Rot": "Red",
    "Grün": "Green",
    "Blau": "Blue",
    "Gelb": "Yellow",
    "Lila": "Purple",
    "Türkis": "Cyan",
    "Weiß": "White",
    "Orange": "Orange",
    "Was dunkel bleibt oder seine alten Farben behält, hängt nicht an diesem Kanal. Ist eine Farbe nur halb "
    "zu sehen, oben einen anderen Typ wählen und neu zählen.":
        "Whatever stays dark or keeps its old colours is not on this channel. If a colour only shows on half "
        "a part, pick another type above and count again.",
    "Ich sehe:": "I see:",
    "1 Farbe": "1 colour",
    "nichts": "nothing",
    "Nichts eingetragen: der Hub behält sein eigenes Licht": "Nothing entered: the hub keeps its own lighting",
    "Eigene Anzahl…": "Custom count…",
    "Wenn NeoRGB nicht läuft:": "When NeoRGB is not running:",
    "Die angeschlossenen Lüfter und die Pumpe meldet der Commander CORE selbst.":
        "The Commander CORE reports the connected fans and the pump itself.",
    "%1 LEDs erkannt": "%1 LEDs detected",
    "nichts erkannt": "nothing detected",
    "automatisch": "automatic",
    "%1 Lüfter · eingestellt wird unter „Kühlung“.": "%1 fans · set them up under “Cooling”.",
    "Anschlüsse erscheinen, sobald dort einmal ein Lüfter gedreht hat. Stoppt NeoRGB, regelt wieder das BIOS.":
        "Headers show up once a fan has spun on them. When NeoRGB stops, the BIOS takes over again.",
    "Die Kurve läuft in der Grafikkarte selbst, gegen die Hotspot-Temperatur.":
        "The curve runs in the graphics card itself, against the hotspot temperature.",
    "Kopieren": "Copy",
    "WLED über das Netzwerk · %1 LEDs. Läuft NeoRGB nicht, zeigt WLED nach ein paar Sekunden wieder seinen eigenen Effekt.":
        "WLED over the network · %1 LEDs. When NeoRGB is not running, WLED shows its own effect again after a few seconds.",
    "Nicht erreichbar, NeoRGB versucht es alle 10 s erneut.": "Not reachable, NeoRGB retries every 10 s.",
    "WLED-Oberfläche öffnen": "Open WLED interface",
    "Entfernen": "Remove",
    "Über OpenRGB angebunden · %1": "Connected through OpenRGB · %1",
    "Übernehmen": "Apply",
    "ARGB-Anschluss: Anzahl der LEDs eintragen": "ARGB header: enter the number of LEDs",
    # device states and Lighting Node parts from the daemon
    "error": "error",
    "offline": "offline",
    "starting": "starting",
    "RGB-LED-Streifen (Lighting Node PRO Kit)": "RGB LED strip (Lighting Node PRO kit)",
    "LS100 Streifen 250 mm": "LS100 strip 250 mm",
    "LS100 Streifen 350 mm": "LS100 strip 350 mm",
    "LS100 Streifen 450 mm": "LS100 strip 450 mm",
    "LT100 Turm": "LT100 tower",
    "SP/AF RGB Elite Lüfter (8 LEDs)": "SP/AF RGB Elite fan (8 LEDs)",
    "HD RGB Lüfter (12 LEDs)": "HD RGB fan (12 LEDs)",
    "LL RGB Lüfter (16 LEDs)": "LL RGB fan (16 LEDs)",
    "QL RGB Lüfter (34 LEDs)": "QL RGB fan (34 LEDs)",
    "ML PRO RGB Lüfter (4 LEDs)": "ML PRO RGB fan (4 LEDs)",
    "SP RGB Lüfter (1 LED)": "SP RGB fan (1 LED)",

    # --------------------------------------------------------------- lighting
    "Ein Effekt für alles oder eigene Effekte pro Zone.": "One effect for everything, or separate effects per zone.",
    "Gesamthelligkeit": "Overall brightness",
    "Profile": "Profiles",
    "Ein Profil speichert die Effekte aller Zonen auf einmal": "A profile stores the effects of all zones at once",
    "Alles speichern": "Save all",
    "Klick lädt das Profil. Rechtsklick löscht. Gleicher Name überschreibt.":
        "Click loads the profile. Right-click deletes it. Saving under the same name overwrites it.",
    "Noch keine Profile. Speichert den globalen Effekt und alle Zonen mit eigenem Effekt.":
        "No profiles yet. A profile stores the global effect and every zone with its own effect.",
    "Zonen": "Zones",
    "Klick auf eine Zone, um ihr einen eigenen Effekt zu geben": "Click a zone to give it its own effect",
    "Alle (globaler Effekt)": "All (global effect)",
    "eigen": "own",
    "Noch keine Lichtzonen. Unter „Geräte“ eintragen, was an den Lighting Nodes hängt.":
        "No lighting zones yet. Enter under “Devices” what hangs on the Lighting Nodes.",
    "Globaler Effekt": "Global effect",
    "%1 LEDs": "%1 LEDs",
    "Gilt für alle Zonen ohne eigenen Effekt": "Applies to all zones without their own effect",
    "Aufblinken lassen": "Flash it",
    "Eigener Effekt für diese Zone": "Own effect for this zone",
    "Gespeicherte Effekte": "Saved effects",
    "Aktuellen speichern": "Save current",
    "Noch nichts gespeichert. Ohne Namen wird der Effektname verwendet.":
        "Nothing saved yet. Without a name, the effect's name is used.",
    "Klick lädt den Effekt. Rechtsklick löscht. Gleicher Name überschreibt.":
        "Click loads the effect. Right-click deletes it. Saving under the same name overwrites it.",
    "Klick lädt den Effekt (die Zone bekommt dann ihren eigenen Effekt). Rechtsklick löscht. Gleicher Name überschreibt.":
        "Click loads the effect (the zone then gets its own effect). Right-click deletes it. "
        "Saving under the same name overwrites it.",
    "Effekt für alle Zonen": "Effect for all zones",
    "Effekt für %1": "Effect for %1",
    "Diese Zone folgt dem globalen Effekt": "This zone follows the global effect",
    "Farben: kalt · heiß": "Colours: cold · hot",
    "Farben: Vordergrund · Hintergrund": "Colours: foreground · background",
    "Farben": "Colours",
    "Rechtsklick entfernt": "Right-click removes",
    "Bildbereich": "Screen area",
    "Rand rundum": "Edges all around",
    "Ganzes Bild": "Whole picture",
    "Farbverstärkung": "Colour boost",
    "Bildschirmaufnahme: %1": "Screen capture: %1",
    "Bildschirm wird aufgenommen.": "Capturing the screen.",
    "Beim ersten Mal fragt KDE, welcher Bildschirm geteilt werden soll. Danach läuft es ohne Nachfrage.":
        "The first time, KDE asks which screen to share. After that it runs without asking.",
    "Reaktion": "Response",
    "Geschwindigkeit": "Speed",
    "Wiederholungen": "Repeats",
    "Schweif": "Tail",
    "Dichte": "Density",
    "Hintergrund": "Background",
    "Kalt bis": "Cold up to",
    "Heiß ab": "Hot from",
    "Richtung umkehren": "Reverse direction",
    "Helligkeit dieses Effekts": "Brightness of this effect",
    # effect names from the daemon
    "Atmen": "Breathing",
    "Kreisen": "Spin",
    "Komet": "Comet",
    "Funkeln": "Twinkle",
    "Temperatur": "Temperature",
    "Bildschirm": "Screen",
    "Effekt": "Effect",
    # screen capture errors
    "Bildschirmfreigabe beendet": "Screen sharing ended",
    "Bildschirmfreigabe abgelehnt": "Screen sharing declined",
    "Portal-Fehler": "Portal error",
    "Portal lieferte keinen Bildschirm": "The portal returned no screen",

    # --------------------------------------------------------------- settings
    "Sprache": "Language",
    "Andere RGB-Geräte über OpenRGB": "Other RGB devices through OpenRGB",
    "Mainboard (Aura), RAM, Tastatur und Maus laufen über einen OpenRGB-Server. Die Corsair-Hubs bleiben bei NeoRGB.":
        "Mainboard (Aura), RAM, keyboard and mouse run through an OpenRGB server. The Corsair hubs stay with NeoRGB.",
    "OpenRGB-Geräte einbinden": "Include OpenRGB devices",
    "OpenRGB-Server selbst starten (ohne Corsair-Hubs)": "Start our own OpenRGB server (without the Corsair hubs)",
    "Änderungen hier greifen nach einem Neustart des Dienstes.": "Changes here take effect after a service restart.",
    "Bilder pro Sekunde": "Frames per second",
    "Dienst": "Service",
    "neorgbd läuft im Hintergrund und regelt auch ohne dieses Fenster.":
        "neorgbd runs in the background and keeps working without this window.",
    "Läuft seit %1 min": "Running for %1 min",
    "Dienst neu starten": "Restart service",
    "Ausschalten bis zum Neustart": "Switch off until restart",
    "Neu starten lädt auch den OpenRGB-Server neu. Ausgeschaltet regelt die AIO nach ihrer gespeicherten Kurve, "
    "bis zum nächsten Login.":
        "Restarting also reloads the OpenRGB server. When switched off, the AIO runs its stored curve until the next login.",
    "Autostart: systemctl --user enable --now neorgbd": "Autostart: systemctl --user enable --now neorgbd",
    "Konfiguration: ~/.config/neorgb/config.json": "Configuration: ~/.config/neorgb/config.json",
    "Über": "About",
    "NeoRGB %1 · GPL-3.0-or-later · Protokolle nach liquidctl, OpenLinkHub und OpenRGB":
        "NeoRGB %1 · GPL-3.0-or-later · protocols after liquidctl, OpenLinkHub and OpenRGB",

    # ------------------------------------------------------------------- tray
    "Fenster öffnen": "Open window",
    "Beenden (Dienst läuft weiter)": "Quit (service keeps running)",
    "Dienst läuft": "Service running",
    "Dienst startet …": "Service starting …",
    "Ausgeschaltet bis zum Neustart": "Switched off until restart",
    "Dienst läuft nicht": "Service not running",
    "Neustart fehlgeschlagen": "Restart failed",
    "Ausschalten fehlgeschlagen": "Switching off failed",

    # ------------------------------------------------------- daemon errors
    "Kurve wird noch verwendet": "The curve is still in use",
    "eine Kurve braucht mindestens 2 Punkte": "a curve needs at least 2 points",
    "Lighting Node nicht bereit": "Lighting Node not ready",
    "Bitte eine IP-Adresse oder einen Hostnamen eintragen": "Please enter an IP address or a host name",
    "openrgb ist nicht installiert": "openrgb is not installed",
    "neorgbd läuft nicht (systemctl --user start neorgbd)": "neorgbd is not running (systemctl --user start neorgbd)",
    "Verbindung zum Daemon verloren": "Lost the connection to the daemon",
}

# Texts with a variable part.  Captured parts are translated too, so
# "Wasser (AIO) fehlt" becomes "Liquid (AIO) missing".
PATTERNS: list[tuple[re.Pattern, str]] = [(re.compile(p), t) for p, t in (
    (r"Lüfter (\d+)", "Fan {0}"),
    (r"RGB-Port (\d+)", "RGB port {0}"),
    (r"Kanal (\d+)", "Channel {0}"),
    (r"Kanal (\d+) gibt es nicht", "There is no channel {0}"),
    (r"Temperaturfühler (\d+)", "Temperature probe {0}"),
    (r"Mainboard-Lüfter · (.+)", "Mainboard fans · {0}"),
    (r"Profil (\d+)", "Profile {0}"),
    (r"(\d+) LEDs", "{0} LEDs"),
    (r"Wasser über (\d+) °C", "Liquid above {0} °C"),
    (r"GStreamer/PyGObject fehlt: (.*)", "GStreamer/PyGObject missing: {0}"),
    (r"(.+) fehlt", "{0} missing"),
    (r"WLED unter (.+) nicht erreichbar \((.*)\)", "WLED at {0} not reachable ({1})"),
    (r"(.+) ist kein WLED-Gerät", "{0} is not a WLED device"),
    (r"(.+) ist schon eingetragen", "{0} is already added"),
)]


def translate(text: str, lang: str) -> str:
    """``text`` in ``lang``; unknown texts (names the user typed, hardware labels) come back unchanged."""
    if lang != "en" or not text:
        return text
    hit = EN.get(text)
    if hit is not None:
        return hit
    for rx, tmpl in PATTERNS:
        m = rx.fullmatch(text)
        if m:
            return tmpl.format(*(translate(g, lang) for g in m.groups()))
    return text
