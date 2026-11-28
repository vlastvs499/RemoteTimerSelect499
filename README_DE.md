# RemoteTimerSelect499

> **Language / Jazyk / Sprache:** [English (README.md)](README.md) | [Čeština (README_CZ.md)](README_CZ.md) | **Deutsch**

Ein schlanker Ersatz für das **RemoteTimer / Partnerbox**-Plugin für **OpenATV / Enigma2 (Python 3)** — mit Unterstützung für bis zu **4 Remote-Receiver**.
Erstelle, prüfe und verwalte Timer auf deinem lokalen Receiver sowie bis zu **4 Remote-Enigma2-Receivern** direkt aus dem EPG oder im Live-TV — komplett über die Fernbedienung konfigurierbar.

## Funktionen

* **EPG- & Sofortaufnahme mit REC-Taste:** Drücke **REC** im EPG (oder bei aktivierter Option auch direkt beim Fernsehen), um den lokalen oder einen beliebigen Remote-Receiver auszuwählen, Vor- und Nachlaufzeiten festzulegen, eine **Unendliche Aufnahme** zu starten, den **Aufnahmepfad** zu wechseln oder einen bestehenden Timer abzubrechen.

* **Live-Status in der Receiver-Auswahl:** Receiver, die gerade aufnehmen, werden **rot** hervorgehoben (`REC bis: 19:00` oder `REC bis: ∞` bei unendlicher Aufnahme). Receiver mit einem geplanten Timer innerhalb der nächsten 100 Minuten werden **gelb** hervorgehoben (`Gepl. REC in: 45 Min`). So erkennst du sofort, welche Box frei ist, und vermeidest unnötige Timer-Konflikte.

* **EPG-Timer-Markierungen:** Geplante Sendungen werden im EPG automatisch mit benutzerdefinierten Receiver-Kürzeln (z. B. `[L]`, `[M]`, `[V]`) markiert. Die Kürzel lassen sich direkt in den **Remote-Timer Einstellungen** festlegen.

* **Gemeinsame Übersicht „Alle Timer“:** Zeigt alle lokalen und entfernten Timer in einer chronologisch sortierten Übersicht (`Datum & Zeit` → `Status` → `Kürzel` → `Sender | Sendung`) mit farbigem Status, `∞`-Symbol und blinkender `[Aufnahme]`-Anzeige bei laufenden unendlichen Aufnahmen.

* **Schnelle Änderung der Endzeit:** Drücke **BLAU** in *Alle Timer*, um das Ende eines laufenden oder wartenden Timers anzupassen (`±1 Min` / `±5 Min`) — inklusive integriertem Kollisionsschutz (1 Minute Sicherheitsabstand vor dem nächsten wartenden Timer auf derselben Box).

* **Aufnahmen stoppen & löschen:** Drücke **ROT** auf einer laufenden Aufnahme in *Alle Timer*, um **STOP REC** oder **STOP REC & AUFNAHME LÖSCHEN** zu wählen (stoppt die Aufnahme und löscht sowohl den Timer als auch die Datei von der Festplatte). Mit **OK** wird der Timer gelöscht und die Aufnahme gestoppt, die bisher aufgenommene Datei bleibt jedoch erhalten.

* **Dynamischer Aufnahmepfad & HDD-Wakeup-Unterstützung:** Fragt automatisch das aktive Aufnahmeverzeichnis jeder Remote-Box ab und weckt schlafende Festplatten im Hintergrund ohne Timeouts oder Einfrieren der Oberfläche (voll kompatibel mit OpenATV 8.0). Im Fenster **Vor-/Nachlauf** kannst du in der letzten Zeile (**Aufnahmepfad**) mit den Pfeiltasten **LINKS/RECHTS** sofort zwischen dem aktuell geöffneten Ordner und dem Standard-Aufnahmepfad des Receivers wechseln — bereits geplante Timer behalten ihren gewählten Pfad bei.

* **Einrichtung per Fernbedienung & Auto-Löschen:** Konfiguriere bis zu 4 Remote-Boxen direkt am Receiver (gespeichert in `/etc/enigma2/settings`) inklusive automatischem Löschen und Ein-Klick-Bereinigung fertiger/fehlgeschlagener Timer.

## Installation

### Option 1: Schnellinstallation per SSH oder Telnet (RCC / DCC)

Verbinde dich per **SSH** oder **Telnet** (z. B. mit **PuTTY**, **RCC** oder **DCC**) als `root` mit deinem Receiver, kopiere die Befehle für deine gewünschte Sprache und bestätige mit **Enter** (die Enigma2-GUI startet anschließend automatisch neu):

#### Deutsche Version (`DE`)

```bash
mkdir -p /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/__init__.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/DE/__init__.py
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/plugin.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/DE/plugin.py
killall -9 enigma2
```

#### Englische Version (`EN`)

```bash
mkdir -p /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/__init__.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/EN/__init__.py
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/plugin.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/EN/plugin.py
killall -9 enigma2
```

#### Tschechische Version / Česká verze (`CZ`)

```bash
mkdir -p /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/__init__.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/CZ/__init__.py
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/plugin.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/CZ/plugin.py
killall -9 enigma2
```

### Option 2: Manuelle Installation

1. Erstelle das Verzeichnis `/usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/` auf deinem Receiver.
2. Kopiere `__init__.py` und `plugin.py` aus dem Ordner `DE/`, `EN/` oder `CZ/` in dieses Verzeichnis (**UTF-8**-Kodierung und **LF**-Zeilenenden beibehalten).
3. Starte die Enigma2-GUI neu (`killall -9 enigma2` oder über **Menü → Standby / Neustart → GUI neu starten**).

> **Tipp:** Wenn du mehrere Receiver besitzt, installiere das Plugin auf allen Boxen, um Timer boxübergreifend von jedem gerade genutzten Receiver aus verwalten zu können.

## Konfiguration (Fernbedienung)

1. Öffne die Einstellungen über eines dieser Menüs:
   * **Menü → Alle Timer**, dann **GELB** oder **MENU** drücken
   * **Menü → Timer → Remote-Timer Einstellungen**
   * **Erweiterungen / Plugins → Remote-Timer - Einstellungen**
2. Konfiguriere deine Optionen:
   * **Kürzel dieses Receivers (max. 2 Zeichen):** Kurzes Kürzel (Standard: `L`), idealerweise 1 Zeichen, da es im EPG direkt vor dem Sendungstitel angezeigt wird.
   * **Auto-Löschen fertiger/fehlgeschl. Timer (Tage):** Anzahl der Tage bis zur automatischen Bereinigung (`0` = aus).
   * **Box-Auswahl mit REC (empf. Ja):** `Nein` = klassisches OpenATV-Verhalten bei Sofortaufnahme, `Ja` = öffnet beim Drücken von **REC** die einheitliche Receiver-Auswahl. (Im EPG steht die Receiver-Auswahl immer zur Verfügung.)
   * **Bis zu 4 Remote-Boxen:** Drücke **OK** auf Textfeldern für die Bildschirmtastatur, gib IP-Adressen über die Zifferntasten (`0–9`) ein (`0.0.0.0` = deaktiviert), Standard-OpenWebif-Port ist `80`.
3. Drücke **GRÜN** zum Speichern. Remote-Timer werden sofort ohne GUI-Neustart synchronisiert.

## Bedienung

* **EPG:** Markiere eine Sendung und drücke **REC**, um auf einer beliebigen konfigurierten Box einen Timer zu setzen oder abzubrechen.
* **Alle Timer (`Menü → Alle Timer`):**
  * **OK:** Ausgewählten Timer löschen (auch bei laufender Aufnahme — stoppt die Aufnahme und löscht den Timer, behält aber die Datei; über das obere Banner können alle fertigen/fehlgeschlagenen Timer auf einmal gelöscht werden).
  * **ROT:** Laufende Aufnahme stoppen (**STOP REC** oder **STOP REC & AUFNAHME LÖSCHEN**).
  * **BLAU:** Endzeit eines laufenden oder wartenden Timers ändern (`LINKS/RECHTS` = ±1 Min, `HOCH/RUNTER` = ±5 Min).
  * **GELB / MENU:** **Remote-Timer Einstellungen** öffnen.

> **Tipp:** Es wird empfohlen, die Option **Box-Auswahl mit REC (empf. Ja)** auf **Ja** zu stellen (zu finden unter **Erweiterungen / Plugins → Remote-Timer - Einstellungen → Box-Auswahl mit REC (empf. Ja)** oder über **Menü → Timer → Remote-Timer Einstellungen → Box-Auswahl mit REC (empf. Ja)**). Dadurch ist die gesamte Aufnahmesteuerung — einschließlich lokaler Aufnahmen und Pfadauswahl — komplett einheitlich. Ist die Option deaktiviert, wird die Sofortaufnahme weiterhin vom System gesteuert.

## Änderungsprotokoll (Changelog)

### 27.11.2026

* **Einheitliche REC-Taste (`Box-Auswahl mit REC (empf. Ja)`):** Verhalten der REC-Taste bei aktivierter Option in den *Remote-Timer Einstellungen* definiert (einheitliche Auswahl von Vor-/Nachlauf und Aufnahmepfad).
* **Auswahl des Aufnahmepfads:** Möglichkeit hinzugefügt, im Fenster *Vor-/Nachlauf* direkt zwischen dem Standard-Aufnahmepfad des Systems und dem aktuell geöffneten Ordner zu wählen (sowohl lokal als auch auf Remote-Boxen).
* **Stop REC Fix (ROTE Taste):** Das Stoppen einer laufenden lokalen Aufnahme über die rote Taste bei aktivierter Option *Box-Auswahl mit REC (empf. Ja)* in den *Remote-Timer Einstellungen* wurde behoben.

### 26.11.2026

* **Optionale REC-Taste bei Sofortaufnahme:** Konfigurierbare Option (*Box-Auswahl mit REC (empf. Ja)*) hinzugefügt, um die Receiver-Auswahl direkt beim Fernsehen zu öffnen (volle Unterstützung für OpenATV 8.0).
* **REC-Ende ändern (BLAUE Taste):** Änderung der Endzeit für laufende und wartende Timer in *Alle Timer* mit 1 Minute Kollisionsschutz vor dem nächsten wartenden Timer auf derselben Box.
* **Unendliche Aufnahme & blinkende Anzeige:** Option *Unendliche Aufnahme* (24 Std.), sauber ausgerichtetes **`∞`**-Symbol und im 1-Hz-Takt blinkender `[Aufnahme]`-Status in *Alle Timer*.
* **Hinweis auf bald geplante Aufnahme:** Receiver mit einem Timer, der in weniger als 100 Minuten startet, werden in der Auswahl **gelb** hervorgehoben (`Gepl. REC in: X Min`).
* **Unterstützung für schlafende Festplatten:** Hintergrund-Übertragung beim Erstellen von Timern mit verlängerten Timeouts und der Meldung *Verbinde (Festplatte läuft an)...*, damit schlafende Festplatten ohne Timeouts oder Abstürze anlaufen können.

> **Hinweis:** Sollte dein Receiver nach einigen Stunden Laufzeit langsamer werden oder komplett einfrieren, prüfe bitte deine Netzwerkfreigaben — oft sind auf einer Remote-Box versehentlich zwei identische Mounts auf dieselbe Festplatte eingerichtet. Lösche in diesem Fall die doppelte Verbindung.