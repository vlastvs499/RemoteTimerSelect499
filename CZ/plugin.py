# -*- coding: utf-8 -*-
import base64
from datetime import datetime
import inspect
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

# Interval aktualizace EPG znacek na pozadi (v sekundach)
CACHE_REFRESH_SEC = 300

# Velikost pisma v souhrnnem prehledu vsech casovacu
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
        self.setTitle("Nastavení vzdálených časovačů")

        self["key_red"] = StaticText("Zrušit")
        self["key_green"] = StaticText("Uložit")
        self["footnote"] = StaticText("OK = klávesnice pro text   |   Zelená = uložit")
        self["description"] = StaticText("")

        cfg = config.plugins.remotetimerselect
        self.list = [
            (
                getConfigListEntry("Označení tohoto přijímače", cfg.local_tag),
                "Krátká značka v přehledu časovačů pro tento lokální přijímač (výchozí: L).",
            ),
            (
                getConfigListEntry("Auto-mazání hotových/selhaných (dny)", cfg.auto_cleanup_days),
                "Po kolika dnech automaticky mazat hotové a selhané časovače (0 = vypnuto).",
            ),
        ]

        for idx in range(1, 5):
            b_cfg = getattr(cfg, "box%d" % idx)
            self.list.append(
                (
                    getConfigListEntry("Box %d - Název přijímače" % idx, b_cfg.name),
                    "Název %d. vzdáleného boxu v nabídce a hláškách (např. Obývák nebo SF8008)." % idx,
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - Označení (značka)" % idx, b_cfg.tag),
                    "Krátká značka v EPG a časovačích pro %d. box (např. M, V, B%d)." % (idx, idx),
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - IP adresa (0.0.0.0 = vypnuto)" % idx, b_cfg.ip),
                    "IP adresa %d. boxu v místní síti (čísly na ovladači). 0.0.0.0 = nepoužívá se." % idx,
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - HTTP port OpenWebif" % idx, b_cfg.port),
                    "HTTP port rozhraní OpenWebif na %d. boxu (výchozí je 80)." % idx,
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - Uživatel OpenWebif" % idx, b_cfg.user),
                    "Uživatelské jméno pro OpenWebif (nech prázdné, pokud není zapnuté heslo).",
                )
            )
            self.list.append(
                (
                    getConfigListEntry("Box %d - Heslo OpenWebif" % idx, b_cfg.password),
                    "Heslo pro OpenWebif na %d. boxu (nech prázdné, pokud není vyžadováno)." % idx,
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
        "Nahrává": 0x00FF6666,
        "Čeká": 0x0077DD77,
        "Hotovo": 0x0088CCFF,
        "Selhalo": 0x00FFAA44,
        "Příprava": 0x00FFEE66,
        "Vypnuto": 0x00999999,
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
        self.setTitle("Všechny časovače")

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
                '<screen name="CombinedTimersScreen" position="50,55" size="1820,970" title="Všechny časovače">'
                '<widget source="title_text" render="Label" position="25,15" size="1770,50" font="Regular;34" foregroundColor="#00ffcc33" noWrap="1" />'
                '<widget name="list" position="25,75" size="1770,%d" font="Regular;%d" itemHeight="%d" scrollbarMode="showOnDemand" enableWrapAround="1" />'
                '<widget source="hint_ok" render="Label" position="25,922" size="210,38" font="Regular;28" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_red" render="Label" position="235,922" size="140,38" font="Regular;28" foregroundColor="#00ff5555" noWrap="1" />'
                '<widget source="hint_stop" render="Label" position="375,922" size="195,38" font="Regular;28" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_yellow" render="Label" position="570,922" size="105,38" font="Regular;28" foregroundColor="#00ffdd33" noWrap="1" />'
                '<widget source="hint_rest" render="Label" position="675,922" size="1120,38" font="Regular;28" foregroundColor="#00aaaaaa" noWrap="1" />'
                "</screen>"
            ) % (rows_h, font_sz, item_h)
        else:
            font_sz = int(TIMER_LIST_FONT_HD)
            item_h = int(font_sz * 1.40)
            rows_h = (546 // item_h) * item_h
            self.skin = (
                '<screen name="CombinedTimersScreen" position="30,35" size="1220,650" title="Všechny časovače">'
                '<widget source="title_text" render="Label" position="15,10" size="1190,36" font="Regular;24" foregroundColor="#00ffcc33" noWrap="1" />'
                '<widget name="list" position="15,52" size="1190,%d" font="Regular;%d" itemHeight="%d" scrollbarMode="showOnDemand" enableWrapAround="1" />'
                '<widget source="hint_ok" render="Label" position="15,606" size="155,32" font="Regular;20" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_red" render="Label" position="170,606" size="100,32" font="Regular;20" foregroundColor="#00ff5555" noWrap="1" />'
                '<widget source="hint_stop" render="Label" position="270,606" size="145,32" font="Regular;20" foregroundColor="#00aaaaaa" noWrap="1" />'
                '<widget source="hint_yellow" render="Label" position="415,606" size="75,32" font="Regular;20" foregroundColor="#00ffdd33" noWrap="1" />'
                '<widget source="hint_rest" render="Label" position="490,606" size="715,32" font="Regular;20" foregroundColor="#00aaaaaa" noWrap="1" />'
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
        self["hint_ok"] = StaticText("OK = smazat  |")
        self["hint_red"] = StaticText("ČERVENÁ")
        self["hint_stop"] = StaticText("= stop REC  |")
        self["hint_yellow"] = StaticText("ŽLUTÁ")
        self["hint_rest"] = StaticText("/ MENU = nastavení boxů  |  EXIT = zavřít")
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
        self.setTitle("Posun času (%s)" % box["name"])

        self["key_red"] = StaticText("Zrušit")
        self["key_green"] = StaticText("Nahrát")
        self["footnote"] = StaticText("")
        self["description"] = StaticText(timer_data["name"])

        val_before = max(0, min(120, int(default_before)))
        val_after = max(0, min(180, int(default_after)))

        self.cfg_before = ConfigSelectionNumber(0, 120, 1, default=val_before)
        self.cfg_after = ConfigSelectionNumber(0, 180, 1, default=val_after)

        self.list = [
            getConfigListEntry("Posun před pořadem (min)", self.cfg_before),
            getConfigListEntry("Posun za pořadem (min)", self.cfg_after),
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
                name = _xml_text(item, "e2name", "Bez názvu")
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
                            "box_name": "Tento přijímač",
                            "tag": l_tag,
                            "local_obj": t,
                            "sref": t_sref,
                            "begin": t_begin,
                            "end": t_end,
                            "name": str(getattr(t, "name", "Bez názvu") or "Bez názvu"),
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
                    "name": t.get("name", "Bez názvu"),
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
        statetext = _xml_text(root, "e2statetext", "Bez odpovědi")

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

            dir_info = remote_dir if remote_dir else "výchozí"
            msg = "Časovač přidán na %s (-%d / +%d min):\n%s\nCesta: %s\n\n(%s)" % (
                box["name"],
                margin_before_min,
                margin_after_min,
                timer_data["name"],
                dir_info,
                statetext,
            )
            session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout=6)
        else:
            msg = "Box %s časovač odmítl:\n%s" % (box["name"], statetext)
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=8)

    except urllib.error.HTTPError as e:
        msg = "HTTP chyba na %s (%s): %s" % (box["name"], box["ip"], e.code)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=8)
    except urllib.error.URLError as e:
        msg = "Nelze se připojit k %s (%s):\n%s" % (box["name"], box["ip"], e.reason)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=8)
    except Exception as e:
        msg = "Neočekávaná chyba (%s):\n%s" % (box["name"], str(e))
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=8)


def delete_timer_from_epg(session, timer_item, on_changed_callback=None):
    if timer_item["is_local"]:
        ok, statetext = _delete_local_timer_raw(session, timer_item)
        if ok:
            if callable(on_changed_callback):
                on_changed_callback()
            msg = "Časovač zrušen (%s):\n%s" % (timer_item["box_name"], timer_item["name"])
            session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout=4)
        else:
            msg = "Chyba při rušení lokálního časovače:\n%s" % statetext
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
            msg = "Časovač zrušen (%s):\n%s" % (box["name"], timer_item["name"])
            session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout=4)
        else:
            msg = "Box %s odmítl zrušit časovač:\n%s" % (box["name"], statetext)
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except urllib.error.HTTPError as e:
        msg = "HTTP chyba při rušení na %s: %s" % (box["name"], e.code)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except urllib.error.URLError as e:
        msg = "Nelze se připojit k %s:\n%s" % (box["name"], e.reason)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except Exception as e:
        msg = "Chyba při rušení (%s):\n%s" % (box["name"], str(e))
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
            "Nepodařilo se načíst data o pořadu (chybí EPG nebo kanál).",
            MessageBox.TYPE_ERROR,
            timeout=5,
        )
        return

    sref = get_sref_string(service)
    if not sref:
        session.open(
            MessageBox,
            "Chybí Service Reference (sRef) vybraného kanálu.",
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
        "name": event.getEventName() or "Bez názvu",
        "desc": event.getShortDescription() or "",
        "eit": int(event.getEventId() or 0),
    }

    choices = []

    existing_timers = find_matching_timers_for_event(session, service, event)
    for ex in existing_timers:
        choices.append(
            (
                ">>> Zrušit časovač: %s (%s) <<<" % (ex["box_name"], ex["tag"]),
                ("DELETE", ex),
            )
        )

    if callable(local_callback):
        choices.append(("Tento přijímač (%s)" % get_local_tag(), ("LOCAL", None)))

    active_boxes = get_active_boxes()
    for b in active_boxes:
        choices.append(("%s [%s] (%s)" % (b["name"], b["tag"], b["ip"]), ("BOX", b)))

    if not active_boxes:
        choices.append((">>> Nastavit vzdálené přijímače... <<<", ("SETUP", None)))

    title = "Kam nahrát: %s" % timer_data["name"]
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


# --- Souhrnny prehled, zastaveni a mazani casovacu ze vsech prijimacu ---

def _format_timer_state(state_str, disabled_str, end_ts, now_ts):
    if disabled_str == "1":
        return "Vypnuto"
    if state_str == "3":
        return "Hotovo"
    if state_str == "2":
        return "Nahrává"
    if end_ts > 0 and end_ts < now_ts:
        return "Selhalo"
    if state_str == "1":
        return "Příprava"
    if state_str == "0":
        return "Čeká"
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
            name = str(getattr(t, "name", "Bez názvu") or "Bez názvu")
            sref_obj = getattr(t, "service_ref", None)
            if sref_obj and hasattr(sref_obj, "getServiceName"):
                sname = sref_obj.getServiceName() or "Neznámý kanál"
            else:
                sname = "Neznámý kanál"
            sref_str = get_sref_string(sref_obj)

            time_txt = _format_time_range(begin_ts, end_ts)
            state_txt = _format_timer_state(state_str, disabled_str, end_ts, now_ts)

            timers.append(
                {
                    "is_local": True,
                    "box": None,
                    "box_name": "Tento přijímač",
                    "tag": l_tag,
                    "local_obj": t,
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
        sname = _xml_text(item, "e2servicename", "Neznámý kanál")
        name = _xml_text(item, "e2name", "Bez názvu")
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
    statetext = _xml_text(root, "e2statetext", "Bez odpovědi")
    return state_ok, statetext


def _stop_local_timer_raw(session, timer_item):
    rec_timer = getattr(session.nav, "RecordTimer", None)
    t_obj = timer_item.get("local_obj")
    if rec_timer is None or t_obj is None:
        return False, "Lokální časovač nenalezen"
    try:
        if hasattr(t_obj, "afterEvent"):
            t_obj.afterEvent = 0
        if hasattr(t_obj, "disable"):
            t_obj.disable()
        else:
            t_obj.disabled = True
        rec_timer.timeChanged(t_obj)
        return True, "Nahrávání zastaveno"
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
    statetext = _xml_text(root, "e2statetext", "Bez odpovědi")
    return state_ok, statetext


def _delete_local_timer_raw(session, timer_item):
    rec_timer = getattr(session.nav, "RecordTimer", None)
    t_obj = timer_item.get("local_obj")
    if rec_timer is None or t_obj is None:
        return False, "Lokální časovač nenalezen"
    try:
        if hasattr(t_obj, "afterEvent"):
            t_obj.afterEvent = 0
        rec_timer.removeEntry(t_obj)
        return True, "Smazáno"
    except Exception as e:
        return False, str(e)


def stop_any_timer(session, timer_item, delete_after=False):
    if timer_item["is_local"]:
        if delete_after:
            ok_del, del_txt = _delete_local_timer_raw(session, timer_item)
            if ok_del:
                msg = "Nahrávání zastaveno a časovač smazán (%s):\n%s" % (
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
                msg = "Chyba při zastavení a smazání:\n%s" % del_txt
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
            msg = "Nahrávání zastaveno (%s):\n%s" % (
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
            msg = "Chyba při zastavení lokálního nahrávání:\n%s" % statetext
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
            if del_ok:
                msg = "Nahrávání zastaveno a časovač smazán (%s):\n%s" % (
                    box["name"],
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
                msg = "Box %s odmítl zastavit a smazat časovač:\n%s" % (
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

        state_ok, statetext = _stop_remote_timer_raw(box, timer_item)
        sync_timer_cache_async()
        if state_ok:
            msg = "Nahrávání zastaveno (%s):\n%s" % (box["name"], timer_item["name"])
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=3,
            )
        else:
            msg = "Box %s odmítl zastavit nahrávání:\n%s" % (box["name"], statetext)
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_ERROR,
                timeout=6,
            )
    except urllib.error.HTTPError as e:
        msg = "HTTP chyba při zastavení na %s: %s" % (box["name"], e.code)
        session.openWithCallback(
            lambda _res: open_combined_timers(session),
            MessageBox,
            msg,
            MessageBox.TYPE_ERROR,
            timeout=6,
        )
    except urllib.error.URLError as e:
        msg = "Nelze se připojit k %s:\n%s" % (box["name"], e.reason)
        session.openWithCallback(
            lambda _res: open_combined_timers(session),
            MessageBox,
            msg,
            MessageBox.TYPE_ERROR,
            timeout=6,
        )
    except Exception as e:
        msg = "Chyba při zastavení (%s):\n%s" % (box["name"], str(e))
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
    msg = "Smazáno %d hotových/selhaných časovačů ze všech přijímačů." % deleted
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
            msg = "Časovač smazán z %s:\n%s" % (timer_item["box_name"], timer_item["name"])
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=3,
            )
        else:
            msg = "Chyba při mazání lokálního časovače:\n%s" % statetext
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
        return

    box = timer_item["box"]
    try:
        state_ok, statetext = _delete_single_timer_raw(box, timer_item)
        if state_ok:
            sync_timer_cache_async()
            msg = "Časovač smazán z %s:\n%s" % (box["name"], timer_item["name"])
            session.openWithCallback(
                lambda _res: open_combined_timers(session),
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=3,
            )
        else:
            msg = "Box %s odmítl smazat časovač:\n%s" % (box["name"], statetext)
            session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except urllib.error.HTTPError as e:
        msg = "HTTP chyba při mazání na %s: %s" % (box["name"], e.code)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except urllib.error.URLError as e:
        msg = "Nelze se připojit k %s:\n%s" % (box["name"], e.reason)
        session.open(MessageBox, msg, MessageBox.TYPE_ERROR, timeout=6)
    except Exception as e:
        msg = "Chyba při mazání (%s):\n%s" % (box["name"], str(e))
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
            ("BANNER", "OPEN_SETUP", ">>> Není nastaven žádný vzdálený box – otevřít nastavení <<<")
        )

    if offline_boxes:
        rows_spec.append(
            ("BANNER", "OFFLINE_INFO", "[!] Nedostupné: %s" % ", ".join(offline_boxes))
        )

    if finished_or_failed:
        rows_spec.append(
            (
                "BANNER",
                "CLEANUP_ALL",
                ">>> SMAZAT VŠECHNY HOTOVÉ A SELHANÉ (%d) <<<" % len(finished_or_failed),
            )
        )

    for t in all_timers:
        rows_spec.append(("TIMER", t, ""))

    if not rows_spec:
        rows_spec.append(
            ("BANNER", "OPEN_SETUP", "Žádné časovače (ŽLUTÉ tlačítko = nastavení boxů)")
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
                    "Vybraný časovač právě nenahrává.",
                    MessageBox.TYPE_INFO,
                    timeout=3,
                )
                return

            t_item = selected
            stop_choices = [
                ("STOP REC", "STOP_ONLY"),
                ("STOP REC & DELETE", "STOP_DELETE"),
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

            stop_title = "Ukončit nahrávání [%s]: %s" % (t_item["tag"], t_item["name"])
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
                "Hromadně smazat všechny hotové a selhané časovače (%d) ze všech přijímačů?"
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
        confirm_msg = "Smazat časovač z [%s] %s?\n\n%s\n%s (%s)" % (
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

    legend_parts = ["[%s]=Tento" % get_local_tag()] + [
        "[%s]=%s" % (b.get("tag", b["name"][:2].upper()), b["name"]) for b in active_boxes
    ]
    title = "Všechny časovače: " + "  ".join(legend_parts)
    session.openWithCallback(on_screen_closed, CombinedTimersScreen, title, rows_spec)


def timer_menu_entry(menuid, **kwargs):
    if menuid == "mainmenu":
        return [("Všechny časovače", open_combined_timers, "remote_timer_main", 15)]
    if menuid == "timermenu":
        return [
            ("Všechny časovače", open_combined_timers, "remote_timer_select", 50),
            ("Nastavení vzdálených časovačů", open_setup_screen, "remote_timer_setup", 51),
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
            name="Všechny časovače",
            description="Souhrnný seznam časovačů ze všech přijímačů",
            where=PluginDescriptor.WHERE_MENU,
            fnc=timer_menu_entry,
            needsRestart=False,
        ),
        PluginDescriptor(
            name="Vzdálené nahrávání",
            description="Přidat časovač na vzdálený přijímač",
            where=PluginDescriptor.WHERE_EVENTINFO,
            fnc=eventinfo,
            needsRestart=False,
        ),
        PluginDescriptor(
            name="Vzdálené nahrávání",
            description="Nahrát aktuální pořad na vzdálený přijímač",
            where=PluginDescriptor.WHERE_EXTENSIONSMENU,
            fnc=main_extension,
            needsRestart=False,
        ),
        PluginDescriptor(
            name="Všechny časovače",
            description="Souhrnný seznam a mazání časovačů ze všech přijímačů",
            where=[
                PluginDescriptor.WHERE_EXTENSIONSMENU,
                PluginDescriptor.WHERE_PLUGINMENU,
            ],
            fnc=open_combined_timers,
            needsRestart=False,
        ),
        PluginDescriptor(
            name="Vzdálené časovače - nastavení",
            description="Konfigurace IP adres a označení vzdálených přijímačů",
            where=PluginDescriptor.WHERE_PLUGINMENU,
            fnc=open_setup_screen,
            needsRestart=False,
        ),
    ]
