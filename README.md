# RemoteTimerSelect499

A lightweight replacement for the **Partnerbox** plugin for **OpenATV / Enigma2 (Python 3)**.
Schedule, view, and manage timers across your local receiver and up to **4 remote Enigma2 receivers** directly from the EPG — fully configurable using the remote control.

## Features
* **Direct EPG Recording & Cancellation:** Press **REC** on any program in the EPG to choose the local or any remote receiver (with custom start/end margins), or cancel an existing timer or recording directly from the popup menu.
* **EPG Timer Badges:** Programs scheduled on remote receivers are automatically marked with custom receiver tags (e.g. `[B1]`, `[M]`, `[V]`) directly in the EPG list.
* **Unified All Timers Screen:** View all local and remote timers in one chronologically sorted, column-aligned overview (`Date & Time` → `Status` → `Badge` → `Channel | Event`) with color-coded statuses.
* **Remote Control Setup:** Configure up to 4 remote boxes (name, tag, IP address, OpenWebif port, optional login) directly on receiver — settings are saved in `/etc/enigma2/settings`.
* **Automatic & Bulk Cleanup:** Automatically removes finished/failed timers older than X days, plus one-click bulk cleanup across all receivers.
* **Dynamic Remote Recording Path:** Automatically queries each remote receiver for its active recording directory. It prioritizes the folder currently opened in the remote receiver's recordings list, allowing you to instantly and easily change the target recording directory (e.g., via the web interface).

* **All Timers:** Open **Menu → All Timers** (also available under **Timers**, **Extensions**, and **Plugins**). Press **OK** on a timer to delete it, press **RED** on an active recording to choose **STOP REC** or **STOP & DELETE Recording** (stops the recording and deletes the timer + file from disk), or select the top banner to bulk-delete finished and failed timers.

* **Note:** The remote control button for instant recording on the local box remains unchanged — partner boxes are not shown there! Always schedule timers and start instant recordings exclusively via the EPG. There, you can also start an instant recording on the local box by adding an immediate timer (press the **Green** button or REC button on a currently running EPG event).


## Installation

### Option 1: Quick Install via SSH (English version)
Connect to your receiver via SSH as `root` and run:

```bash
mkdir -p /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/__init__.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/EN/__init__.py
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/plugin.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/EN/plugin.py
killall -9 enigma2
```

### Option 1b: Quick Install via SSH (Czech version / Česká verze)
Connect to your receiver via SSH as `root` and run:

```bash
mkdir -p /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/__init__.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/CZ/__init__.py
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/plugin.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/CZ/plugin.py
killall -9 enigma2
```

### Option 1c: Quick Install via SSH (German version / Deutsche Version)
Connect to your receiver via SSH as `root` and run:
```bash
mkdir -p /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/__init__.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/DE/__init__.py
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/plugin.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/DE/plugin.py
killall -9 enigma2
```


### Option 2: Manual Installation
1. Create the directory `/usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/` on your receiver.
2. Copy `__init__.py` and `plugin.py` from either the `EN/` or `CZ/` folder into that directory (keep **UTF-8** encoding and **LF** line endings).
3. Restart Enigma2 GUI (`killall -9 enigma2` or via **Menu → Standby / Restart → Restart GUI**).

> **Note:** After installation, the **All Timers** (**Všechny časovače**) item will appear in the main menu.

## Configuration (Remote Control)
1. Open setup via any of these menus:
   * **Menu → All Timers**, then press **YELLOW** or **MENU**
   * **Menu → Timers → Remote Timers Setup**
   * **Plugins → Remote Timers - Setup**
2. Set your local badge (default: `L`), auto-cleanup days (`0` = disabled), and up to 4 remote boxes:
   * Press **OK** on text fields (name, tag, username, password) to open the virtual keyboard.
   * Enter IP addresses with the number keys (`0–9`). Leave unused slots at `0.0.0.0`.
   * Default OpenWebif port is `80`. Leave username/password empty if authentication is disabled.
3. Press **GREEN** to save. Remote timers sync immediately without restarting GUI.

## Usage
* **EPG:** Highlight an event and press **REC** to schedule or cancel a timer on any configured box.
* **All Timers:** Open **Menu → All Timers** (also available under **Timers**, **Extensions**, and **Plugins**). Press **OK** on a timer to delete it, or select the top banner to bulk-delete finished and failed timers.
*  **Live recording status in receiver selection:** When choosing a receiver to record with, any box that is currently recording is now highlighted in **red** with its recording end time shown on the right (e.g., `REC until: 19:00`).
* **Local receiver tag in EPG (max. 2 characters):** Local timers are now also marked in the EPG in square brackets (e.g., `[L]`) for a unified look alongside OpenATV's native recording icons. The local tag is intentionally limited to a maximum of 2 characters so it does not take up too much space in the EPG program titles.
* **Tip:** If you have multiple receivers, I recommend installing the plugin on all of them so you can schedule and delete timers across all boxes, depending on which one you are currently using.
  
