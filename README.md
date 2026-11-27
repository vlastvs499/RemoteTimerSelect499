# RemoteTimerSelect499

> **Language / Jazyk / Sprache:** **English** | [Čeština (README_CZ.md)](README_CZ.md) | [Deutsch (README_DE.md)](README_DE.md)

A lightweight replacement for the **Partnerbox** plugin for **OpenATV / Enigma2 (Python 3)**.
Schedule, view, and manage timers across your local receiver and up to **4 remote Enigma2 receivers** directly from the EPG or live TV — fully configurable using the remote control.

## Features

* **EPG & Optional Live TV Recording:** Press **REC** in the EPG (or optionally during live TV) to choose the local or any remote receiver, set custom start/end margins, enable **Infinite recording**, or cancel an existing timer.

* **Live Status in Receiver Selection:** Currently recording receivers are highlighted in **red** (`REC until: 19:00` or `REC until: ∞`). Receivers with an upcoming timer within 100 minutes are highlighted in **yellow** (`Plan. REC in: 45 min`).

* **EPG Timer Badges:** Scheduled programs are automatically marked in the EPG with custom receiver tags (e.g., `[L]`, `[M]`, `[V]`).

* **Unified All Timers Screen:** View all local and remote timers in one chronologically sorted overview (`Date & Time` → `Status` → `Badge` → `Channel | Event`) with color-coded statuses, `∞` symbol, and a blinking `[Recording]` indicator for active infinite recordings.

* **Quick End-Time Adjustment:** Press **BLUE** in *All Timers* to adjust the end time of any active or waiting timer (`±1 min` / `±5 min`) with built-in collision protection (1-minute safety buffer before the next waiting timer on the same box).

* **Stop & Delete Recordings:** Press **RED** on an active recording to choose **STOP REC** or **STOP REC & DELETE RECORDING** (stops recording and deletes both timer and file from disk).

* **Dynamic Path & Sleeping HDD Support:** Automatically queries the active recording directory on each remote box and handles spun-down hard drives in the background without timeouts or UI freezes (fully compatible with OpenATV 8.0).

* **Remote Control Setup & Auto-Cleanup:** Configure up to 4 remote boxes directly on the receiver (saved in `/etc/enigma2/settings`) with automatic and one-click bulk cleanup of finished/failed timers.

## Installation

### Option 1: Quick Install via SSH or Telnet (RCC / DCC)

Connect to your receiver via **SSH** or **Telnet** (e.g. using **PuTTY**, **RCC**, or **DCC**) as `root` and run the commands for your preferred language:

#### English version (`EN`)

```bash
mkdir -p /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/__init__.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/EN/__init__.py
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/plugin.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/EN/plugin.py
killall -9 enigma2
```

#### Czech version / Česká verze (`CZ`)

```bash
mkdir -p /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/__init__.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/CZ/__init__.py
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/plugin.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/CZ/plugin.py
killall -9 enigma2
```

#### German version / Deutsche Version (`DE`)

```bash
mkdir -p /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/__init__.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/DE/__init__.py
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/plugin.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/DE/plugin.py
killall -9 enigma2
```

### Option 2: Manual Installation

1. Create the directory `/usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/` on your receiver.

2. Copy `__init__.py` and `plugin.py` from the `EN/`, `CZ/`, or `DE/` folder into that directory (keep **UTF-8** encoding and **LF** line endings).

3. Restart Enigma2 GUI (`killall -9 enigma2` or via **Menu → Standby / Restart → Restart GUI**).

> **Tip:** If you have multiple receivers, install the plugin on all of them so you can manage timers across all boxes from whichever receiver you are currently using.

## Configuration (Remote Control)

1. Open settings via any of these menus:

   * **Menu → All Timers**, then press **YELLOW** or **MENU**

   * **Menu → Timers → Remote Timer Settings**

   * **Plugins → Remote Timer - Settings**

2. Configure your options:

   * **This receiver tag** (max. 2 characters, default: `L`)

   * **Auto-delete finished/failed** in days (`0` = off)

   * **Box selector on REC button (live TV)** (`No` = native OpenATV menu, `Yes` = open receiver selector on live TV)

   * **Up to 4 remote boxes:** press **OK** on text fields for the virtual keyboard, use number keys (`0–9`) for IP addresses (`0.0.0.0` = disabled), default OpenWebif port is `80`.

3. Press **GREEN** to save. Remote timers sync immediately without restarting GUI.

## Usage

* **EPG:** Highlight any program and press **REC** to schedule or cancel a timer on any configured box.

* **Live TV (optional):** If enabled in the partner box settings, pressing **REC** opens this plugin's receivers selector with the list of remote boxes. If the **"Box selector on REC button (live TV)"** option is disabled, the box selector does not open and the receiver behaves in the classic OpenATV way. You can configure this item in the plugin settings, where you enter the IP addresses of the receivers. It's at the top.

* **All Timers (`Menu → All Timers`):**

  * **OK:** Delete the selected timer (or bulk-delete all finished/failed timers via the top banner).

  * **RED:** Stop an active recording (**STOP REC** or **STOP REC & DELETE RECORDING**).

  * **BLUE:** Change the end time of an active or waiting timer (`LEFT/RIGHT` = ±1 min, `UP/DOWN` = ±5 min).

  * **YELLOW / MENU:** Open box setup.

## Changelog

### 26.–27.11.2026

* **Optional Live TV REC button:** Added a configurable setting (*Box selector on REC button (live TV)*) to open the receiver selector directly from live TV (with full OpenATV 8.0 support).

* **Change REC end time (BLUE button):** Added end-time editing for active and waiting timers in *All Timers* with 1-minute collision protection before the next waiting timer on the same box.

* **Infinite recording & blinking indicator:** Added an *Infinite recording* option (24 h), aligned **`∞`** symbol display, and a 1 Hz blinking `[Recording]` indicator in *All Timers*.

* **Upcoming planned REC alert:** If you want to insert a preceding timer on a receiver, it will warn you if the upcoming timer starts recording in less than 100 minutes (Plan. REC in: X min).

* **Sleeping HDD spin-up handling:** Background timer creation with extended timeouts and a *Connecting (spinning up disk)...* notification to prevent freezes/timeouts on spun-down drives.
