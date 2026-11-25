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

from enigma import (
    RT_HALIGN_LEFT,
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
    ConfigSelectionNumber,
    ConfigSubsection,
    ConfigText,
    config,
    configfile,
    getConfigListEntry,
)
from Plugins.Plugin import PluginDescriptor
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen

# Background EPG mark refresh interval (seconds)
CACHE_REFRESH_SEC = 300

# Font size in the combined timers overview
TIMER_LIST_FONT_FHD = 42
TIMER_LIST_FONT_HD = 30

_EPG_HOOKED = False
_EPG_LIST_HOOKED = False
_CACHE_TIMER = None
_CACHE_LOCK = threading.Lock()
REMOTE_TIMER_CACHE = []


def init_plugin_config():
    if not hasattr(config.plugins, "remotetimerselect"):
        config.plugins.remotetimerselect = ConfigSubsection()

    cfg = config.plugins.remotetimerselect
    if not hasattr(cfg, "local_tag"):
        cfg.local_tag = ConfigText(default="L", fixed_size=False)
    if not hasattr(cfg, "auto_cleanup_days"):
        cfg.auto_cleanup_days = ConfigSelectionNumber(0, 30, 1, default=2)

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
        return val if val else "L"
    except Exception:
        return "L"


def get_auto_cleanup_days():
    try:
        return int(config.plugins.remotetimerselect.auto_cleanup_days.value)
    except Exception:
        return 2


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
        self.setTitle("Remote Timers Setup")

        self["key_red"] = StaticText("Cancel")
        self["key_green"] = StaticText("Save")
        self["footnote"] = StaticText("OK = virtual keyboard   |   Green = save")
        self["description"] = StaticText("")

        cfg = config.plugins.remotetimerselect
        self.list = [
            (
                getConfigListEntry("Local receiver tag", cfg.local_tag),
                "Short tag shown in the timers overview for this local receiver (default: L).",
            ),
            (
                getConfigListEntry("Auto-delete done/failed timers (days)", cfg.auto_cleanup_days),
                "Automatically delete finished and failed timers older than this many days (0 = off).",
            ),
        ]

        for idx in range(1, 5):
            b_cfg = getattr(cfg, "box%d" % idx)
            self.list.append(
                (
                    getConfigListEntry("Box %d - Receiver name" % idx, b_cfg.name),
                    "Display name of remote box %d in menus and messages (e.g. LivingRoom or SF8008)." % idx,
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - Short tag" % idx, b_cfg.tag),
                    "Short tag shown in EPG and timer list for box %d (e.g. M, V, B%d)." % (idx, idx),
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - IP address (0.0.0.0 = disabled)" % idx, b_cfg.ip),
                    "Local network IP address of box %d (enter with number keys). 0.0.0.0 = disabled." % idx,
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - OpenWebif HTTP port" % idx, b_cfg.port),
                    "OpenWebif HTTP port on box %d (default is 80)." % idx,
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - OpenWebif username" % idx, b_cfg.user),
                    "OpenWebif username (leave empty if authentication is disabled).",
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - OpenWebif password" % idx, b_cfg.password),
                    "OpenWebif password for box %d (leave empty if not required)." % idx,
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


def _state_color(state_txt):
    colors = {
        "Recording": 0x00FF6666,
        "Waiting": 0x0077DD77,
        "Done": 0x0088CCFF,
        "Failed": 0x00FFAA44,
        "Preparing": 0x00FFEE66,
        "Disabled": 0x00999999,
    }
    return colors.get(state_txt, None)


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


def _build_timer_entry(timer_item, is_fhd, item_h):
    flags = RT_HALIGN_LEFT | RT_VALIGN_CENTER
    time_txt = timer_item["time_txt"]
    state_txt = "[%s]" % timer_item["state_txt"] if timer_item.get("state_txt") else ""
    tag_txt = "[%s]" % timer_item["tag"]
    detail_txt = "%s  |  %s" % (timer_item["sname"], timer_item["name"])
    st_color = _state_color(timer_item.get("state_txt", ""))

    # Column order: 1. Date & time, 2. State, 3. Receiver tag, 4. Channel | Event name
    if is_fhd:
        col1_x, col1_w = 5, 355
        col2_x, col2_w = 370, 235
        col3_x, col3_w = 615, 130
        col4_x, col4_w = 755, 1010
    else:
        col1_x, col1_w = 5, 250
        col2_x, col2_w = 260, 175
        col3_x, col3_w = 440, 95
        col4_x, col4_w = 540, 645

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
        self.setTitle("All Timers")

        desktop_w = 1920
        try:
            desktop_w = getDesktop(0).size().width()
        except Exception:
            pass

        is_fhd = desktop_w >= 1920
        if is_fhd:
            font_sz = int(TIMER_LIST_FONT_FHD)
            item_h = int(font_sz * 1.42)
            rows_h = (840 // item_h) * item_h
            self.skin = (
                '<screen name="CombinedTimersScreen" position="50,55" size="1820,970" title="All Timers">'
                '<widget source="title_text" render="Label" position="25,15" size="1770,50" font="Regular;34" foregroundColor="#00ffcc33" noWrap="1" />'
                '<widget name="list" position="25,75" size="1770,%d" font="Regular;%d" itemHeight="%d" scrollbarMode="showOnDemand" enableWrapAround="1" />'
                '<widget source="hint_ok" render="Label" position="25,922" size="195,38" font="Regular;28" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_red" render="Label" position="220,922" size="65,38" font="Regular;28" foregroundColor="#00ff5555" noWrap="1" />'
                '<widget source="hint_stop" render="Label" position="285,922" size="190,38" font="Regular;28" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_yellow" render="Label" position="475,922" size="125,38" font="Regular;28" foregroundColor="#00ffdd33" noWrap="1" />'
                '<widget source="hint_rest" render="Label" position="600,922" size="1195,38" font="Regular;28" foregroundColor="#00aaaaaa" noWrap="1" />'
                "</screen>"
            ) % (rows_h, font_sz, item_h)
        else:
            font_sz = int(TIMER_LIST_FONT_HD)
            item_h = int(font_sz * 1.40)
            rows_h = (546 // item_h) * item_h
            self.skin = (
                '<screen name="CombinedTimersScreen" position="30,35" size="1220,650" title="All Timers">'
                '<widget source="title_text" render="Label" position="15,10" size="1190,36" font="Regular;24" foregroundColor="#00ffcc33" noWrap="1" />'
                '<widget name="list" position="15,52" size="1190,%d" font="Regular;%d" itemHeight="%d" scrollbarMode="showOnDemand" enableWrapAround="1" />'
                '<widget source="hint_ok" render="Label" position="15,606" size="140,32" font="Regular;20" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_red" render="Label" position="155,606" size="50,32" font="Regular;20" foregroundColor="#00ff5555" noWrap="1" />'
                '<widget source="hint_stop" render="Label" position="205,606" size="140,32" font="Regular;20" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_yellow" render="Label" position="345,606" size="90,32" font="Regular;20" foregroundColor="#00ffdd33" noWrap="1" />'
                '<widget source="hint_rest" render="Label" position="435,606" size="770,32" font="Regular;20" foregroundColor="#00aaaaaa" noWrap="1" />'
                "</screen>"
            ) % (rows_h, font_sz, item_h)

        mc_entries = []
        for row_type, payload, text in rows_spec:
            if row_type == "TIMER":
                mc_entries.append(_build_timer_entry(payload, is_fhd, item_h))
            else:
                b_color = 0x00FF7777 if payload == "OFFLINE_INFO" else 0x00FFCC33
                mc_entries.append(_build_banner_entry(payload, text, is_fhd, item_h, color=b_color))

        self["title_text"] = StaticText(title)
        self["hint_ok"] = StaticText("OK = delete  |")
        self["hint_red"] = StaticText("RED")
        self["hint_stop"] = StaticText("= stop REC  |")
        self["hint_yellow"] = StaticText("YELLOW")
        self["hint_rest"] = StaticText("/ MENU = box setup  |  EXIT = close")
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
                "menu": self.keySetup,
            },
            -1,
        )

    def keyOk(self):
        cur = self["list"].getCurrent()
        if cur:
            self.close(("SELECT", cur[0]))

    def keyRed(self):
        cur = self["list"].getCurrent()
        if cur:
            self.close(("STOP_REC", cur[0]))

    def keySetup(self):
        self.close(("OPEN_SETUP", None))

    def keyCancel(self):
        self.close(None)


class RemoteTimerMarginScreen(ConfigListScreen, Screen):
    def __init__(self, session, box, timer_data, default_before, default_after):
        Screen.__init__(self, session)
        self.skinName = ["Setup"]
        self.setTitle("Time margins (%s)" % box["name"])

        self["key_red"] = StaticText("Cancel")
        self["key_green"] = StaticText("Record")
        self["footnote"] = StaticText("")
        self["description"] = StaticText(timer_data["name"])

        val_before = max(0, min(120, int(default_before)))
        val_after = max(0, min(180, int(default_after)))

        self.cfg_before = ConfigSelectionNumber(0, 120, 1, default=val_before)
        self.cfg_after = ConfigSelectionNumber(0, 180, 1, default=val_after)

        self.list = [
            getConfigListEntry("Margin before event (min)", self.cfg_before),
            getConfigListEntry("Margin after event (min)", self.cfg_after),
        ]

        ConfigListScreen.__init__(self, self.list, session=session)

        self["actions"] = ActionMap(
            ["SetupActions", "ColorActions"],
            {
                "ok": self.keySave,
                "save": self.keySave,
                "green": self.keySave,
                "cancel": self.keyCancel,
                "red": self.keyCancel,
            },
            -2,
        )

    def keySave(self):
        self.close((int(self.cfg_before.value), int(self.cfg_after.value)))

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


def fetch_remote_dirname(box):
    for endpoint in ("/web/getcurrlocation", "/web/getlocations"):
        try:
            url = "http://%s:%d%s" % (box["ip"], box["port"], endpoint)
            req = _build_request(box, url)
            with urllib.request.urlopen(req, timeout=4) as resp:
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
                name = _xml_text(item, "e2name", "No title")
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

    with _CACHE_LOCK:
        REMOTE_TIMER_CACHE = new_items


def sync_timer_cache_async():
    try:
        t = threading.Thread(target=_sync_timer_cache_worker, daemon=True)
        t.start()
    except Exception:
        pass


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

    with _CACHE_LOCK:
        snapshot = list(REMOTE_TIMER_CACHE)

    tags = []
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

    # 1. Check local timers (This receiver)
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
                            "box_name": "This receiver",
                            "tag": l_tag,
                            "local_obj": t,
                            "sref": t_sref,
                            "begin": t_begin,
                            "end": t_end,
                            "name": str(getattr(t, "name", "No title") or "No title"),
                        }
                    )
    except Exception:
        pass

    # 2. Check remote timers from cache
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
                    "name": t.get("name", "No title"),
                }
            )

    return matches


def send_timer_http(
    session, box, timer_data, margin_before_min, margin_after_min, on_changed_callback=None
):
    begin = int(timer_data["raw_begin"]) - (int(margin_before_min) * 60)
    end = int(timer_data["raw_end"]) + (int(margin_after_min) * 60)

    remote_dir = fetch_remote_dirname(box)
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

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            xml_data = resp.read()

        root = ET.fromstring(xml_data)
        state_ok = _xml_text(root, "e2state").lower() == "true"
        statetext = _xml_text(root, "e2statetext", "No response")

        if state_ok:
            with _CACHE_LOCK:
                REMOTE_TIMER_CACHE.append(
                    {
                        "box": box,
                        "tag": box.get("tag", box["name"][:2].upper()),
                        "sref": _normalize_sref(timer_data["sref"]),
                        "raw_sref": timer_data["sref"],
                        "eit": int(timer_data.get("eit") or 0),
                        "begin": int(begin),
                        "end": int(end),
                        "name": timer_data["name"],
                    }
                )
            if callable(on_changed_callback):
                on_changed_callback()
            try:
                auto_cleanup_old_timers(box)
            except Exception:
                pass
            sync_timer_cache_async()

            dir_info = remote_dir if remote_dir else "default"
            msg = "Timer added on %s (-%d / +%d min):\n%s\nPath: %s\n\n(%s)" % (
                box["name"],
                margin_before_min,
                margin_after_min,
                timer_data["name"],
                dir_info,
                statetext,
            )
            session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout=6)
        else:
            msg = "Box %s rejected the timer:\n%s" % (box["name"], statetext)
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=8)

    except urllib.error.HTTPError as e:
        msg = "HTTP error on %s (%s): %s" % (box["name"], box["ip"], e.code)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=8)
    except urllib.error.URLError as e:
        msg = "Cannot connect to %s (%s):\n%s" % (box["name"], box["ip"], e.reason)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=8)
    except Exception as e:
        msg = "Unexpected error (%s):\n%s" % (box["name"], str(e))
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=8)


def delete_timer_from_epg(session, timer_item, on_changed_callback=None):
    if timer_item["is_local"]:
        ok, statetext = _delete_local_timer_raw(session, timer_item)
        if ok:
            if callable(on_changed_callback):
                on_changed_callback()
            msg = "Timer cancelled (%s):\n%s" % (timer_item["box_name"], timer_item["name"])
            session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout=4)
        else:
            msg = "Error cancelling local timer:\n%s" % statetext
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
            msg = "Timer cancelled (%s):\n%s" % (box["name"], timer_item["name"])
            session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout=4)
        else:
            msg = "Box %s refused to cancel timer:\n%s" % (box["name"], statetext)
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except urllib.error.HTTPError as e:
        msg = "HTTP error while cancelling on %s: %s" % (box["name"], e.code)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except urllib.error.URLError as e:
        msg = "Cannot connect to %s:\n%s" % (box["name"], e.reason)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except Exception as e:
        msg = "Error while cancelling (%s):\n%s" % (box["name"], str(e))
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)


def on_box_selected(session, choice, timer_data, local_callback=None, on_changed_callback=None):
    if not choice:
        return

    action, payload = choice[1]

    if action == "SETUP":
        open_setup_screen(session)
        return

    if action == "DELETE":
        delete_timer_from_epg(session, payload, on_changed_callback=on_changed_callback)
        return

    if action == "LOCAL":
        if callable(local_callback):
            local_callback()
        return

    box = payload
    default_before, default_after = get_default_margins_minutes()

    def on_margins_confirmed(margins):
        if margins is None:
            return
        m_before, m_after = margins
        send_timer_http(
            session,
            box,
            timer_data,
            m_before,
            m_after,
            on_changed_callback=on_changed_callback,
        )

    session.openWithCallback(
        on_margins_confirmed,
        RemoteTimerMarginScreen,
        box,
        timer_data,
        default_before,
        default_after,
    )


def open_box_selector(session, event, service, local_callback=None, on_changed_callback=None):
    if event is None or service is None:
        session.open(
            MessageBox,
            "Failed to load event data (missing EPG or channel).",
            MessageBox.TYPE_ERROR,
            timeout=5,
        )
        return

    sref = get_sref_string(service)
    if not sref:
        session.open(
            MessageBox,
            "Missing Service Reference (sRef) for the selected channel.",
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
        "name": event.getEventName() or "No title",
        "desc": event.getShortDescription() or "",
        "eit": int(event.getEventId() or 0),
    }

    choices = []

    existing_timers = find_matching_timers_for_event(session, service, event)
    for ex in existing_timers:
        choices.append(
            (
                ">>> Cancel timer: %s (%s) <<<" % (ex["box_name"], ex["tag"]),
                ("DELETE", ex),
            )
        )

    if callable(local_callback):
        choices.append(("This receiver (%s)" % get_local_tag(), ("LOCAL", None)))

    active_boxes = get_active_boxes()
    for b in active_boxes:
        choices.append(("%s [%s] (%s)" % (b["name"], b["tag"], b["ip"]), ("BOX", b)))

    if not active_boxes:
        choices.append((">>> Configure remote receivers... <<<", ("SETUP", None)))

    title = "Record on: %s" % timer_data["name"]
    session.openWithCallback(
        lambda choice: on_box_selected(
            session,
            choice,
            timer_data,
            local_callback=local_callback,
            on_changed_callback=on_changed_callback,
        ),
        ChoiceBox,
        title=title,
        list=choices,
    )


# --- Combined overview, stopping and deleting timers and recordings ---

def _format_timer_state(state_str, disabled_str, end_ts, now_ts):
    if disabled_str == "1":
        return "Disabled"
    if state_str == "3":
        return "Done"
    if state_str == "2":
        return "Recording"
    if end_ts > 0 and end_ts < now_ts:
        return "Failed"
    if state_str == "1":
        return "Preparing"
    if state_str == "0":
        return "Waiting"
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
            name = str(getattr(t, "name", "No title") or "No title")
            filename = str(getattr(t, "Filename", "") or "")
            sref_obj = getattr(t, "service_ref", None)
            if sref_obj and hasattr(sref_obj, "getServiceName"):
                sname = sref_obj.getServiceName() or "Unknown channel"
            else:
                sname = "Unknown channel"
            sref_str = get_sref_string(sref_obj)

            time_txt = _format_time_range(begin_ts, end_ts)
            state_txt = _format_timer_state(state_str, disabled_str, end_ts, now_ts)

            timers.append(
                {
                    "is_local": True,
                    "box": None,
                    "box_name": "This receiver",
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
        sname = _xml_text(item, "e2servicename", "Unknown channel")
        name = _xml_text(item, "e2name", "No title")
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
    statetext = _xml_text(root, "e2statetext", "No response")
    return state_ok, statetext


def _stop_local_timer_raw(session, timer_item):
    rec_timer = getattr(session.nav, "RecordTimer", None)
    t_obj = timer_item.get("local_obj")
    if rec_timer is None or t_obj is None:
        return False, "Local timer not found"
    try:
        if hasattr(t_obj, "afterEvent"):
            t_obj.afterEvent = 0
        if hasattr(t_obj, "disable"):
            t_obj.disable()
        else:
            t_obj.disabled = True
        rec_timer.timeChanged(t_obj)
        return True, "Recording stopped"
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
    statetext = _xml_text(root, "e2statetext", "No response")
    return state_ok, statetext


def _delete_local_timer_raw(session, timer_item):
    rec_timer = getattr(session.nav, "RecordTimer", None)
    t_obj = timer_item.get("local_obj")
    if rec_timer is None or t_obj is None:
        return False, "Local timer not found"
    try:
        if hasattr(t_obj, "afterEvent"):
            t_obj.afterEvent = 0
        rec_timer.removeEntry(t_obj)
        return True, "Deleted"
    except Exception as e:
        return False, str(e)


def _delete_local_recording_raw(timer_item):
    filename = timer_item.get("filename", "")
    if not filename:
        t_obj = timer_item.get("local_obj")
        if t_obj is not None:
            filename = str(getattr(t_obj, "Filename", "") or "")
    if not filename:
        return False, "Recording file path not found"

    ts_path = filename if filename.endswith(".ts") else (filename + ".ts")
    base_no_ext = ts_path[:-3]

    # 1. Native deletion via Enigma2 eServiceCenter (also removes companion files)
    try:
        sref = eServiceReference("1:0:0:0:0:0:0:0:0:0:" + ts_path)
        service_handler = eServiceCenter.getInstance()
        offline = service_handler.offlineOperations(sref)
        if offline is not None and offline.deleteFromDisk(0) == 0:
            return True, "Recording deleted"
    except Exception:
        pass

    # 2. Fallback direct filesystem deletion
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
        return True, "Recording deleted"
    return False, "Recording file not found on disk"


def _find_remote_movie_sref(box, timer_item):
    filename = (timer_item.get("filename") or "").strip()
    if filename:
        ts_path = filename if filename.endswith(".ts") else (filename + ".ts")
        return "1:0:0:0:0:0:0:0:0:0:" + ts_path

    # Fallback: lookup recording via /web/movielist by title and start time
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
        return False, "Recording path not found"

    url_base = "http://%s:%d/web/moviedelete?" % (box["ip"], box["port"])
    params = {"sRef": movie_sref}
    url = url_base + urllib.parse.urlencode(params)
    req = _build_request(box, url)
    with urllib.request.urlopen(req, timeout=6) as resp:
        xml_data = resp.read()
    root = ET.fromstring(xml_data)
    state_ok = _xml_text(root, "e2state").lower() == "true"
    statetext = _xml_text(root, "e2statetext", "No response")
    return state_ok, statetext


def stop_any_timer(session, timer_item, delete_after=False):
    if timer_item["is_local"]:
        if delete_after:
            ok_del, del_txt = _delete_local_timer_raw(session, timer_item)
            if not ok_del:
                msg = "Error stopping and deleting local timer:\n%s" % del_txt
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
                msg = "Recording stopped, timer and recording deleted (%s):\n%s" % (
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
                msg = "Timer deleted, but deleting recording failed (%s):\n%s" % (
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
            msg = "Recording stopped (%s):\n%s" % (
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
            msg = "Error stopping local recording:\n%s" % statetext
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
                msg = "Box %s refused to stop and delete timer:\n%s" % (
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
                msg = "Recording stopped, timer and recording deleted (%s):\n%s" % (
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
                msg = "Timer deleted, but box %s failed to delete recording:\n%s" % (
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
            msg = "Recording stopped (%s):\n%s" % (box["name"], timer_item["name"])
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=3,
            )
        else:
            msg = "Box %s refused to stop recording:\n%s" % (box["name"], statetext)
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_ERROR,
                timeout=6,
            )
    except urllib.error.HTTPError as e:
        msg = "HTTP error while stopping on %s: %s" % (box["name"], e.code)
        session.openWithCallback(
            lambda _res: open_combined_timers(session),
            MessageBox,
            msg,
            MessageBox.TYPE_ERROR,
            timeout=6,
        )
    except urllib.error.URLError as e:
        msg = "Cannot connect to %s:\n%s" % (box["name"], e.reason)
        session.openWithCallback(
            lambda _res: open_combined_timers(session),
            MessageBox,
            msg,
            MessageBox.TYPE_ERROR,
            timeout=6,
        )
    except Exception as e:
        msg = "Error while stopping (%s):\n%s" % (box["name"], str(e))
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
    msg = "Deleted %d finished/failed timers across all receivers." % deleted
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
            msg = "Timer deleted from %s:\n%s" % (timer_item["box_name"], timer_item["name"])
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=3,
            )
        else:
            msg = "Error deleting local timer:\n%s" % statetext
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
        return

    box = timer_item["box"]
    try:
        state_ok, statetext = _delete_single_timer_raw(box, timer_item)
        if state_ok:
            sync_timer_cache_async()
            msg = "Timer deleted from %s:\n%s" % (box["name"], timer_item["name"])
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=3,
            )
        else:
            msg = "Box %s refused to delete timer:\n%s" % (box["name"], statetext)
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except urllib.error.HTTPError as e:
        msg = "HTTP error while deleting on %s: %s" % (box["name"], e.code)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except urllib.error.URLError as e:
        msg = "Cannot connect to %s:\n%s" % (box["name"], e.reason)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except Exception as e:
        msg = "Error while deleting (%s):\n%s" % (box["name"], str(e))
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

    # Sort chronologically by start date and time
    all_timers.sort(key=lambda t: (t["begin"], t["end"], t["name"]))

    now_ts = int(time.time())
    finished_or_failed = [t for t in all_timers if _is_finished_or_failed(t, now_ts)]

    rows_spec = []
    if not active_boxes:
        rows_spec.append(
            ("BANNER", "OPEN_SETUP", ">>> No remote box configured - open setup <<<")
        )

    if offline_boxes:
        rows_spec.append(
            ("BANNER", "OFFLINE_INFO", "[!] Offline: %s" % ", ".join(offline_boxes))
        )

    if finished_or_failed:
        rows_spec.append(
            (
                "BANNER",
                "CLEANUP_ALL",
                ">>> DELETE ALL FINISHED AND FAILED (%d) <<<" % len(finished_or_failed),
            )
        )

    for t in all_timers:
        rows_spec.append(("TIMER", t, ""))

    if not rows_spec:
        rows_spec.append(
            ("BANNER", "OPEN_SETUP", "No timers (YELLOW button = box setup)")
        )

    def on_screen_closed(result):
        if not result:
            return
        cmd, selected = result

        if cmd == "OPEN_SETUP" or selected == "OPEN_SETUP":
            open_setup_screen(session, callback=lambda _saved: open_combined_timers(session))
            return

        if cmd == "STOP_REC":
            if not isinstance(selected, dict) or selected.get("state") != "2":
                session.openWithCallback(
                    lambda _res: open_combined_timers(session),
                    MessageBox,
                    "Selected timer is not currently recording.",
                    MessageBox.TYPE_INFO,
                    timeout=3,
                )
                return

            t_item = selected
            stop_choices = [
                ("STOP REC", "STOP_ONLY"),
                ("STOP & DELETE Recording", "STOP_DELETE"),
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

            stop_title = "Stop recording [%s]: %s" % (t_item["tag"], t_item["name"])
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
                "Delete all finished and failed timers (%d) from all receivers?"
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
        confirm_msg = "Delete timer from [%s] %s?\n\n%s\n%s (%s)" % (
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

    legend_parts = ["[%s]=Local" % get_local_tag()] + [
        "[%s]=%s" % (b.get("tag", b["name"][:2].upper()), b["name"]) for b in active_boxes
    ]
    title = "All Timers: " + "  ".join(legend_parts)
    session.openWithCallback(on_screen_closed, CombinedTimersScreen, title, rows_spec)


def timer_menu_entry(menuid, **kwargs):
    if menuid == "mainmenu":
        return [("All Timers", open_combined_timers, "remote_timer_main", 15)]
    if menuid == "timermenu":
        return [
            ("All Timers", open_combined_timers, "remote_timer_select", 50),
            ("Remote Timers Setup", open_setup_screen, "remote_timer_setup", 51),
        ]
    return []


# --- EPG Hook (REC button + automatic marks in EPG) ---

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
            name="All Timers",
            description="Combined list of timers from all receivers",
            where=PluginDescriptor.WHERE_MENU,
            fnc=timer_menu_entry,
            needsRestart=False,
        ),
        PluginDescriptor(
            name="Remote Recording",
            description="Add a timer to a remote receiver",
            where=PluginDescriptor.WHERE_EVENTINFO,
            fnc=eventinfo,
            needsRestart=False,
        ),
        PluginDescriptor(
            name="Remote Recording",
            description="Record current event on a remote receiver",
            where=PluginDescriptor.WHERE_EXTENSIONSMENU,
            fnc=main_extension,
            needsRestart=False,
        ),
        PluginDescriptor(
            name="All Timers",
            description="Combined list and deletion of timers from all receivers",
            where=[
                PluginDescriptor.WHERE_EXTENSIONSMENU,
                PluginDescriptor.WHERE_PLUGINMENU,
            ],
            fnc=open_combined_timers,
            needsRestart=False,
        ),
        PluginDescriptor(
            name="Remote Timers - Setup",
            description="Configure IP addresses and tags of remote receivers",
            where=PluginDescriptor.WHERE_PLUGINMENU,
            fnc=open_setup_screen,
            needsRestart=False,
        ),
    ]
