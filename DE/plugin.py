# -*- coding: utf-8 -*-
import base64
from datetime import datetime
import inspect
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import NavigationInstance
from enigma import (
    RT_HALIGN_LEFT,
    RT_HALIGN_RIGHT,
    RT_VALIGN_CENTER,
    eListboxPythonMultiContent,
    eServiceCenter,
    eServiceReference,
    eTimer,
    gFont,
    getDesktop,
)
from Components.ActionMap import ActionMap
from Components.ConfigList import ConfigListScreen
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText
from Components.Sources.StaticText import StaticText
from Components.config import (
    ConfigIP,
    ConfigInteger,
    ConfigPassword,
    ConfigSelection,
    ConfigSelectionNumber,
    ConfigSubsection,
    ConfigText,
    ConfigYesNo,
    config,
    configfile,
    getConfigListEntry,
)
from Plugins.Plugin import PluginDescriptor
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen

# Interval aktualizace EPG znacek na pozadi (v sekundach)
CACHE_REFRESH_SEC = 300

# Velikost pisma v souhrnnem prehledu vsech casovacu
TIMER_LIST_FONT_FHD = 42
TIMER_LIST_FONT_HD = 30

_EPG_HOOKED = False
_EPG_LIST_HOOKED = False
_LIVE_REC_HOOKED = False
_BYPASS_LIVE_REC = False
_CACHE_TIMER = None
_CACHE_LOCK = threading.Lock()
_ACTIVE_POLL_TIMERS = []
REMOTE_TIMER_CACHE = []
REMOTE_LOCATIONS_CACHE = {}


def init_plugin_config():
    if not hasattr(config.plugins, "remotetimerselect"):
        config.plugins.remotetimerselect = ConfigSubsection()

    cfg = config.plugins.remotetimerselect
    if not hasattr(cfg, "local_tag"):
        cfg.local_tag = ConfigText(default="L", fixed_size=False)
    if not hasattr(cfg, "auto_cleanup_days"):
        cfg.auto_cleanup_days = ConfigSelectionNumber(0, 30, 1, default=2)
    if not hasattr(cfg, "live_rec_selector"):
        cfg.live_rec_selector = ConfigYesNo(default=False)

    for idx in range(1, 5):
        sec_name = "box%d" % idx
        if not hasattr(cfg, sec_name):
            setattr(cfg, sec_name, ConfigSubsection())
        b_cfg = getattr(cfg, sec_name)
        if not hasattr(b_cfg, "name"):
            b_cfg.name = ConfigText(default="Box%d" % idx, fixed_size=False)
        if not hasattr(b_cfg, "tag"):
            b_cfg.tag = ConfigText(default="B%d" % idx, fixed_size=False)
        if not hasattr(b_cfg, "ip"):
            b_cfg.ip = ConfigIP(default=[0, 0, 0, 0])
        if not hasattr(b_cfg, "port"):
            b_cfg.port = ConfigInteger(default=80, limits=(1, 65535))
        if not hasattr(b_cfg, "user"):
            b_cfg.user = ConfigText(default="", fixed_size=False)
        if not hasattr(b_cfg, "password"):
            b_cfg.password = ConfigPassword(default="", fixed_size=False)


init_plugin_config()


def _ip_list_to_str(ip_val):
    try:
        if not ip_val or len(ip_val) != 4:
            return ""
        if list(ip_val) == [0, 0, 0, 0]:
            return ""
        return "%d.%d.%d.%d" % tuple(ip_val)
    except Exception:
        return ""


def get_local_tag():
    try:
        val = config.plugins.remotetimerselect.local_tag.value.strip()
        return val[:2] if val else "L"
    except Exception:
        return "L"


def get_auto_cleanup_days():
    try:
        return int(config.plugins.remotetimerselect.auto_cleanup_days.value)
    except Exception:
        return 2


def is_live_rec_selector_enabled():
    try:
        return bool(config.plugins.remotetimerselect.live_rec_selector.value)
    except Exception:
        return False


def get_active_boxes():
    cfg = config.plugins.remotetimerselect
    active = []
    for idx in range(1, 5):
        b_cfg = getattr(cfg, "box%d" % idx, None)
        if b_cfg is None:
            continue
        ip_str = _ip_list_to_str(b_cfg.ip.value)
        if not ip_str:
            continue
        name = b_cfg.name.value.strip() or ("Box%d" % idx)
        tag = b_cfg.tag.value.strip() or ("B%d" % idx)
        active.append(
            {
                "name": name,
                "tag": tag,
                "ip": ip_str,
                "port": int(b_cfg.port.value),
                "user": b_cfg.user.value.strip(),
                "password": b_cfg.password.value,
            }
        )
    return active


class RemoteTimerSetupScreen(ConfigListScreen, Screen):
    def __init__(self, session):
        Screen.__init__(self, session)
        self.skinName = ["Setup"]
        self.setTitle("Remote-Timer Einstellungen")

        self["key_red"] = StaticText("Abbrechen")
        self["key_green"] = StaticText("Speichern")
        self["footnote"] = StaticText("OK = Tastatur für Text   |   Grün = Speichern")
        self["description"] = StaticText("")

        cfg = config.plugins.remotetimerselect
        self.list = [
            (
                getConfigListEntry("Kürzel dieses Receivers (max. 2 Zeichen)", cfg.local_tag),
                "Kurzes Kürzel (max. 2 Zeichen) im EPG und in der Timerliste für diesen lokalen Receiver (Standard: L).",
            ),
            (
                getConfigListEntry("Auto-Löschen fertiger/fehlgeschl. Timer (Tage)", cfg.auto_cleanup_days),
                "Nach wie vielen Tagen fertige und fehlgeschlagene Timer automatisch gelöscht werden (0 = aus).",
            ),
            (
                getConfigListEntry("Box-Auswahl mit REC-Taste (Live-TV)", cfg.live_rec_selector),
                "Öffnet beim Drücken von REC im Live-TV die Receiver-Auswahl (aus = Standardverhalten von OpenATV).",
            ),
        ]

        for idx in range(1, 5):
            b_cfg = getattr(cfg, "box%d" % idx)
            self.list.append(
                (
                    getConfigListEntry("Box %d - Receiver-Name" % idx, b_cfg.name),
                    "Name der %d. Remote-Box im Menü und in Meldungen (z. B. Wohnzimmer oder SF8008)." % idx,
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - Kürzel (Tag)" % idx, b_cfg.tag),
                    "Kurzes Kürzel im EPG und in der Timerliste für Box %d (z. B. M, V, B%d)." % (idx, idx),
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - IP-Adresse (0.0.0.0 = aus)" % idx, b_cfg.ip),
                    "IP-Adresse der %d. Box im lokalen Netzwerk (Zifferntasten). 0.0.0.0 = deaktiviert." % idx,
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - OpenWebif HTTP-Port" % idx, b_cfg.port),
                    "HTTP-Port von OpenWebif auf Box %d (Standard ist 80)." % idx,
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - OpenWebif Benutzer" % idx, b_cfg.user),
                    "Benutzername für OpenWebif (leer lassen, wenn kein Passwort aktiv ist).",
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - OpenWebif Passwort" % idx, b_cfg.password),
                    "Passwort für OpenWebif auf Box %d (leer lassen, wenn nicht erforderlich)." % idx,
                )
            )

        self.cfg_entries = [item[0] for item in self.list]
        self.help_texts = [item[1] for item in self.list]

        ConfigListScreen.__init__(self, self.cfg_entries, session=session)

        self["actions"] = ActionMap(
            ["SetupActions", "ColorActions"],
            {
                "save": self.keySave,
                "green": self.keySave,
                "cancel": self.keyCancel,
                "red": self.keyCancel,
            },
            -2,
        )

        try:
            self["config"].onSelectionChanged.append(self._update_help)
        except Exception:
            pass
        self.onLayoutFinish.append(self._update_help)

    def _update_help(self):
        try:
            idx = self["config"].getCurrentIndex()
            if 0 <= idx < len(self.help_texts):
                self["description"].setText(self.help_texts[idx])
        except Exception:
            pass

    def keySave(self):
        for entry in self.cfg_entries:
            try:
                entry[1].save()
            except Exception:
                pass
        try:
            config.plugins.remotetimerselect.save()
            configfile.save()
        except Exception:
            pass
        sync_timer_cache_async()
        self.close(True)

    def keyCancel(self):
        for entry in self.cfg_entries:
            try:
                entry[1].cancel()
            except Exception:
                pass
        self.close(False)


def open_setup_screen(session, callback=None, **kwargs):
    def _on_closed(saved):
        if callable(callback):
            callback(saved)

    session.openWithCallback(_on_closed, RemoteTimerSetupScreen)


class BoxSelectorScreen(Screen):
    def __init__(self, session, title, items):
        Screen.__init__(self, session)
        self.setTitle(title)

        desktop_w = 1920
        desktop_h = 1080
        try:
            sz = getDesktop(0).size()
            desktop_w = sz.width()
            desktop_h = sz.height()
        except Exception:
            pass

        is_fhd = desktop_w >= 1920
        visible_rows = max(3, min(10, len(items)))

        if is_fhd:
            font_sz = 36
            item_h = 56
            win_w = 1180
            pad_x = 30
            title_h = 50
            list_y = 80
            list_h = visible_rows * item_h
            win_h = list_y + list_h + 30
            right_w = 420
            title_font = 32
        else:
            font_sz = 25
            item_h = 40
            win_w = 820
            pad_x = 20
            title_h = 36
            list_y = 58
            list_h = visible_rows * item_h
            win_h = list_y + list_h + 22
            right_w = 300
            title_font = 22

        pos_x = max(20, (desktop_w - win_w) // 2)
        pos_y = max(20, (desktop_h - win_h) // 2)
        list_w = win_w - (2 * pad_x)

        self.skin = (
            '<screen name="BoxSelectorScreen" position="%d,%d" size="%d,%d" title="%s">'
            '<widget source="title_text" render="Label" position="%d,15" size="%d,%d" font="Regular;%d" foregroundColor="#00ffcc33" noWrap="1" />'
            '<widget name="list" position="%d,%d" size="%d,%d" font="Regular;%d" itemHeight="%d" scrollbarMode="showOnDemand" enableWrapAround="1" />'
            "</screen>"
        ) % (
            pos_x,
            pos_y,
            win_w,
            win_h,
            title.replace('"', "&quot;"),
            pad_x,
            list_w,
            title_h,
            title_font,
            pad_x,
            list_y,
            list_w,
            list_h,
            font_sz,
            item_h,
        )

        mc_entries = []
        flags_l = RT_HALIGN_LEFT | RT_VALIGN_CENTER
        flags_r = RT_HALIGN_RIGHT | RT_VALIGN_CENTER

        for left_txt, right_txt, color, payload in items:
            if right_txt:
                left_w = list_w - right_w - 20
                entry = [
                    (left_txt, payload),
                    MultiContentEntryText(
                        pos=(10, 0),
                        size=(left_w, item_h),
                        font=0,
                        flags=flags_l,
                        text=left_txt,
                        color=color,
                    ),
                    MultiContentEntryText(
                        pos=(list_w - right_w - 10, 0),
                        size=(right_w, item_h),
                        font=0,
                        flags=flags_r,
                        text=right_txt,
                        color=color,
                    ),
                ]
            else:
                entry = [
                    (left_txt, payload),
                    MultiContentEntryText(
                        pos=(10, 0),
                        size=(list_w - 20, item_h),
                        font=0,
                        flags=flags_l,
                        text=left_txt,
                        color=color,
                    ),
                ]
            mc_entries.append(entry)

        self["title_text"] = StaticText(title)
        self["list"] = MenuList(
            mc_entries,
            enableWrapAround=True,
            content=eListboxPythonMultiContent,
        )
        self["list"].l.setFont(0, gFont("Regular", font_sz))
        self["list"].l.setItemHeight(item_h)

        self["actions"] = ActionMap(
            ["OkCancelActions"],
            {
                "ok": self.keyOk,
                "cancel": self.keyCancel,
            },
            -1,
        )

    def keyOk(self):
        cur = self["list"].getCurrent()
        if cur:
            self.close(cur[0])

    def keyCancel(self):
        self.close(None)


def _state_color(state_txt):
    colors = {
        "Aufnahme": 0x00FF6666,
        "Wartet": 0x0077DD77,
        "Fertig": 0x0088CCFF,
        "Fehler": 0x00FFAA44,
        "Vorbereit.": 0x00FFEE66,
        "Deaktiv.": 0x00999999,
    }
    return colors.get(state_txt, None)


def _is_infinite_recording(timer_item):
    if not isinstance(timer_item, dict):
        return False
    if timer_item.get("state") != "2":
        return False
    b_ts = int(timer_item.get("begin") or 0)
    e_ts = int(timer_item.get("end") or 0)
    return b_ts > 0 and (e_ts - b_ts) >= 82800


def _build_banner_entry(payload, text, is_fhd, item_h, color=0x00FFCC33):
    list_w = 1770 if is_fhd else 1190
    flags = RT_HALIGN_LEFT | RT_VALIGN_CENTER
    return [
        payload,
        MultiContentEntryText(
            pos=(5, 0),
            size=(list_w - 10, item_h),
            font=0,
            flags=flags,
            text=text,
            color=color,
        ),
    ]


def _build_timer_entry(timer_item, is_fhd, item_h, blink_hide=False):
    flags = RT_HALIGN_LEFT | RT_VALIGN_CENTER
    time_txt = timer_item["time_txt"]
    if blink_hide and _is_infinite_recording(timer_item):
        state_txt = ""
    else:
        state_txt = "[%s]" % timer_item["state_txt"] if timer_item.get("state_txt") else ""
    tag_txt = "[%s]" % timer_item["tag"]
    detail_txt = "%s  |  %s" % (timer_item["sname"], timer_item["name"])
    st_color = _state_color(timer_item.get("state_txt", ""))

    # Poradi sloupcu: 1. Datum a cas, 2. Stav, 3. Znacka prijimace, 4. Kanal | Nazev poradu
    if is_fhd:
        col1_x, col1_w = 5, 355
        col2_x, col2_w = 370, 225
        col3_x, col3_w = 605, 135
        col4_x, col4_w = 750, 1015
    else:
        col1_x, col1_w = 5, 250
        col2_x, col2_w = 260, 165
        col3_x, col3_w = 430, 95
        col4_x, col4_w = 530, 655

    return [
        timer_item,
        MultiContentEntryText(
            pos=(col1_x, 0),
            size=(col1_w, item_h),
            font=0,
            flags=flags,
            text=time_txt,
        ),
        MultiContentEntryText(
            pos=(col2_x, 0),
            size=(col2_w, item_h),
            font=0,
            flags=flags,
            text=state_txt,
            color=st_color,
        ),
        MultiContentEntryText(
            pos=(col3_x, 0),
            size=(col3_w, item_h),
            font=0,
            flags=flags,
            text=tag_txt,
        ),
        MultiContentEntryText(
            pos=(col4_x, 0),
            size=(col4_w, item_h),
            font=0,
            flags=flags,
            text=detail_txt,
        ),
    ]


class CombinedTimersScreen(Screen):
    def __init__(self, session, title, rows_spec):
        Screen.__init__(self, session)
        self.setTitle("Alle Timer")
        self.rows_spec = rows_spec
        self._blink_hidden = False
        self._blink_timer = None

        desktop_w = 1920
        try:
            desktop_w = getDesktop(0).size().width()
        except Exception:
            pass

        is_fhd = desktop_w >= 1920
        self.is_fhd = is_fhd
        if is_fhd:
            font_sz = int(TIMER_LIST_FONT_FHD)
            item_h = int(font_sz * 1.42)
            rows_h = (840 // item_h) * item_h
            self.skin = (
                '<screen name="CombinedTimersScreen" position="50,55" size="1820,970" title="Alle Timer">'
                '<widget source="title_text" render="Label" position="25,15" size="1770,50" font="Regular;34" foregroundColor="#00ffcc33" noWrap="1" />'
                '<widget name="list" position="25,75" size="1770,%d" font="Regular;%d" itemHeight="%d" scrollbarMode="showOnDemand" enableWrapAround="1" />'
                '<widget source="hint_ok" render="Label" position="25,922" size="195,38" font="Regular;26" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_red" render="Label" position="220,922" size="85,38" font="Regular;26" foregroundColor="#00ff5555" noWrap="1" />'
                '<widget source="hint_stop" render="Label" position="305,922" size="175,38" font="Regular;26" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_yellow" render="Label" position="480,922" size="85,38" font="Regular;26" foregroundColor="#00ffdd33" noWrap="1" />'
                '<widget source="hint_setup" render="Label" position="565,922" size="230,38" font="Regular;26" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_blue" render="Label" position="795,922" size="85,38" font="Regular;26" foregroundColor="#0055aaff" noWrap="1" />'
                '<widget source="hint_rest" render="Label" position="880,922" size="915,38" font="Regular;26" foregroundColor="#00aaaaaa" noWrap="1" />'
                "</screen>"
            ) % (rows_h, font_sz, item_h)
        else:
            font_sz = int(TIMER_LIST_FONT_HD)
            item_h = int(font_sz * 1.40)
            rows_h = (546 // item_h) * item_h
            self.skin = (
                '<screen name="CombinedTimersScreen" position="30,35" size="1220,650" title="Alle Timer">'
                '<widget source="title_text" render="Label" position="15,10" size="1190,36" font="Regular;24" foregroundColor="#00ffcc33" noWrap="1" />'
                '<widget name="list" position="15,52" size="1190,%d" font="Regular;%d" itemHeight="%d" scrollbarMode="showOnDemand" enableWrapAround="1" />'
                '<widget source="hint_ok" render="Label" position="15,606" size="140,32" font="Regular;18" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_red" render="Label" position="155,606" size="60,32" font="Regular;18" foregroundColor="#00ff5555" noWrap="1" />'
                '<widget source="hint_stop" render="Label" position="215,606" size="125,32" font="Regular;18" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_yellow" render="Label" position="340,606" size="62,32" font="Regular;18" foregroundColor="#00ffdd33" noWrap="1" />'
                '<widget source="hint_setup" render="Label" position="402,606" size="165,32" font="Regular;18" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_blue" render="Label" position="567,606" size="62,32" font="Regular;18" foregroundColor="#0055aaff" noWrap="1" />'
                '<widget source="hint_rest" render="Label" position="629,606" size="580,32" font="Regular;18" foregroundColor="#00aaaaaa" noWrap="1" />'
                "</screen>"
            ) % (rows_h, font_sz, item_h)

        self.item_h = item_h
        mc_entries = self._build_entries(blink_hide=False)

        self["title_text"] = StaticText(title)
        self["hint_ok"] = StaticText("OK = löschen  |")
        self["hint_red"] = StaticText("ROT")
        self["hint_stop"] = StaticText("= Stop REC  |")
        self["hint_yellow"] = StaticText("GELB")
        self["hint_setup"] = StaticText("/ MENU = Boxen  |")
        self["hint_blue"] = StaticText("BLAU")
        self["hint_rest"] = StaticText("= REC-Ende ändern  |  EXIT = schließen")
        self["list"] = MenuList(
            mc_entries,
            enableWrapAround=True,
            content=eListboxPythonMultiContent,
        )
        self["list"].l.setFont(0, gFont("Regular", font_sz))
        self["list"].l.setItemHeight(item_h)

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "MenuActions"],
            {
                "ok": self.keyOk,
                "cancel": self.keyCancel,
                "red": self.keyRed,
                "yellow": self.keySetup,
                "blue": self.keyBlue,
                "menu": self.keySetup,
            },
            -1,
        )

        has_inf_rec = any(
            row_type == "TIMER" and _is_infinite_recording(payload)
            for row_type, payload, _text in rows_spec
        )
        if has_inf_rec:
            try:
                self._blink_timer = eTimer()
                self._blink_timer.callback.append(self._toggle_blink)
                self._blink_timer.start(500, False)
            except Exception:
                self._blink_timer = None

        self.onClose.append(self._stop_blink_timer)

    def _build_entries(self, blink_hide=False):
        mc_entries = []
        for row_type, payload, text in self.rows_spec:
            if row_type == "TIMER":
                mc_entries.append(
                    _build_timer_entry(
                        payload, self.is_fhd, self.item_h, blink_hide=blink_hide
                    )
                )
            else:
                b_color = 0x00FF7777 if payload == "OFFLINE_INFO" else 0x00FFCC33
                mc_entries.append(
                    _build_banner_entry(
                        payload, text, self.is_fhd, self.item_h, color=b_color
                    )
                )
        return mc_entries

    def _toggle_blink(self):
        try:
            self._blink_hidden = not self._blink_hidden
            idx = self["list"].getSelectedIndex()
            self["list"].setList(self._build_entries(blink_hide=self._blink_hidden))
            if idx is not None and idx >= 0:
                self["list"].moveToIndex(idx)
        except Exception:
            pass

    def _stop_blink_timer(self):
        if self._blink_timer is not None:
            try:
                self._blink_timer.stop()
            except Exception:
                pass
            self._blink_timer = None

    def keyOk(self):
        cur = self["list"].getCurrent()
        if cur:
            self.close(("SELECT", cur[0]))

    def keyRed(self):
        cur = self["list"].getCurrent()
        if cur:
            self.close(("STOP_REC", cur[0]))

    def keyBlue(self):
        cur = self["list"].getCurrent()
        if cur:
            self.close(("CHANGE_END", cur[0]))

    def keySetup(self):
        self.close(("OPEN_SETUP", None))

    def keyCancel(self):
        self.close(None)


class ChangeTimerEndScreen(Screen):
    def __init__(self, session, timer_item, max_end_ts=None, next_timer_info=""):
        Screen.__init__(self, session)
        self.setTitle("REC-Ende ändern")
        self.timer_item = timer_item
        self.orig_end = int(timer_item["end"])
        self.cur_end = self.orig_end
        now_ts = int(time.time())
        self.min_end = max(int(timer_item["begin"]) + 60, now_ts + 60)
        if self.min_end > self.orig_end:
            self.min_end = self.orig_end
        self.max_end = int(max_end_ts) if max_end_ts else None

        desktop_w = 1920
        desktop_h = 1080
        try:
            sz = getDesktop(0).size()
            desktop_w = sz.width()
            desktop_h = sz.height()
        except Exception:
            pass

        is_fhd = desktop_w >= 1920
        if is_fhd:
            win_w, win_h = 1100, 440
            pad_x = 40
            f_title, f_info, f_time, f_limit, f_hint = 34, 30, 52, 26, 26
            y_title, y_info, y_time, y_limit, y_hint = 25, 95, 175, 285, 365
            h_title, h_info, h_time, h_limit, h_hint = 50, 50, 75, 45, 45
        else:
            win_w, win_h = 780, 320
            pad_x = 28
            f_title, f_info, f_time, f_limit, f_hint = 24, 21, 36, 18, 18
            y_title, y_info, y_time, y_limit, y_hint = 18, 68, 125, 205, 262
            h_title, h_info, h_time, h_limit, h_hint = 36, 36, 55, 34, 34

        pos_x = max(20, (desktop_w - win_w) // 2)
        pos_y = max(20, (desktop_h - win_h) // 2)
        inner_w = win_w - (2 * pad_x)

        self.skin = (
            '<screen name="ChangeTimerEndScreen" position="%d,%d" size="%d,%d" title="REC-Ende ändern">'
            '<widget source="title_lbl" render="Label" position="%d,%d" size="%d,%d" font="Regular;%d" foregroundColor="#00ffcc33" noWrap="1" />'
            '<widget source="info_lbl" render="Label" position="%d,%d" size="%d,%d" font="Regular;%d" foregroundColor="#00cccccc" noWrap="1" />'
            '<widget source="time_lbl" render="Label" position="%d,%d" size="%d,%d" font="Regular;%d" foregroundColor="#00ffffff" halign="center" noWrap="1" />'
            '<widget source="limit_lbl" render="Label" position="%d,%d" size="%d,%d" font="Regular;%d" foregroundColor="#00ffaa44" halign="center" noWrap="1" />'
            '<widget source="hint_lbl" render="Label" position="%d,%d" size="%d,%d" font="Regular;%d" foregroundColor="#00aaaaaa" halign="center" noWrap="1" />'
            "</screen>"
        ) % (
            pos_x, pos_y, win_w, win_h,
            pad_x, y_title, inner_w, h_title, f_title,
            pad_x, y_info, inner_w, h_info, f_info,
            pad_x, y_time, inner_w, h_time, f_time,
            pad_x, y_limit, inner_w, h_limit, f_limit,
            pad_x, y_hint, inner_w, h_hint, f_hint,
        )

        self["title_lbl"] = StaticText(
            "REC-Ende ändern [%s]: %s" % (timer_item["tag"], timer_item["name"])
        )
        try:
            dt_b = datetime.fromtimestamp(int(timer_item["begin"]))
            begin_str = dt_b.strftime("%d.%m %H:%M")
        except Exception:
            begin_str = "??:??"
        self["info_lbl"] = StaticText(
            "%s  |  Start: %s" % (timer_item["sname"], begin_str)
        )
        self["time_lbl"] = StaticText("")
        self["limit_lbl"] = StaticText(next_timer_info)
        self["hint_lbl"] = StaticText(
            "LINKS/RECHTS = ±1 Min  |  HOCH/RUNTER = ±5 Min  |  OK = speichern  |  EXIT = abbrechen"
        )

        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions"],
            {
                "left": lambda: self._shift_minutes(-1),
                "right": lambda: self._shift_minutes(1),
                "down": lambda: self._shift_minutes(-5),
                "up": lambda: self._shift_minutes(5),
                "ok": self.keySave,
                "green": self.keySave,
                "cancel": self.keyCancel,
                "red": self.keyCancel,
            },
            -1,
        )

        self._refresh_display()

    def _refresh_display(self):
        try:
            dt_e = datetime.fromtimestamp(self.cur_end)
            end_str = dt_e.strftime("%d.%m %H:%M")
        except Exception:
            end_str = "??:??"
        diff_min = (self.cur_end - self.orig_end) // 60
        if diff_min > 0:
            diff_str = " (+%d Min)" % diff_min
        elif diff_min < 0:
            diff_str = " (%d Min)" % diff_min
        else:
            diff_str = " (unverändert)"
        self["time_lbl"].setText("Neues Ende: %s%s" % (end_str, diff_str))

    def _shift_minutes(self, delta_min):
        new_ts = self.cur_end + (delta_min * 60)
        if delta_min > 0 and self.max_end is not None and new_ts >= self.max_end:
            self.cur_end = max(self.min_end, self.max_end)
            self._refresh_display()
            self.session.open(
                MessageBox,
                "ACHTUNG! Startzeit des nächsten wartenden Timers erreicht!!!",
                MessageBox.TYPE_WARNING,
                timeout=5,
            )
            return
        if new_ts < self.min_end:
            new_ts = self.min_end
        self.cur_end = new_ts
        self._refresh_display()

    def keySave(self):
        if self.cur_end == self.orig_end:
            self.close(None)
        else:
            self.close(self.cur_end)

    def keyCancel(self):
        self.close(None)


class RemoteTimerMarginScreen(ConfigListScreen, Screen):
    def __init__(self, session, box, timer_data, default_before, default_after, existing_timer=None):
        Screen.__init__(self, session)
        self.existing_timer = existing_timer
        box_title = box["name"] if box is not None else "Dieser Receiver"
        win_title = "Vor-/Nachlauf (%s)" % box_title
        self.setTitle(win_title)

        desktop_w = 1920
        desktop_h = 1080
        try:
            sz = getDesktop(0).size()
            desktop_w = sz.width()
            desktop_h = sz.height()
        except Exception:
            pass

        is_fhd = desktop_w >= 1920
        if is_fhd:
            win_w, win_h = 1360, 620
            pad_x = 35
            inner_w = win_w - (2 * pad_x)
            self.skin = (
                '<screen name="RemoteTimerMarginScreen" position="%d,%d" size="%d,%d" title="%s">'
                '<widget source="title_lbl" render="Label" position="%d,20" size="%d,48" font="Regular;34" foregroundColor="#00ffcc33" noWrap="1" />'
                '<widget source="event_lbl" render="Label" position="%d,72" size="%d,40" font="Regular;28" foregroundColor="#00ffffff" noWrap="1" />'
                '<widget name="config" position="%d,125" size="%d,220" font="Regular;30" itemHeight="52" scrollbarMode="showOnDemand" enableWrapAround="1" />'
                '<widget source="description" render="Label" position="%d,365" size="%d,175" font="Regular;26" foregroundColor="#00dddddd" />'
                '<widget source="key_red" render="Label" position="%d,555" size="250,42" font="Regular;28" foregroundColor="#00ff5555" noWrap="1" />'
                '<widget source="key_green" render="Label" position="%d,555" size="260,42" font="Regular;28" foregroundColor="#0055ff55" noWrap="1" />'
                '<widget source="footnote" render="Label" position="%d,558" size="%d,38" font="Regular;24" foregroundColor="#00aaaaaa" halign="right" noWrap="1" />'
                "</screen>"
            ) % (
                max(20, (desktop_w - win_w) // 2),
                max(20, (desktop_h - win_h) // 2),
                win_w,
                win_h,
                win_title.replace('"', "&quot;"),
                pad_x, inner_w,
                pad_x, inner_w,
                pad_x, inner_w,
                pad_x, inner_w,
                pad_x,
                pad_x + 270,
                pad_x + 550, inner_w - 550,
            )
        else:
            win_w, win_h = 960, 440
            pad_x = 24
            inner_w = win_w - (2 * pad_x)
            self.skin = (
                '<screen name="RemoteTimerMarginScreen" position="%d,%d" size="%d,%d" title="%s">'
                '<widget source="title_lbl" render="Label" position="%d,14" size="%d,34" font="Regular;24" foregroundColor="#00ffcc33" noWrap="1" />'
                '<widget source="event_lbl" render="Label" position="%d,50" size="%d,28" font="Regular;20" foregroundColor="#00ffffff" noWrap="1" />'
                '<widget name="config" position="%d,88" size="%d,156" font="Regular;21" itemHeight="38" scrollbarMode="showOnDemand" enableWrapAround="1" />'
                '<widget source="description" render="Label" position="%d,258" size="%d,125" font="Regular;18" foregroundColor="#00dddddd" />'
                '<widget source="key_red" render="Label" position="%d,394" size="175,30" font="Regular;20" foregroundColor="#00ff5555" noWrap="1" />'
                '<widget source="key_green" render="Label" position="%d,394" size="185,30" font="Regular;20" foregroundColor="#0055ff55" noWrap="1" />'
                '<widget source="footnote" render="Label" position="%d,396" size="%d,28" font="Regular;17" foregroundColor="#00aaaaaa" halign="right" noWrap="1" />'
                "</screen>"
            ) % (
                max(20, (desktop_w - win_w) // 2),
                max(20, (desktop_h - win_h) // 2),
                win_w,
                win_h,
                win_title.replace('"', "&quot;"),
                pad_x, inner_w,
                pad_x, inner_w,
                pad_x, inner_w,
                pad_x, inner_w,
                pad_x,
                pad_x + 190,
                pad_x + 390, inner_w - 390,
            )

        self["title_lbl"] = StaticText(win_title)
        self["event_lbl"] = StaticText(timer_data["name"])
        red_label = "ROT = Stop REC" if self.existing_timer is not None else "ROT = Abbrechen"
        self["key_red"] = StaticText(red_label)
        self["key_green"] = StaticText("GRÜN = Aufnehmen")
        self["footnote"] = StaticText("LINKS/RECHTS = ändern  |  OK = aufnehmen")
        self["description"] = StaticText(
            "Wenn Sie sich in der Aufnahmeliste in einem anderen Ordner befinden als dem Standard-Aufnahmepfad, "
            "können Sie in der letzten Zeile mit den Pfeiltasten LINKS/RECHTS sofort den Aufnahmeordner wechseln. "
            "Es stehen immer der Standardordner oder der aktuell geöffnete Ordner zur Verfügung."
        )

        val_before = max(0, min(120, int(default_before)))
        val_after = max(0, min(180, int(default_after)))

        self.cfg_before = ConfigSelectionNumber(0, 120, 1, default=val_before)
        self.cfg_after = ConfigSelectionNumber(0, 180, 1, default=val_after)
        self.cfg_infinite = ConfigYesNo(default=False)

        if box is None:
            local_locs = get_local_locations_list()
            if local_locs:
                loc_choices = [(p, p) for p in local_locs]
            else:
                loc_choices = [("", "Standardpfad des Receivers")]
        else:
            cached_locs = get_cached_remote_locations(box)
            if cached_locs:
                loc_choices = [(p, p) for p in cached_locs]
            else:
                loc_choices = [("", "Automatisch (aktuell auf Box)")]
                sync_timer_cache_async()
        self.cfg_dirname = ConfigSelection(default=loc_choices[0][0], choices=loc_choices)

        self.list = [
            getConfigListEntry("Vorlauf vor Sendung (Min)", self.cfg_before),
            getConfigListEntry("Nachlauf nach Sendung (Min)", self.cfg_after),
            getConfigListEntry("Unendliche Aufnahme", self.cfg_infinite),
            getConfigListEntry("Aufnahmepfad", self.cfg_dirname),
        ]

        ConfigListScreen.__init__(self, self.list, session=session)

        # Vyssi priorita (-3) pro barevna tlacitka, aby RED nesezralo SetupActions/cancel
        self["color_actions"] = ActionMap(
            ["ColorActions"],
            {
                "green": self.keySave,
                "red": self.keyRed,
            },
            -3,
        )
        self["actions"] = ActionMap(
            ["OkCancelActions"],
            {
                "ok": self.keySave,
                "cancel": self.keyCancel,
            },
            -2,
        )

    def keySave(self):
        self.close(
            (
                int(self.cfg_before.value),
                int(self.cfg_after.value),
                bool(self.cfg_infinite.value),
                str(self.cfg_dirname.value or ""),
            )
        )

    def keyRed(self):
        if self.existing_timer is not None:
            self.close(("DELETE_EXISTING", self.existing_timer))
        else:
            self.close(None)

    def keyCancel(self):
        self.close(None)


def _build_request(box, url):
    req = urllib.request.Request(url)
    if box.get("user"):
        creds = "%s:%s" % (box["user"], box.get("password", ""))
        b64_creds = base64.b64encode(creds.encode("utf-8")).decode("ascii")
        req.add_header("Authorization", "Basic %s" % b64_creds)
    return req


def _xml_text(parent, tag, default=""):
    el = parent.find(tag)
    if el is not None and el.text is not None:
        return el.text.strip()
    return default


def _normalize_sref(sref):
    if not sref:
        return ""
    s = str(sref).strip()
    parts = s.split(":")
    if len(parts) >= 10:
        return ":".join(parts[:10]).upper()
    return s.upper()


def get_sref_string(srv):
    if srv is None:
        return ""
    if hasattr(srv, "ref") and hasattr(srv.ref, "toString"):
        return srv.ref.toString()
    if hasattr(srv, "toString"):
        return srv.toString()
    return str(srv)


def get_default_margins_minutes():
    try:
        margin_before = int(config.recording.margin_before.value)
    except Exception:
        margin_before = 0
    try:
        margin_after = int(config.recording.margin_after.value)
    except Exception:
        margin_after = 0
    return margin_before, margin_after


def get_local_locations_list():
    locations = []

    def _add_path(p):
        if not p:
            return
        s = str(p).strip()
        if not s or not s.startswith("/"):
            return
        if not s.endswith("/"):
            s += "/"
        if s not in locations:
            locations.append(s)

    try:
        if hasattr(config, "movielist") and hasattr(config.movielist, "last_videodir"):
            _add_path(config.movielist.last_videodir.value)
    except Exception:
        pass

    try:
        if hasattr(config, "usage") and hasattr(config.usage, "default_path"):
            _add_path(config.usage.default_path.value)
    except Exception:
        pass

    try:
        if hasattr(config, "usage") and hasattr(config.usage, "timer_path"):
            _add_path(config.usage.timer_path.value)
    except Exception:
        pass

    try:
        if hasattr(config, "movielist") and hasattr(config.movielist, "videodirs"):
            vdirs = config.movielist.videodirs.value
            if isinstance(vdirs, (list, tuple)):
                for d in vdirs:
                    _add_path(d)
    except Exception:
        pass

    if not locations:
        _add_path("/media/hdd/movie/")

    return locations


def fetch_remote_locations_list(box, timeout=4):
    locations = []
    for endpoint in ("/web/getcurrlocation", "/web/getlocations"):
        try:
            url = "http://%s:%d%s" % (box["ip"], box["port"], endpoint)
            req = _build_request(box, url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            for loc in root.findall("e2location"):
                if loc.text and loc.text.strip():
                    path = loc.text.strip()
                    if path not in locations:
                        locations.append(path)
        except Exception:
            pass
    return locations


def get_cached_remote_locations(box):
    key = (box.get("ip", ""), int(box.get("port", 80)))
    with _CACHE_LOCK:
        return list(REMOTE_LOCATIONS_CACHE.get(key, []))


def fetch_remote_dirname(box, timeout=10):
    for endpoint in ("/web/getcurrlocation", "/web/getlocations"):
        try:
            url = "http://%s:%d%s" % (box["ip"], box["port"], endpoint)
            req = _build_request(box, url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            for loc in root.findall("e2location"):
                if loc.text and loc.text.strip():
                    return loc.text.strip()
        except Exception:
            pass
    return None


def _sync_timer_cache_worker():
    global REMOTE_TIMER_CACHE
    new_items = []
    new_locations = {}
    for box in get_active_boxes():
        try:
            url = "http://%s:%d/web/timerlist" % (box["ip"], box["port"])
            req = _build_request(box, url)
            with urllib.request.urlopen(req, timeout=4) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            tag = box.get("tag", box["name"][:2].upper())
            for item in root.findall("e2timer"):
                state_str = _xml_text(item, "e2state", "0")
                disabled_str = _xml_text(item, "e2disabled", "0")
                if disabled_str == "1" or state_str == "3":
                    continue
                raw_sref = _xml_text(item, "e2servicereference")
                sref = _normalize_sref(raw_sref)
                name = _xml_text(item, "e2name", "Ohne Titel")
                eit_str = _xml_text(item, "e2eit", "0")
                begin_str = _xml_text(item, "e2timebegin", "0")
                end_str = _xml_text(item, "e2timeend", "0")
                try:
                    b_ts = int(float(begin_str))
                    e_ts = int(float(end_str))
                    eit_val = int(float(eit_str)) if eit_str else 0
                    new_items.append(
                        {
                            "box": box,
                            "tag": tag,
                            "state": state_str,
                            "sref": sref,
                            "raw_sref": raw_sref,
                            "eit": eit_val,
                            "begin": b_ts,
                            "end": e_ts,
                            "name": name,
                        }
                    )
                except Exception:
                    pass
        except Exception:
            pass

        try:
            locs = fetch_remote_locations_list(box, timeout=4)
            if locs:
                new_locations[(box["ip"], int(box["port"]))] = locs
        except Exception:
            pass

    with _CACHE_LOCK:
        REMOTE_TIMER_CACHE = new_items
        for k, v in new_locations.items():
            REMOTE_LOCATIONS_CACHE[k] = v


def sync_timer_cache_async():
    try:
        t = threading.Thread(target=_sync_timer_cache_worker, daemon=True)
        t.start()
    except Exception:
        pass


def _format_until_time(end_ts):
    try:
        if int(end_ts) < 0:
            return "REC bis: \u221e"
        dt = datetime.fromtimestamp(int(end_ts))
        return "REC bis: %d:%02d" % (dt.hour, dt.minute)
    except Exception:
        return ""


def _format_plan_in_minutes(begin_ts):
    try:
        now_ts = int(time.time())
        diff = int(begin_ts) - now_ts
        if diff <= 0 or diff >= 100 * 60:
            return ""
        mins = max(1, (diff + 59) // 60)
        if mins >= 100:
            return ""
        return "Gepl. REC in: %d Min" % mins
    except Exception:
        return ""


def get_local_recording_end_ts(session):
    now_ts = int(time.time())
    max_end = 0
    try:
        rec_timer = getattr(session.nav, "RecordTimer", None)
        if rec_timer is not None:
            for t in list(getattr(rec_timer, "timer_list", [])):
                if getattr(t, "disabled", False):
                    continue
                if str(getattr(t, "state", 0)) == "2":
                    t_begin = int(getattr(t, "begin", 0))
                    t_end = int(getattr(t, "end", 0))
                    if t_end > now_ts:
                        if t_begin > 0 and (t_end - t_begin) >= 82800:
                            return -1
                        if t_end > max_end:
                            max_end = t_end
    except Exception:
        pass
    return max_end


def get_local_next_timer_begin_ts(session):
    now_ts = int(time.time())
    min_begin = 0
    try:
        rec_timer = getattr(session.nav, "RecordTimer", None)
        if rec_timer is not None:
            for t in list(getattr(rec_timer, "timer_list", [])):
                if getattr(t, "disabled", False):
                    continue
                if str(getattr(t, "state", 0)) in ("2", "3"):
                    continue
                t_begin = int(getattr(t, "begin", 0))
                if t_begin > now_ts:
                    if min_begin == 0 or t_begin < min_begin:
                        min_begin = t_begin
    except Exception:
        pass
    return min_begin


def get_remote_recording_end_ts(box):
    now_ts = int(time.time())
    max_end = 0
    with _CACHE_LOCK:
        snapshot = list(REMOTE_TIMER_CACHE)

    for t in snapshot:
        t_box = t.get("box")
        if not t_box:
            continue
        if t_box.get("ip") != box.get("ip") or t_box.get("port") != box.get("port"):
            continue
        is_rec = (t.get("state") == "2") or (t["begin"] <= now_ts < t["end"])
        if is_rec and t["end"] > now_ts:
            if t["begin"] > 0 and (t["end"] - t["begin"]) >= 82800:
                return -1
            if t["end"] > max_end:
                max_end = t["end"]
    return max_end


def get_remote_next_timer_begin_ts(box):
    now_ts = int(time.time())
    min_begin = 0
    with _CACHE_LOCK:
        snapshot = list(REMOTE_TIMER_CACHE)

    for t in snapshot:
        t_box = t.get("box")
        if not t_box:
            continue
        if t_box.get("ip") != box.get("ip") or t_box.get("port") != box.get("port"):
            continue
        if t.get("state") in ("2", "3"):
            continue
        t_begin = int(t.get("begin", 0))
        if t_begin > now_ts:
            if min_begin == 0 or t_begin < min_begin:
                min_begin = t_begin
    return min_begin


def get_epg_marks(service, event_id, begin_time, duration):
    if not service or begin_time is None or duration is None:
        return ""
    sref = _normalize_sref(get_sref_string(service))
    if not sref:
        return ""

    try:
        b_ts = int(begin_time)
        dur = int(duration)
        mid_ts = b_ts + (dur // 2)
        eit_val = int(event_id) if event_id else 0
    except Exception:
        return ""

    tags = []

    # 1. Kontrola lokalnich casovacu (Tento prijimac)
    try:
        nav = getattr(NavigationInstance, "instance", None)
        rec_timer = getattr(nav, "RecordTimer", None) if nav is not None else None
        if rec_timer is not None:
            l_tag = get_local_tag()
            for t in list(getattr(rec_timer, "timer_list", [])):
                if getattr(t, "disabled", False):
                    continue
                if str(getattr(t, "state", 0)) == "3":
                    continue
                t_sref = _normalize_sref(get_sref_string(getattr(t, "service_ref", None)))
                if t_sref != sref:
                    continue
                t_begin = int(getattr(t, "begin", 0))
                t_end = int(getattr(t, "end", 0))
                t_eit = int(getattr(t, "eit", 0) or 0)
                matched = False
                if eit_val > 0 and t_eit == eit_val and abs(t_begin - b_ts) < 7200:
                    matched = True
                elif t_begin <= mid_ts <= t_end:
                    matched = True
                if matched:
                    if l_tag not in tags:
                        tags.append(l_tag)
                    break
    except Exception:
        pass

    # 2. Kontrola vzdalenych casovacu z cache
    with _CACHE_LOCK:
        snapshot = list(REMOTE_TIMER_CACHE)

    for t in snapshot:
        if t["sref"] != sref:
            continue
        matched = False
        if eit_val > 0 and t["eit"] == eit_val and abs(t["begin"] - b_ts) < 7200:
            matched = True
        elif t["begin"] <= mid_ts <= t["end"]:
            matched = True
        if matched and t["tag"] not in tags:
            tags.append(t["tag"])

    if not tags:
        return ""
    return "[%s] " % ",".join(tags)


def find_matching_timers_for_event(session, service, event):
    matches = []
    if service is None or event is None:
        return matches

    sref_norm = _normalize_sref(get_sref_string(service))
    if not sref_norm:
        return matches

    try:
        b_ts = int(event.getBeginTime())
        dur = int(event.getDuration())
        mid_ts = b_ts + (dur // 2)
        ev_id = int(event.getEventId() or 0)
    except Exception:
        return matches

    # 1. Kontrola lokalnich casovacu (Tento prijimac)
    try:
        rec_timer = getattr(session.nav, "RecordTimer", None)
        if rec_timer is not None:
            l_tag = get_local_tag()
            for t in list(getattr(rec_timer, "timer_list", [])):
                if getattr(t, "disabled", False):
                    continue
                if str(getattr(t, "state", 0)) == "3":
                    continue
                t_sref = _normalize_sref(get_sref_string(getattr(t, "service_ref", None)))
                if t_sref != sref_norm:
                    continue
                t_begin = int(getattr(t, "begin", 0))
                t_end = int(getattr(t, "end", 0))
                t_eit = int(getattr(t, "eit", 0) or 0)
                matched = False
                if ev_id > 0 and t_eit == ev_id and abs(t_begin - b_ts) < 7200:
                    matched = True
                elif t_begin <= mid_ts <= t_end:
                    matched = True
                if matched:
                    matches.append(
                        {
                            "is_local": True,
                            "box": None,
                            "box_name": "Dieser Receiver",
                            "tag": l_tag,
                            "local_obj": t,
                            "sref": t_sref,
                            "begin": t_begin,
                            "end": t_end,
                            "name": str(getattr(t, "name", "Ohne Titel") or "Ohne Titel"),
                        }
                    )
    except Exception:
        pass

    # 2. Kontrola vzdalenych casovacu z cache
    with _CACHE_LOCK:
        snapshot = list(REMOTE_TIMER_CACHE)

    for t in snapshot:
        if t["sref"] != sref_norm:
            continue
        matched = False
        if ev_id > 0 and t["eit"] == ev_id and abs(t["begin"] - b_ts) < 7200:
            matched = True
        elif t["begin"] <= mid_ts <= t["end"]:
            matched = True
        if matched:
            box = t["box"]
            matches.append(
                {
                    "is_local": False,
                    "box": box,
                    "box_name": box["name"],
                    "tag": t["tag"],
                    "local_obj": None,
                    "sref": t["raw_sref"],
                    "begin": t["begin"],
                    "end": t["end"],
                    "name": t.get("name", "Ohne Titel"),
                }
            )

    return matches


def add_local_timer(
    session,
    timer_data,
    margin_before_min,
    margin_after_min,
    infinite=False,
    selected_dirname="",
    on_changed_callback=None,
):
    now_ts = int(time.time())
    begin = int(timer_data["raw_begin"]) - (int(margin_before_min) * 60)
    if infinite:
        end = max(begin, now_ts) + 86400
    else:
        end = int(timer_data["raw_end"]) + (int(margin_after_min) * 60)

    try:
        from RecordTimer import AFTEREVENT, RecordTimerEntry
        from ServiceReference import ServiceReference

        after_ev = getattr(AFTEREVENT, "AUTO", 3)
        local_dir = selected_dirname if selected_dirname else None

        entry = RecordTimerEntry(
            ServiceReference(timer_data["sref"]),
            begin,
            end,
            timer_data["name"],
            timer_data["desc"],
            int(timer_data.get("eit") or 0),
            disabled=False,
            justplay=False,
            afterEvent=after_ev,
            dirname=local_dir,
        )

        rec_timer = getattr(session.nav, "RecordTimer", None)
        if rec_timer is None:
            session.open(
                MessageBox,
                "RecordTimer dieses Receivers konnte nicht geladen werden.",
                MessageBox.TYPE_ERROR,
                timeout=6,
            )
            return

        conflicts = rec_timer.record(entry)
        if conflicts is None:
            try:
                auto_cleanup_old_local_timers(session)
            except Exception:
                pass
            if callable(on_changed_callback):
                try:
                    on_changed_callback()
                except Exception:
                    pass
            dir_info = local_dir if local_dir else "Standard"
            if infinite:
                margin_info = "-%d Min / unendlich (\u221e)" % margin_before_min
            else:
                margin_info = "-%d / +%d Min" % (margin_before_min, margin_after_min)
            msg = "Timer hinzugefügt auf Dieser Receiver (%s):\n%s\nPfad: %s" % (
                margin_info,
                timer_data["name"],
                dir_info,
            )
            session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout=5)
        else:
            conflict_names = []
            try:
                for c in conflicts:
                    c_name = getattr(c, "name", "")
                    if c_name:
                        conflict_names.append(str(c_name))
            except Exception:
                pass
            c_txt = ("\n" + ", ".join(conflict_names)) if conflict_names else ""
            msg = "Timer-Konflikt auf diesem Receiver!%s" % c_txt
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=7)
    except Exception as e:
        session.open(
            MessageBox,
            "Fehler beim Hinzufügen des lokalen Timers:\n%s" % str(e),
            MessageBox.TYPE_ERROR,
            timeout=6,
        )


def send_timer_http(
    session,
    box,
    timer_data,
    margin_before_min,
    margin_after_min,
    infinite=False,
    selected_dirname="",
    on_changed_callback=None,
):
    now_ts = int(time.time())
    begin = int(timer_data["raw_begin"]) - (int(margin_before_min) * 60)
    if infinite:
        end = max(begin, now_ts) + 86400
    else:
        end = int(timer_data["raw_end"]) + (int(margin_after_min) * 60)

    state = {"done": False, "ok": False, "msg": ""}

    def _show_result(_res=None):
        if state["ok"] and callable(on_changed_callback):
            try:
                on_changed_callback()
            except Exception:
                pass
        msg_type = MessageBox.TYPE_INFO if state["ok"] else MessageBox.TYPE_ERROR
        timeout_sec = 6 if state["ok"] else 8
        try:
            session.open(MessageBox, state["msg"], msg_type, timeout=timeout_sec)
        except Exception:
            try:
                from Tools import Notifications
                Notifications.AddNotification(
                    MessageBox, state["msg"], type=msg_type, timeout=timeout_sec
                )
            except Exception:
                pass

    wait_dlg = None
    try:
        wait_dlg = session.openWithCallback(
            _show_result,
            MessageBox,
            "Verbinde (Festplatte läuft an)...\n(%s)" % box["name"],
            MessageBox.TYPE_INFO,
            enable_input=False,
        )
    except Exception:
        wait_dlg = None

    def _worker():
        try:
            if selected_dirname:
                remote_dir = selected_dirname
            else:
                remote_dir = fetch_remote_dirname(box, timeout=10)
            url_base = "http://%s:%d/web/timeradd?" % (box["ip"], box["port"])

            params = {
                "sRef": timer_data["sref"],
                "begin": str(begin),
                "end": str(end),
                "name": timer_data["name"],
                "description": timer_data["desc"],
                "eit": str(timer_data["eit"]),
                "disabled": "0",
                "justplay": "0",
                "afterevent": "3",
            }

            if remote_dir:
                params["dirname"] = remote_dir

            url = url_base + urllib.parse.urlencode(params)
            req = _build_request(box, url)

            with urllib.request.urlopen(req, timeout=20) as resp:
                xml_data = resp.read()

            root = ET.fromstring(xml_data)
            state_ok = _xml_text(root, "e2state").lower() == "true"
            statetext = _xml_text(root, "e2statetext", "Keine Antwort")

            if state_ok:
                cur_ts = int(time.time())
                init_state = "2" if (int(begin) <= cur_ts < int(end)) else "0"
                with _CACHE_LOCK:
                    REMOTE_TIMER_CACHE.append(
                        {
                            "box": box,
                            "tag": box.get("tag", box["name"][:2].upper()),
                            "state": init_state,
                            "sref": _normalize_sref(timer_data["sref"]),
                            "raw_sref": timer_data["sref"],
                            "eit": int(timer_data.get("eit") or 0),
                            "begin": int(begin),
                            "end": int(end),
                            "name": timer_data["name"],
                        }
                    )
                try:
                    auto_cleanup_old_timers(box)
                except Exception:
                    pass
                sync_timer_cache_async()

                dir_info = remote_dir if remote_dir else "Standard"
                if infinite:
                    margin_info = "-%d Min / unendlich (\u221e)" % margin_before_min
                else:
                    margin_info = "-%d / +%d Min" % (margin_before_min, margin_after_min)
                state["ok"] = True
                state["msg"] = "Timer hinzugefügt auf %s (%s):\n%s\nPfad: %s\n\n(%s)" % (
                    box["name"],
                    margin_info,
                    timer_data["name"],
                    dir_info,
                    statetext,
                )
            else:
                state["ok"] = False
                state["msg"] = "Box %s hat den Timer abgelehnt:\n%s" % (box["name"], statetext)

        except urllib.error.HTTPError as e:
            state["ok"] = False
            state["msg"] = "HTTP-Fehler auf %s (%s): %s" % (box["name"], box["ip"], e.code)
        except urllib.error.URLError as e:
            state["ok"] = False
            state["msg"] = "Verbindung zu %s (%s) fehlgeschlagen:\n%s" % (box["name"], box["ip"], e.reason)
        except Exception as e:
            state["ok"] = False
            state["msg"] = "Unerwarteter Fehler (%s):\n%s" % (box["name"], str(e))
        finally:
            state["done"] = True

    poll_timer = eTimer()
    _ACTIVE_POLL_TIMERS.append(poll_timer)

    def _check_done():
        if not state["done"]:
            return
        try:
            poll_timer.stop()
        except Exception:
            pass
        try:
            _ACTIVE_POLL_TIMERS.remove(poll_timer)
        except Exception:
            pass
        if wait_dlg is not None:
            try:
                wait_dlg.close()
                return
            except Exception:
                pass
        _show_result()

    poll_timer.callback.append(_check_done)
    poll_timer.start(150, False)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def delete_timer_from_epg(session, timer_item, on_changed_callback=None):
    if timer_item["is_local"]:
        ok, statetext = _delete_local_timer_raw(session, timer_item)
        if ok:
            if callable(on_changed_callback):
                on_changed_callback()
            msg = "Timer abgebrochen (%s):\n%s" % (timer_item["box_name"], timer_item["name"])
            session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout=4)
        else:
            msg = "Fehler beim Abbrechen des lokalen Timers:\n%s" % statetext
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
        return

    box = timer_item["box"]
    try:
        state_ok, statetext = _delete_single_timer_raw(box, timer_item)
        if state_ok:
            with _CACHE_LOCK:
                REMOTE_TIMER_CACHE[:] = [
                    x
                    for x in REMOTE_TIMER_CACHE
                    if not (
                        x["tag"] == timer_item["tag"]
                        and x["begin"] == timer_item["begin"]
                        and x["end"] == timer_item["end"]
                        and x["sref"] == _normalize_sref(timer_item["sref"])
                    )
                ]
            if callable(on_changed_callback):
                on_changed_callback()
            sync_timer_cache_async()
            msg = "Timer abgebrochen (%s):\n%s" % (box["name"], timer_item["name"])
            session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout=4)
        else:
            msg = "Box %s hat das Abbrechen abgelehnt:\n%s" % (box["name"], statetext)
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except urllib.error.HTTPError as e:
        msg = "HTTP-Fehler beim Abbrechen auf %s: %s" % (box["name"], e.code)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except urllib.error.URLError as e:
        msg = "Verbindung zu %s fehlgeschlagen:\n%s" % (box["name"], e.reason)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except Exception as e:
        msg = "Fehler beim Abbrechen (%s):\n%s" % (box["name"], str(e))
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)


def on_box_selected(
    session,
    choice,
    timer_data,
    local_callback=None,
    on_changed_callback=None,
    existing_timers=None,
):
    if not choice:
        return

    action, payload = choice[1]
    ex_list = existing_timers or []

    if action == "SETUP":
        open_setup_screen(session)
        return

    if action == "DELETE":
        delete_timer_from_epg(session, payload, on_changed_callback=on_changed_callback)
        return

    default_before, default_after = get_default_margins_minutes()

    if action == "LOCAL":
        local_existing = next((ex for ex in ex_list if ex.get("is_local")), None)

        def on_local_margins_confirmed(margins):
            if margins is None:
                return
            if isinstance(margins, tuple) and len(margins) == 2 and margins[0] == "DELETE_EXISTING":
                delete_timer_from_epg(session, margins[1], on_changed_callback=on_changed_callback)
                return
            m_before, m_after, is_infinite, selected_dirname = margins
            add_local_timer(
                session,
                timer_data,
                m_before,
                m_after,
                infinite=is_infinite,
                selected_dirname=selected_dirname,
                on_changed_callback=on_changed_callback,
            )

        session.openWithCallback(
            on_local_margins_confirmed,
            RemoteTimerMarginScreen,
            None,
            timer_data,
            default_before,
            default_after,
            existing_timer=local_existing,
        )
        return

    box = payload
    remote_existing = next(
        (
            ex
            for ex in ex_list
            if not ex.get("is_local")
            and ex.get("box")
            and ex["box"].get("ip") == box.get("ip")
            and ex["box"].get("port") == box.get("port")
        ),
        None,
    )

    def on_margins_confirmed(margins):
        if margins is None:
            return
        if isinstance(margins, tuple) and len(margins) == 2 and margins[0] == "DELETE_EXISTING":
            delete_timer_from_epg(session, margins[1], on_changed_callback=on_changed_callback)
            return
        m_before, m_after, is_infinite, selected_dirname = margins
        send_timer_http(
            session,
            box,
            timer_data,
            m_before,
            m_after,
            infinite=is_infinite,
            selected_dirname=selected_dirname,
            on_changed_callback=on_changed_callback,
        )

    session.openWithCallback(
        on_margins_confirmed,
        RemoteTimerMarginScreen,
        box,
        timer_data,
        default_before,
        default_after,
        existing_timer=remote_existing,
    )


def open_box_selector(session, event, service, local_callback=None, on_changed_callback=None):
    if event is None or service is None:
        session.open(
            MessageBox,
            "Sendungsdaten konnten nicht geladen werden (EPG oder Kanal fehlt).",
            MessageBox.TYPE_ERROR,
            timeout=5,
        )
        return

    sref = get_sref_string(service)
    if not sref:
        session.open(
            MessageBox,
            "Service Reference (sRef) des gewählten Kanals fehlt.",
            MessageBox.TYPE_ERROR,
            timeout=5,
        )
        return

    raw_begin = int(event.getBeginTime())
    raw_end = raw_begin + int(event.getDuration())

    timer_data = {
        "sref": sref,
        "raw_begin": raw_begin,
        "raw_end": raw_end,
        "name": event.getEventName() or "Ohne Titel",
        "desc": event.getShortDescription() or "",
        "eit": int(event.getEventId() or 0),
    }

    # Polozky: (levy_text, pravy_text, barva, payload)
    items = []

    existing_timers = find_matching_timers_for_event(session, service, event)
    for ex in existing_timers:
        items.append(
            (
                ">>> Timer abbrechen: %s (%s) <<<" % (ex["box_name"], ex["tag"]),
                "",
                0x00FFCC33,
                ("DELETE", ex),
            )
        )

    local_rec_end = get_local_recording_end_ts(session)
    if local_rec_end:
        local_right = _format_until_time(local_rec_end)
        local_color = 0x00FF5555
    else:
        local_next = get_local_next_timer_begin_ts(session)
        local_right = _format_plan_in_minutes(local_next) if local_next else ""
        local_color = 0x00FFDD33 if local_right else None
    items.append(
        (
            "(%s) Dieser Receiver" % get_local_tag(),
            local_right,
            local_color,
            ("LOCAL", None),
        )
    )

    active_boxes = get_active_boxes()
    for b in active_boxes:
        rem_rec_end = get_remote_recording_end_ts(b)
        if rem_rec_end:
            rem_right = _format_until_time(rem_rec_end)
            rem_color = 0x00FF5555
        else:
            rem_next = get_remote_next_timer_begin_ts(b)
            rem_right = _format_plan_in_minutes(rem_next) if rem_next else ""
            rem_color = 0x00FFDD33 if rem_right else None
        items.append(
            (
                "%s [%s] (%s)" % (b["name"], b["tag"], b["ip"]),
                rem_right,
                rem_color,
                ("BOX", b),
            )
        )

    if not active_boxes:
        items.append(
            (
                ">>> Remote-Receiver einrichten... <<<",
                "",
                0x00FFCC33,
                ("SETUP", None),
            )
        )

    title = "Aufnehmen mit: %s" % timer_data["name"]
    session.openWithCallback(
        lambda choice: on_box_selected(
            session,
            choice,
            timer_data,
            local_callback=local_callback,
            on_changed_callback=on_changed_callback,
            existing_timers=existing_timers,
        ),
        BoxSelectorScreen,
        title,
        items,
    )


# --- Souhrnny prehled, zastaveni, zmena konce a mazani casovacu i nahravek ---

def _format_timer_state(state_str, disabled_str, end_ts, now_ts):
    if disabled_str == "1":
        return "Deaktiv."
    if state_str == "3":
        return "Fertig"
    if state_str == "2":
        return "Aufnahme"
    if end_ts > 0 and end_ts < now_ts:
        return "Fehler"
    if state_str == "1":
        return "Vorbereit."
    if state_str == "0":
        return "Wartet"
    return ""


def _is_finished_or_failed(timer_item, now_ts):
    if timer_item["state"] == "3":
        return True
    if timer_item["state"] != "2" and timer_item["end"] > 0 and timer_item["end"] < now_ts:
        return True
    return False


def _format_time_range(begin_ts, end_ts):
    try:
        dt_begin = datetime.fromtimestamp(begin_ts)
        if begin_ts > 0 and end_ts > begin_ts and (end_ts - begin_ts) >= 82800:
            return "%s-  \u221e" % dt_begin.strftime("%d.%m %H:%M")
        dt_end = datetime.fromtimestamp(end_ts)
        return "%s-%s" % (dt_begin.strftime("%d.%m %H:%M"), dt_end.strftime("%H:%M"))
    except Exception:
        return "??:??"


def fetch_local_timers(session):
    now_ts = int(time.time())
    timers = []
    rec_timer = getattr(session.nav, "RecordTimer", None)
    if rec_timer is None:
        return timers

    l_tag = get_local_tag()
    all_local = list(getattr(rec_timer, "timer_list", [])) + list(
        getattr(rec_timer, "processed_timers", [])
    )

    for t in all_local:
        try:
            begin_ts = int(getattr(t, "begin", 0))
            end_ts = int(getattr(t, "end", 0))
            state_str = str(getattr(t, "state", 0))
            disabled_str = "1" if getattr(t, "disabled", False) else "0"
            name = str(getattr(t, "name", "Ohne Titel") or "Ohne Titel")
            filename = str(getattr(t, "Filename", "") or "")
            sref_obj = getattr(t, "service_ref", None)
            if sref_obj and hasattr(sref_obj, "getServiceName"):
                sname = sref_obj.getServiceName() or "Unbekannter Kanal"
            else:
                sname = "Unbekannter Kanal"
            sref_str = get_sref_string(sref_obj)

            time_txt = _format_time_range(begin_ts, end_ts)
            state_txt = _format_timer_state(state_str, disabled_str, end_ts, now_ts)

            timers.append(
                {
                    "is_local": True,
                    "box": None,
                    "box_name": "Dieser Receiver",
                    "tag": l_tag,
                    "local_obj": t,
                    "filename": filename,
                    "sref": sref_str,
                    "sname": sname,
                    "name": name,
                    "begin": begin_ts,
                    "end": end_ts,
                    "state": state_str,
                    "state_txt": state_txt,
                    "disabled": disabled_str,
                    "time_txt": time_txt,
                }
            )
        except Exception:
            pass

    return timers


def fetch_remote_timers(box):
    url = "http://%s:%d/web/timerlist" % (box["ip"], box["port"])
    req = _build_request(box, url)

    with urllib.request.urlopen(req, timeout=4) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    now_ts = int(time.time())
    tag = box.get("tag", box["name"][:2].upper())
    timers = []

    for item in root.findall("e2timer"):
        sref = _xml_text(item, "e2servicereference")
        sname = _xml_text(item, "e2servicename", "Unbekannter Kanal")
        name = _xml_text(item, "e2name", "Ohne Titel")
        filename = _xml_text(item, "e2filename", "")
        begin_str = _xml_text(item, "e2timebegin", "0")
        end_str = _xml_text(item, "e2timeend", "0")
        state_str = _xml_text(item, "e2state", "0")
        disabled_str = _xml_text(item, "e2disabled", "0")

        try:
            begin_ts = int(float(begin_str))
            end_ts = int(float(end_str))
        except Exception:
            begin_ts = 0
            end_ts = 0

        time_txt = _format_time_range(begin_ts, end_ts)
        state_txt = _format_timer_state(state_str, disabled_str, end_ts, now_ts)

        timers.append(
            {
                "is_local": False,
                "box": box,
                "box_name": box["name"],
                "tag": tag,
                "local_obj": None,
                "filename": filename,
                "sref": sref,
                "sname": sname,
                "name": name,
                "begin": begin_ts,
                "end": end_ts,
                "state": state_str,
                "state_txt": state_txt,
                "disabled": disabled_str,
                "time_txt": time_txt,
            }
        )

    return timers


def _change_remote_timer_end_raw(box, timer_item, new_end_ts):
    url_base = "http://%s:%d/web/timerchange?" % (box["ip"], box["port"])
    params = {
        "sRef": timer_item["sref"],
        "begin": str(timer_item["begin"]),
        "end": str(int(new_end_ts)),
        "name": timer_item["name"],
        "description": "",
        "channelOld": timer_item["sref"],
        "beginOld": str(timer_item["begin"]),
        "endOld": str(timer_item["end"]),
        "disabled": "0",
        "justplay": "0",
        "afterevent": "3",
        "deleteOldOnSave": "1",
    }
    url = url_base + urllib.parse.urlencode(params)
    req = _build_request(box, url)
    with urllib.request.urlopen(req, timeout=6) as resp:
        xml_data = resp.read()
    root = ET.fromstring(xml_data)
    state_ok = _xml_text(root, "e2state").lower() == "true"
    statetext = _xml_text(root, "e2statetext", "Keine Antwort")
    return state_ok, statetext


def _change_local_timer_end_raw(session, timer_item, new_end_ts):
    rec_timer = getattr(session.nav, "RecordTimer", None)
    t_obj = timer_item.get("local_obj")
    if rec_timer is None or t_obj is None:
        return False, "Lokaler Timer nicht gefunden"
    try:
        t_obj.end = int(new_end_ts)
        rec_timer.timeChanged(t_obj)
        return True, "Ende geändert"
    except Exception as e:
        return False, str(e)


def change_any_timer_end(session, timer_item, new_end_ts):
    try:
        dt_new = datetime.fromtimestamp(int(new_end_ts))
        new_end_str = dt_new.strftime("%d.%m %H:%M")
    except Exception:
        new_end_str = "??:??"

    if timer_item["is_local"]:
        ok, statetext = _change_local_timer_end_raw(session, timer_item, new_end_ts)
        if ok:
            msg = "Aufnahmeende geändert (%s):\n%s\nNeues Ende: %s" % (
                timer_item["box_name"],
                timer_item["name"],
                new_end_str,
            )
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=3,
            )
        else:
            msg = "Fehler beim Ändern des lokalen Timers:\n%s" % statetext
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_ERROR,
                timeout=6,
            )
        return

    box = timer_item["box"]
    try:
        state_ok, statetext = _change_remote_timer_end_raw(box, timer_item, new_end_ts)
        sync_timer_cache_async()
        if state_ok:
            msg = "Aufnahmeende geändert (%s):\n%s\nNeues Ende: %s" % (
                box["name"],
                timer_item["name"],
                new_end_str,
            )
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=3,
            )
        else:
            msg = "Box %s hat das Ändern abgelehnt:\n%s" % (box["name"], statetext)
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_ERROR,
                timeout=6,
            )
    except urllib.error.HTTPError as e:
        msg = "HTTP-Fehler beim Ändern auf %s: %s" % (box["name"], e.code)
        session.openWithCallback(
            lambda _res: open_combined_timers(session),
            MessageBox,
            msg,
            MessageBox.TYPE_ERROR,
            timeout=6,
        )
    except urllib.error.URLError as e:
        msg = "Verbindung zu %s fehlgeschlagen:\n%s" % (box["name"], e.reason)
        session.openWithCallback(
            lambda _res: open_combined_timers(session),
            MessageBox,
            msg,
            MessageBox.TYPE_ERROR,
            timeout=6,
        )
    except Exception as e:
        msg = "Fehler beim Ändern (%s):\n%s" % (box["name"], str(e))
        session.openWithCallback(
            lambda _res: open_combined_timers(session),
            MessageBox,
            msg,
            MessageBox.TYPE_ERROR,
            timeout=6,
        )


def _find_next_waiting_timer_on_same_box(timer_item, all_timers):
    best_t = None
    for t in all_timers:
        if t is timer_item:
            continue
        if t.get("disabled") == "1":
            continue
        if t.get("state") not in ("0", "1"):
            continue
        # Kontrola stejneho prijimace
        if timer_item["is_local"]:
            if not t["is_local"]:
                continue
        else:
            if t["is_local"]:
                continue
            b1 = timer_item.get("box")
            b2 = t.get("box")
            if not b1 or not b2:
                continue
            if b1.get("ip") != b2.get("ip") or b1.get("port") != b2.get("port"):
                continue
        if int(t["begin"]) > int(timer_item["begin"]):
            if best_t is None or int(t["begin"]) < int(best_t["begin"]):
                best_t = t
    return best_t


def _stop_remote_timer_raw(box, timer_item):
    now_ts = int(time.time())
    new_end = max(int(timer_item["begin"]) + 1, now_ts)
    url_base = "http://%s:%d/web/timerchange?" % (box["ip"], box["port"])
    params = {
        "sRef": timer_item["sref"],
        "begin": str(timer_item["begin"]),
        "end": str(new_end),
        "name": timer_item["name"],
        "description": "",
        "channelOld": timer_item["sref"],
        "beginOld": str(timer_item["begin"]),
        "endOld": str(timer_item["end"]),
        "disabled": "0",
        "justplay": "0",
        "afterevent": "0",
        "deleteOldOnSave": "1",
    }
    url = url_base + urllib.parse.urlencode(params)
    req = _build_request(box, url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        xml_data = resp.read()
    root = ET.fromstring(xml_data)
    state_ok = _xml_text(root, "e2state").lower() == "true"
    statetext = _xml_text(root, "e2statetext", "Keine Antwort")
    return state_ok, statetext


def _stop_local_timer_raw(session, timer_item):
    rec_timer = getattr(session.nav, "RecordTimer", None)
    t_obj = timer_item.get("local_obj")
    if rec_timer is None or t_obj is None:
        return False, "Lokaler Timer nicht gefunden"
    try:
        if hasattr(t_obj, "afterEvent"):
            t_obj.afterEvent = 0
        if hasattr(t_obj, "disable"):
            t_obj.disable()
        else:
            t_obj.disabled = True
        rec_timer.timeChanged(t_obj)
        return True, "Aufnahme gestoppt"
    except Exception as e:
        return False, str(e)


def _delete_single_timer_raw(box, timer_item):
    url_base = "http://%s:%d/web/timerdelete?" % (box["ip"], box["port"])
    params = {
        "sRef": timer_item["sref"],
        "begin": str(timer_item["begin"]),
        "end": str(timer_item["end"]),
    }
    url = url_base + urllib.parse.urlencode(params)
    req = _build_request(box, url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        xml_data = resp.read()
    root = ET.fromstring(xml_data)
    state_ok = _xml_text(root, "e2state").lower() == "true"
    statetext = _xml_text(root, "e2statetext", "Keine Antwort")
    return state_ok, statetext


def _delete_local_timer_raw(session, timer_item):
    rec_timer = getattr(session.nav, "RecordTimer", None)
    t_obj = timer_item.get("local_obj")
    if rec_timer is None or t_obj is None:
        return False, "Lokaler Timer nicht gefunden"
    try:
        if hasattr(t_obj, "afterEvent"):
            t_obj.afterEvent = 0
        rec_timer.removeEntry(t_obj)
        return True, "Gelöscht"
    except Exception as e:
        return False, str(e)


def _delete_local_recording_raw(timer_item):
    filename = timer_item.get("filename", "")
    if not filename:
        t_obj = timer_item.get("local_obj")
        if t_obj is not None:
            filename = str(getattr(t_obj, "Filename", "") or "")
    if not filename:
        return False, "Dateipfad der Aufnahme nicht gefunden"

    ts_path = filename if filename.endswith(".ts") else (filename + ".ts")
    base_no_ext = ts_path[:-3]

    # 1. Nativni smazani pres Enigma2 eServiceCenter (smaze i doprovodne soubory)
    try:
        sref = eServiceReference("1:0:0:0:0:0:0:0:0:0:" + ts_path)
        service_handler = eServiceCenter.getInstance()
        offline = service_handler.offlineOperations(sref)
        if offline is not None and offline.deleteFromDisk(0) == 0:
            return True, "Aufnahme gelöscht"
    except Exception:
        pass

    # 2. Zalozni prime smazani ze souboroveho systemu
    removed_any = False
    for ext in (".ts", ".ts.meta", ".ts.cuts", ".ts.ap", ".ts.sc", ".eit"):
        fpath = base_no_ext + ext
        try:
            if os.path.exists(fpath):
                os.remove(fpath)
                removed_any = True
        except Exception:
            pass

    if removed_any:
        return True, "Aufnahme gelöscht"
    return False, "Aufnahmedatei nicht auf der Festplatte gefunden"


def _find_remote_movie_sref(box, timer_item):
    filename = (timer_item.get("filename") or "").strip()
    if filename:
        ts_path = filename if filename.endswith(".ts") else (filename + ".ts")
        return "1:0:0:0:0:0:0:0:0:0:" + ts_path

    # Zaloha: dohledani nahravky pres /web/movielist podle nazvu a casu
    try:
        url = "http://%s:%d/web/movielist" % (box["ip"], box["port"])
        req = _build_request(box, url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        target_name = (timer_item.get("name") or "").strip().lower()
        target_begin = int(timer_item.get("begin") or 0)
        for movie in root.findall("e2movie"):
            m_sref = _xml_text(movie, "e2servicereference")
            m_title = _xml_text(movie, "e2title").lower()
            m_time_str = _xml_text(movie, "e2time", "0")
            try:
                m_time = int(float(m_time_str))
            except Exception:
                m_time = 0
            if m_sref and target_name and m_title == target_name:
                if target_begin == 0 or abs(m_time - target_begin) < 1800:
                    return m_sref
    except Exception:
        pass
    return ""


def _delete_remote_recording_raw(box, timer_item):
    movie_sref = _find_remote_movie_sref(box, timer_item)
    if not movie_sref:
        return False, "Aufnahmepfad nicht gefunden"

    url_base = "http://%s:%d/web/moviedelete?" % (box["ip"], box["port"])
    params = {"sRef": movie_sref}
    url = url_base + urllib.parse.urlencode(params)
    req = _build_request(box, url)
    with urllib.request.urlopen(req, timeout=6) as resp:
        xml_data = resp.read()
    root = ET.fromstring(xml_data)
    state_ok = _xml_text(root, "e2state").lower() == "true"
    statetext = _xml_text(root, "e2statetext", "Keine Antwort")
    return state_ok, statetext


def stop_any_timer(session, timer_item, delete_after=False):
    if timer_item["is_local"]:
        if delete_after:
            ok_del, del_txt = _delete_local_timer_raw(session, timer_item)
            if not ok_del:
                msg = "Fehler beim Stoppen und Löschen:\n%s" % del_txt
                session.openWithCallback(
                    lambda _res: open_combined_timers(session),
                    MessageBox,
                    msg,
                    MessageBox.TYPE_ERROR,
                    timeout=6,
                )
                return

            time.sleep(1.2)
            ok_rec, rec_txt = _delete_local_recording_raw(timer_item)
            if ok_rec:
                msg = "Aufnahme gestoppt, Timer und Aufnahme gelöscht (%s):\n%s" % (
                    timer_item["box_name"],
                    timer_item["name"],
                )
                session.openWithCallback(
                    lambda _res: open_combined_timers(session),
                    MessageBox,
                    msg,
                    MessageBox.TYPE_INFO,
                    timeout=4,
                )
            else:
                msg = "Timer gelöscht, aber Löschen der Aufnahme fehlgeschlagen (%s):\n%s" % (
                    timer_item["box_name"],
                    rec_txt,
                )
                session.openWithCallback(
                    lambda _res: open_combined_timers(session),
                    MessageBox,
                    msg,
                    MessageBox.TYPE_ERROR,
                    timeout=6,
                )
            return

        ok, statetext = _stop_local_timer_raw(session, timer_item)
        if ok:
            msg = "Aufnahme gestoppt (%s):\n%s" % (
                timer_item["box_name"],
                timer_item["name"],
            )
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=3,
            )
        else:
            msg = "Fehler beim Stoppen der lokalen Aufnahme:\n%s" % statetext
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_ERROR,
                timeout=6,
            )
        return

    box = timer_item["box"]
    try:
        if delete_after:
            del_ok, del_txt = _delete_single_timer_raw(box, timer_item)
            sync_timer_cache_async()
            if not del_ok:
                msg = "Box %s hat Stoppen und Löschen abgelehnt:\n%s" % (
                    box["name"],
                    del_txt,
                )
                session.openWithCallback(
                    lambda _res: open_combined_timers(session),
                    MessageBox,
                    msg,
                    MessageBox.TYPE_ERROR,
                    timeout=6,
                )
                return

            time.sleep(1.2)
            rec_ok, rec_txt = _delete_remote_recording_raw(box, timer_item)
            if rec_ok:
                msg = "Aufnahme gestoppt, Timer und Aufnahme gelöscht (%s):\n%s" % (
                    box["name"],
                    timer_item["name"],
                )
                session.openWithCallback(
                    lambda _res: open_combined_timers(session),
                    MessageBox,
                    msg,
                    MessageBox.TYPE_INFO,
                    timeout=4,
                )
            else:
                msg = "Timer gelöscht, aber Box %s konnte Aufnahme nicht löschen:\n%s" % (
                    box["name"],
                    rec_txt,
                )
                session.openWithCallback(
                    lambda _res: open_combined_timers(session),
                    MessageBox,
                    msg,
                    MessageBox.TYPE_ERROR,
                    timeout=6,
                )
            return

        state_ok, statetext = _stop_remote_timer_raw(box, timer_item)
        sync_timer_cache_async()
        if state_ok:
            msg = "Aufnahme gestoppt (%s):\n%s" % (box["name"], timer_item["name"])
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=3,
            )
        else:
            msg = "Box %s hat das Stoppen abgelehnt:\n%s" % (box["name"], statetext)
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_ERROR,
                timeout=6,
            )
    except urllib.error.HTTPError as e:
        msg = "HTTP-Fehler beim Stoppen auf %s: %s" % (box["name"], e.code)
        session.openWithCallback(
            lambda _res: open_combined_timers(session),
            MessageBox,
            msg,
            MessageBox.TYPE_ERROR,
            timeout=6,
        )
    except urllib.error.URLError as e:
        msg = "Verbindung zu %s fehlgeschlagen:\n%s" % (box["name"], e.reason)
        session.openWithCallback(
            lambda _res: open_combined_timers(session),
            MessageBox,
            msg,
            MessageBox.TYPE_ERROR,
            timeout=6,
        )
    except Exception as e:
        msg = "Fehler beim Stoppen (%s):\n%s" % (box["name"], str(e))
        session.openWithCallback(
            lambda _res: open_combined_timers(session),
            MessageBox,
            msg,
            MessageBox.TYPE_ERROR,
            timeout=6,
        )


def auto_cleanup_old_timers(box):
    days = get_auto_cleanup_days()
    if days <= 0:
        return 0
    timers = fetch_remote_timers(box)
    now_ts = int(time.time())
    cutoff_ts = now_ts - (days * 86400)
    deleted = 0

    for t in timers:
        if _is_finished_or_failed(t, now_ts) and t["end"] > 0 and t["end"] < cutoff_ts:
            try:
                ok, _ = _delete_single_timer_raw(box, t)
                if ok:
                    deleted += 1
            except Exception:
                pass
    return deleted


def auto_cleanup_old_local_timers(session):
    days = get_auto_cleanup_days()
    if days <= 0:
        return 0
    timers = fetch_local_timers(session)
    now_ts = int(time.time())
    cutoff_ts = now_ts - (days * 86400)
    deleted = 0

    for t in timers:
        if _is_finished_or_failed(t, now_ts) and t["end"] > 0 and t["end"] < cutoff_ts:
            ok, _ = _delete_local_timer_raw(session, t)
            if ok:
                deleted += 1
    return deleted


def cleanup_all_finished_and_failed(session, timers_to_delete):
    deleted = 0
    touched_boxes = []

    for t in timers_to_delete:
        if t["is_local"]:
            ok, _ = _delete_local_timer_raw(session, t)
            if ok:
                deleted += 1
        else:
            box = t["box"]
            if box not in touched_boxes:
                touched_boxes.append(box)
            try:
                ok, _ = _delete_single_timer_raw(box, t)
                if ok:
                    deleted += 1
            except Exception:
                pass

    for box in touched_boxes:
        try:
            url = "http://%s:%d/web/timercleanup?cleanup=true" % (box["ip"], box["port"])
            req = _build_request(box, url)
            with urllib.request.urlopen(req, timeout=4) as resp:
                resp.read()
        except Exception:
            pass

    sync_timer_cache_async()
    msg = "%d fertige/fehlgeschlagene Timer von allen Receivern gelöscht." % deleted
    session.openWithCallback(
        lambda _res: open_combined_timers(session),
        MessageBox,
        msg,
        MessageBox.TYPE_INFO,
        timeout=3,
    )


def delete_any_timer(session, timer_item):
    if timer_item["is_local"]:
        ok, statetext = _delete_local_timer_raw(session, timer_item)
        if ok:
            msg = "Timer gelöscht von %s:\n%s" % (timer_item["box_name"], timer_item["name"])
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=3,
            )
        else:
            msg = "Fehler beim Löschen des lokalen Timers:\n%s" % statetext
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
        return

    box = timer_item["box"]
    try:
        state_ok, statetext = _delete_single_timer_raw(box, timer_item)
        if state_ok:
            sync_timer_cache_async()
            msg = "Timer gelöscht von %s:\n%s" % (box["name"], timer_item["name"])
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=3,
            )
        else:
            msg = "Box %s hat das Löschen abgelehnt:\n%s" % (box["name"], statetext)
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except urllib.error.HTTPError as e:
        msg = "HTTP-Fehler beim Löschen auf %s: %s" % (box["name"], e.code)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except urllib.error.URLError as e:
        msg = "Verbindung zu %s fehlgeschlagen:\n%s" % (box["name"], e.reason)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except Exception as e:
        msg = "Fehler beim Löschen (%s):\n%s" % (box["name"], str(e))
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)


def open_combined_timers(session, **kwargs):
    all_timers = []
    offline_boxes = []
    active_boxes = get_active_boxes()

    try:
        auto_cleanup_old_local_timers(session)
        all_timers.extend(fetch_local_timers(session))
    except Exception:
        pass

    for box in active_boxes:
        try:
            auto_cleanup_old_timers(box)
            all_timers.extend(fetch_remote_timers(box))
        except Exception:
            offline_boxes.append(box["name"])

    # Razeni chronologicky podle data a casu zacatku
    all_timers.sort(key=lambda t: (t["begin"], t["end"], t["name"]))

    now_ts = int(time.time())
    finished_or_failed = [t for t in all_timers if _is_finished_or_failed(t, now_ts)]

    rows_spec = []
    if not active_boxes:
        rows_spec.append(
            ("BANNER", "OPEN_SETUP", ">>> Keine Remote-Box eingerichtet – Einstellungen öffnen <<<")
        )

    if offline_boxes:
        rows_spec.append(
            ("BANNER", "OFFLINE_INFO", "[!] Nicht erreichbar: %s" % ", ".join(offline_boxes))
        )

    if finished_or_failed:
        rows_spec.append(
            (
                "BANNER",
                "CLEANUP_ALL",
                ">>> ALLE FERTIGEN & FEHLGESCHLAGENEN LÖSCHEN (%d) <<<" % len(finished_or_failed),
            )
        )

    for t in all_timers:
        rows_spec.append(("TIMER", t, ""))

    if not rows_spec:
        rows_spec.append(
            ("BANNER", "OPEN_SETUP", "Keine Timer (GELBE Taste = Boxen einrichten)")
        )

    def on_screen_closed(result):
        if not result:
            return
        cmd, selected = result

        if cmd == "OPEN_SETUP" or selected == "OPEN_SETUP":
            open_setup_screen(session, callback=lambda _saved: open_combined_timers(session))
            return

        if cmd == "CHANGE_END":
            if (
                not isinstance(selected, dict)
                or selected.get("disabled") == "1"
                or selected.get("state") not in ("0", "1", "2")
            ):
                session.openWithCallback(
                    lambda _res: open_combined_timers(session),
                    MessageBox,
                    "Das Ende kann nur bei laufenden oder wartenden Timern geändert werden.",
                    MessageBox.TYPE_INFO,
                    timeout=3,
                )
                return

            t_item = selected
            next_t = _find_next_waiting_timer_on_same_box(t_item, all_timers)
            max_end_ts = (int(next_t["begin"]) - 60) if next_t else None
            next_info = ""
            if next_t:
                try:
                    dt_next = datetime.fromtimestamp(int(next_t["begin"]))
                    next_info = "Nächster wartender Timer auf [%s]: %s (%s)" % (
                        t_item["tag"],
                        dt_next.strftime("%d.%m %H:%M"),
                        next_t["name"],
                    )
                except Exception:
                    next_info = ""

            def on_end_changed(new_end_ts):
                if new_end_ts is None:
                    open_combined_timers(session)
                    return
                change_any_timer_end(session, t_item, new_end_ts)

            session.openWithCallback(
                on_end_changed,
                ChangeTimerEndScreen,
                t_item,
                max_end_ts=max_end_ts,
                next_timer_info=next_info,
            )
            return

        if cmd == "STOP_REC":
            if not isinstance(selected, dict) or selected.get("state") != "2":
                session.openWithCallback(
                    lambda _res: open_combined_timers(session),
                    MessageBox,
                    "Der gewählte Timer nimmt derzeit nicht auf.",
                    MessageBox.TYPE_INFO,
                    timeout=3,
                )
                return

            t_item = selected
            stop_choices = [
                ("STOP REC", "STOP_ONLY"),
                ("STOP REC & AUFNAHME LÖSCHEN", "STOP_DELETE"),
            ]

            def on_stop_choice(choice):
                if not choice:
                    open_combined_timers(session)
                    return
                action = choice[1]
                if action == "STOP_ONLY":
                    stop_any_timer(session, t_item, delete_after=False)
                elif action == "STOP_DELETE":
                    stop_any_timer(session, t_item, delete_after=True)

            stop_title = "Aufnahme beenden [%s]: %s" % (t_item["tag"], t_item["name"])
            session.openWithCallback(
                on_stop_choice,
                ChoiceBox,
                title=stop_title,
                list=stop_choices,
            )
            return

        if selected is None:
            return

        if selected == "OFFLINE_INFO":
            open_combined_timers(session)
            return

        if selected == "CLEANUP_ALL":
            confirm_all = (
                "Alle fertigen und fehlgeschlagenen Timer (%d) von allen Receivern löschen?"
                % len(finished_or_failed)
            )

            def on_confirm_all(answer):
                if answer:
                    cleanup_all_finished_and_failed(session, finished_or_failed)
                else:
                    open_combined_timers(session)

            session.openWithCallback(
                on_confirm_all, MessageBox, confirm_all, MessageBox.TYPE_YESNO
            )
            return

        t_item = selected
        confirm_msg = "Timer löschen von [%s] %s?\n\n%s\n%s (%s)" % (
            t_item["tag"],
            t_item["box_name"],
            t_item["name"],
            t_item["sname"],
            t_item["time_txt"],
        )

        def on_confirm(answer):
            if answer:
                delete_any_timer(session, t_item)
            else:
                open_combined_timers(session)

        session.openWithCallback(on_confirm, MessageBox, confirm_msg, MessageBox.TYPE_YESNO)

    legend_parts = ["[%s]=Lokal" % get_local_tag()] + [
        "[%s]=%s" % (b.get("tag", b["name"][:2].upper()), b["name"]) for b in active_boxes
    ]
    title = "Alle Timer: " + "  ".join(legend_parts)
    session.openWithCallback(on_screen_closed, CombinedTimersScreen, title, rows_spec)


def timer_menu_entry(menuid, **kwargs):
    if menuid == "mainmenu":
        return [("Alle Timer", open_combined_timers, "remote_timer_main", 15)]
    if menuid == "timermenu":
        return [
            ("Alle Timer", open_combined_timers, "remote_timer_select", 50),
            ("Remote-Timer Einstellungen", open_setup_screen, "remote_timer_setup", 51),
        ]
    return []


# --- EPG Hook (tlacitko REC + automaticke znacky v EPG) ---

def _patch_method(cls, method_name):
    if cls is None or not hasattr(cls, method_name):
        return False

    orig_method = getattr(cls, method_name)
    if getattr(orig_method, "_rts_patched", False):
        return True

    def wrapped_timer_action(self, *args, **kwargs):
        def refresh_epg_ui():
            try:
                lst = self["list"]
                if hasattr(lst, "l") and lst.l is not None:
                    lst.l.invalidate()
                if hasattr(lst, "instance") and lst.instance is not None:
                    lst.instance.invalidate()
            except Exception:
                pass

        try:
            cur = self["list"].getCurrent()
            if cur and len(cur) >= 2 and cur[0] is not None and cur[1] is not None:
                event, service = cur[0], cur[1]
                open_box_selector(
                    self.session,
                    event,
                    service,
                    local_callback=lambda: orig_method(self, *args, **kwargs),
                    on_changed_callback=refresh_epg_ui,
                )
                return
        except Exception:
            pass
        return orig_method(self, *args, **kwargs)

    wrapped_timer_action._rts_patched = True
    setattr(cls, method_name, wrapped_timer_action)
    return True


def install_epg_hook():
    global _EPG_HOOKED
    if _EPG_HOOKED:
        return

    modules = []
    for mod_name in ("Screens.EpgSelectionBase", "Screens.EpgSelection"):
        try:
            mod = __import__(mod_name, fromlist=["*"])
            modules.append(mod)
        except Exception:
            pass

    class_names = (
        "EPGSelectionBase",
        "EPGSelection",
        "EPGSelectionSingle",
        "EPGSelectionMulti",
        "EPGSelectionGrid",
    )
    method_names = (
        "RecordTimerQuestion",
        "recordTimerQuestion",
        "timerAdd",
        "addTimer",
    )

    patched_any = False
    for mod in modules:
        for cls_name in class_names:
            cls = getattr(mod, cls_name, None)
            if cls is None:
                continue
            for m_name in method_names:
                if _patch_method(cls, m_name):
                    patched_any = True

    if patched_any:
        _EPG_HOOKED = True


def _patch_live_rec_method(cls, method_name):
    if cls is None or not hasattr(cls, method_name):
        return False

    orig_method = getattr(cls, method_name)
    if getattr(orig_method, "_rts_live_patched", False):
        return True

    def wrapped_live_rec(self, *args, **kwargs):
        global _BYPASS_LIVE_REC
        if _BYPASS_LIVE_REC or not is_live_rec_selector_enabled():
            return orig_method(self, *args, **kwargs)

        def call_orig():
            global _BYPASS_LIVE_REC
            _BYPASS_LIVE_REC = True
            try:
                return orig_method(self, *args, **kwargs)
            finally:
                _BYPASS_LIVE_REC = False

        try:
            event, service = get_current_live_event(self.session)
            if event is not None and service is not None:
                open_box_selector(
                    self.session,
                    event,
                    service,
                    local_callback=call_orig,
                )
                return
        except Exception:
            pass
        return call_orig()

    wrapped_live_rec._rts_live_patched = True
    setattr(cls, method_name, wrapped_live_rec)
    return True


def install_live_rec_hook():
    global _LIVE_REC_HOOKED
    if _LIVE_REC_HOOKED:
        return

    try:
        mod = __import__("Screens.InfoBarGenerics", fromlist=["InfoBarInstantRecord"])
        cls = getattr(mod, "InfoBarInstantRecord", None)
        if cls is None:
            return

        target_methods = ("keyInstantRecord", "instantRecord")
        patched_any = False
        for m_name in target_methods:
            if _patch_live_rec_method(cls, m_name):
                patched_any = True

        # Aktualizace jiz bezici instance InfoBar (vznika pred WHERE_SESSIONSTART)
        try:
            ib_mod = __import__("Screens.InfoBar", fromlist=["InfoBar"])
            ib_cls = getattr(ib_mod, "InfoBar", None)
            ib_inst = getattr(ib_cls, "instance", None) if ib_cls is not None else None
            if ib_inst is not None:
                for m_name in target_methods:
                    bound_wrapped = getattr(ib_inst, m_name, None)
                    if bound_wrapped is None:
                        continue
                    for key in list(ib_inst.keys()):
                        act_map = ib_inst[key]
                        if hasattr(act_map, "actions") and isinstance(act_map.actions, dict):
                            for a_key, a_val in list(act_map.actions.items()):
                                if a_key == m_name or getattr(a_val, "__name__", "") == m_name:
                                    act_map.actions[a_key] = bound_wrapped
        except Exception:
            pass

        if patched_any:
            _LIVE_REC_HOOKED = True
    except Exception:
        pass


def _wrap_epg_builder(orig_fn):
    try:
        sig = inspect.signature(orig_fn)
    except Exception:
        return orig_fn

    def wrapped(*args, **kwargs):
        try:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            b_args = bound.arguments

            service = None
            for k in ("service", "srv", "service_ref", "serviceRef", "sref"):
                if k in b_args and b_args[k] is not None:
                    service = b_args[k]
                    break

            name_key = None
            for k in ("eventName", "EventName", "event_name", "name", "title"):
                if k in b_args and isinstance(b_args[k], str):
                    name_key = k
                    break

            if name_key is not None:
                event_id = None
                for k in ("eventId", "event_id", "eit", "id"):
                    if k in b_args and b_args[k] is not None:
                        event_id = b_args[k]
                        break

                begin_time = None
                for k in ("beginTime", "begin_time", "begin", "startTime", "start_time"):
                    if k in b_args and b_args[k] is not None:
                        begin_time = b_args[k]
                        break

                duration = None
                for k in ("duration", "dur", "length"):
                    if k in b_args and b_args[k] is not None:
                        duration = b_args[k]
                        break

                marks = get_epg_marks(service, event_id, begin_time, duration)
                if marks and not b_args[name_key].startswith(marks):
                    b_args[name_key] = marks + b_args[name_key]
                    return orig_fn(*bound.args, **bound.kwargs)

            event_obj = None
            for k in ("event", "ev", "epgEvent", "epg_event"):
                if k in b_args and b_args[k] is not None and hasattr(b_args[k], "getBeginTime"):
                    event_obj = b_args[k]
                    break

            if event_obj is not None:
                if service is None:
                    service = getattr(event_obj, "service_reference", None)
                ev_id = event_obj.getEventId() if hasattr(event_obj, "getEventId") else 0
                ev_begin = event_obj.getBeginTime()
                ev_dur = event_obj.getDuration() if hasattr(event_obj, "getDuration") else 0
                orig_name = event_obj.getEventName() if hasattr(event_obj, "getEventName") else ""

                marks = get_epg_marks(service, ev_id, ev_begin, ev_dur)
                res = orig_fn(*bound.args, **bound.kwargs)
                if marks and orig_name and not orig_name.startswith(marks) and isinstance(res, list):
                    new_res = []
                    for entry in res:
                        if isinstance(entry, tuple) and orig_name in entry:
                            entry = tuple(
                                (marks + x if x == orig_name else x) for x in entry
                            )
                        new_res.append(entry)
                    return new_res
                return res
        except Exception:
            pass

        return orig_fn(*args, **kwargs)

    wrapped._rts_marked = True
    return wrapped


def install_epg_list_marks_hook():
    global _EPG_LIST_HOOKED
    if _EPG_LIST_HOOKED:
        return

    patched_any = False
    for mod_name in ("Components.EpgList", "Components.EpgListSingle", "Components.EpgListMulti"):
        try:
            mod = __import__(mod_name, fromlist=["*"])
        except Exception:
            continue

        for cls_name, cls in inspect.getmembers(mod, inspect.isclass):
            if "epg" not in cls_name.lower():
                continue
            for m_name, m_obj in list(cls.__dict__.items()):
                if not m_name.startswith("build"):
                    continue
                if callable(m_obj) and not getattr(m_obj, "_rts_marked", False):
                    setattr(cls, m_name, _wrap_epg_builder(m_obj))
                    patched_any = True

    if patched_any:
        _EPG_LIST_HOOKED = True


def start_cache_timer():
    global _CACHE_TIMER
    if _CACHE_TIMER is not None:
        return
    try:
        _CACHE_TIMER = eTimer()
        _CACHE_TIMER.callback.append(sync_timer_cache_async)
        _CACHE_TIMER.start(CACHE_REFRESH_SEC * 1000, False)
    except Exception:
        pass


def on_session_start(reason, **kwargs):
    if reason == 0:
        install_epg_hook()
        install_live_rec_hook()
        install_epg_list_marks_hook()
        sync_timer_cache_async()
        start_cache_timer()


def get_current_live_event(session):
    srv_ref = session.nav.getCurrentlyPlayingServiceReference()
    cur_srv = session.nav.getCurrentService()
    event = None
    if cur_srv:
        info = cur_srv.info()
        if info:
            event = info.getEvent(0)
    return event, srv_ref


def eventinfo(session, selectedevent=None, service=None, event=None, **kwargs):
    if selectedevent is not None:
        if isinstance(selectedevent, (tuple, list)) and len(selectedevent) >= 2:
            event = selectedevent[0]
            service = selectedevent[1]
        else:
            event = selectedevent

    if event is None or service is None:
        live_event, live_srv = get_current_live_event(session)
        if event is None:
            event = live_event
        if service is None:
            service = live_srv

    open_box_selector(session, event, service)


def main_extension(session, **kwargs):
    event, service = get_current_live_event(session)
    open_box_selector(session, event, service)


def Plugins(**kwargs):
    return [
        PluginDescriptor(
            where=PluginDescriptor.WHERE_SESSIONSTART,
            fnc=on_session_start,
        ),
        PluginDescriptor(
            name="Alle Timer",
            description="Gesamtübersicht der Timer aller Receiver",
            where=PluginDescriptor.WHERE_MENU,
            fnc=timer_menu_entry,
            needsRestart=False,
        ),
        PluginDescriptor(
            name="Remote-Aufnahme",
            description="Timer auf einem Remote-Receiver hinzufügen",
            where=PluginDescriptor.WHERE_EVENTINFO,
            fnc=eventinfo,
            needsRestart=False,
        ),
        PluginDescriptor(
            name="Remote-Aufnahme",
            description="Aktuelle Sendung auf einem Remote-Receiver aufnehmen",
            where=PluginDescriptor.WHERE_EXTENSIONSMENU,
            fnc=main_extension,
            needsRestart=False,
        ),
        PluginDescriptor(
            name="Alle Timer",
            description="Gesamtübersicht und Löschen der Timer aller Receiver",
            where=[
                PluginDescriptor.WHERE_EXTENSIONSMENU,
                PluginDescriptor.WHERE_PLUGINMENU,
            ],
            fnc=open_combined_timers,
            needsRestart=False,
        ),
        PluginDescriptor(
            name="Remote-Timer - Einstellungen",
            description="IP-Adressen und Kürzel der Remote-Receiver konfigurieren",
            where=PluginDescriptor.WHERE_PLUGINMENU,
            fnc=open_setup_screen,
            needsRestart=False,
        ),
    ]