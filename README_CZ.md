# RemoteTimerSelect499

> **Language / Jazyk / Sprache:** [English (README.md)](README.md) | **Čeština** | [Deutsch (README_DE.md)](README_DE.md)

Plugin byl vytvořen jako náhrada pluginu **RemoteTimer** pro **OpenATV / Enigma2 (Python 3)**.
Plánujte, prohlížejte a spravujte časovače na svém lokálním přijímači a až **4 vzdálených přijímačích Enigma2** přímo z EPG nebo ze živého vysílání — vše s pohodlným nastavením přímo pomocí dálkového ovladače.

## Funkce

* **Nahrávání z EPG a volitelně ze živého vysílání:** Stisknutím **REC v EPG** (nebo volitelně při sledování živého TV vysílání) vyberete lokální či vzdálený přijímač, nastavíte posun před/za pořadem, zapnete **Nekonečné nahrávání**, případně zrušíte již existující časovač.

* **Zobrazení stavu přijímačů ve výběru:** Přijímače, které právě nahrávají, jsou zvýrazněny **červeně** (`REC do: 19:00` nebo `REC do: ∞` v případě nekonečného nahrávání). Přijímače s plánovaným časovačem do 100 minut jsou zde zvýrazněny **žlutě** (`Plán. REC za: 45 min`). Tím se předejde jejich výběru a zrušení zamýšleného nahrávání na další obrazovce kvůli překryvu pořadů na různých stanicích. 

* **Značky časovačů přímo v EPG:** Naplánované pořady jsou v seznamu EPG automaticky označeny vlastní značkou přijímače, který bude záznam provádět (např. `[L]`, `[M]`, `[V]`). Ta se nastavuje v nastavení, kde se zadávají vzdálené přijímače v MENU/Časovače/Nastavení vzdálených časovačů. Toto nastavení je i v seznamu pluginů.

* **Souhrnná obrazovka „Všechny časovače“:** Zobrazuje všechny lokální i vzdálené časovače v jednom chronologicky seřazeném přehledu (`Datum a čas` → `Stav` → `Značka` → `Kanál | Pořad`) s barevným stavem, symbolem `∞` a blikající indikací `[Nahrává]` u běžících nekonečných nahrávek. V OpenATV je vhodné si tuto položku posunout na první obrazovce nahoru (najet na tuto položku Všechny časovače - modrým povolit úpravy, pak stisk zeleného a posunout nahoru. Pak znovu zelené tlačítko, pak modré, hotovo).
* 
* **Rychlá změna konce nahrávání:** Stisknutím **MODRÉHO** tlačítka ve *Všechny časovače* upravíte čas konce probíhajícího nebo čekajícího časovače (`±1 min` / `±5 min`) včetně ochrany proti kolizi (1 minuta bezpečnostní rezervy před dalším čekajícím časovačem na stejném přijímači). Pokud se tedy konec vámi nataženého času přiblíží dalšímu plánovanému záznamu, další natažení času se zablokuje.

* **Zastavení i smazání nahrávky:** V seznamu Všechny časovače stiskem **ČERVENÉHO** tlačítka na běžícím nahrávání vyberete **STOP REC** nebo **STOP REC & SMAZAT NAHRÁVKU** (zastaví nahrávání a smaže časovač i soubor z disku). Také tlačítko OK je možné zastavt nahrávání a smazat časovač, ovšem nikoli záznam.

* **Dynamická cesta a podpora uspaných disků:** Automaticky zjišťuje aktivní složku pro nahrávání na vzdáleném boxu a odesílání časovače řeší na pozadí s prodlouženým časovým limitem, takže se uspaný HDD roztočí bez timeoutů a zamrzání (plně kompatibilní s OpenATV 8.0).
* Pro usnadnění cesty k záznamu a její jednoduché změně nahrává vzdálený časovač do složky záznamů, ve které právě je. Je to nejrychlejší varianta, jak změnit cestu do složky, kam chceme, aby nahrával. Pokud si nastavíte složku 1 pro první záznam a pak ji pro jiný záznam změníte, nebude se nahrávat do poslední nastavené složky, ale do první půjde první záznam a do druhé druhý. Cesty tedy zůstávají zachovány.

* **Nastavení ovladačem a automatický úklid:** Konfigurace až 4 vzdálených boxů přímo v přijímači (ukládá se do `/etc/enigma2/settings`) s automatickým i hromadným mazáním hotových a selhaných časovačů.

## Instalace

### Možnost 1: Rychlá instalace přes SSH nebo Telnet (RCC / DCC)

Připojte se k přijímači přes **SSH** nebo **Telnet** (např. přes **PuTTY**, **RCC** nebo **DCC**) jako `root` a spusťte příkazy pro zvolený jazyk.
Zkopírujte všechny tyto příkazy pro jazyk, který chcete, po nainstalování stiskněte za posledním Enter. Proběhne restart Enigmy.

#### Česká verze (`CZ`)

```bash
mkdir -p /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/__init__.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/CZ/__init__.py
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/plugin.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/CZ/plugin.py
killall -9 enigma2
```

#### Anglická verze (`EN`)

```bash
mkdir -p /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/__init__.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/EN/__init__.py
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/plugin.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/EN/plugin.py
killall -9 enigma2
```

#### Německá verze (`DE`)

```bash
mkdir -p /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/__init__.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/DE/__init__.py
wget -O /usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/plugin.py https://raw.githubusercontent.com/vlastvs499/RemoteTimerSelect499/main/DE/plugin.py
killall -9 enigma2
```

### Možnost 2: Ruční instalace

1. Vytvořte na přijímači složku `/usr/lib/enigma2/python/Plugins/Extensions/RemoteTimerSelect499/`.
2. Zkopírujte soubory `__init__.py` a `plugin.py` ze složky `CZ/`, `EN/` nebo `DE/` do této složky (zachovejte kódování **UTF-8** a konce řádků **LF**).
3. Restartujte GUI Enigmy2 (`killall -9 enigma2` nebo přes **Menu → Pohotovostní režim / Restart → Restartovat GUI**).

> **Tip:** Pokud máte více přijímačů, nainstalujte plugin na všechny — můžete pak plánovat a spravovat časovače napříč všemi boxy z kteréhokoli přijímače, u kterého zrovna sedíte.

## Nastavení (dálkovým ovladačem)

1. Otevřete nastavení některou z těchto cest:
   * **Menu → Všechny časovače**, poté stiskněte **ŽLUTÉ** tlačítko nebo **MENU**
   * nebo:
   * **Menu → Časovače → Nastavení vzdálených časovačů**
   * nebo:
   * **Pluginy → Vzdálené časovače - nastavení**
   * 
2. Nastavte jednotlivé položky:
   * **Označení lokálního (hlavního) přijímače** (max. 2 znaky, výchozí: `L`) - dva znaky záměrně - obecně je ideální dávat krátké názvy, nejlépe znak jeden - budou se totiž zobrazovat v EPG před naplánovaným nahráváním.
   *    * **Auto-mazání hotových/selhaných (dny)** (`0` = vypnuto)
   * **Výběr boxu i tlačítkem REC** (`Ne` = klasické chování tlačítka nahrávání OpenATV bez možnosti výběru přijímačů, `Ano` = při stisku REC se zobrazí výběr přijímačů). Při výběru z EPG je výběr přijímačů k dispozici vždy.
   * **Až 4 vzdálené boxy:** stiskem **OK** na textových polích otevřete virtuální klávesnici, IP adresy zadávejte číselnými tlačítky (`0–9`, nepoužité sloty nechte na `0.0.0.0`), výchozí port OpenWebif je `80`.
3. Uložte stiskem **ZELENÉHO** tlačítka. Vzdálené časovače se ihned sesynchronizují bez nutnosti restartu GUI.

## Používání

* **EPG:** Najeďte na libovolný pořad a stiskněte **REC** pro naplánování nebo zrušení časovače na kterémkoli nastaveném boxu.
* **Okamžité nahrávání (volitelné):** Je-li funkce povolena v nastavení partnerských boxů, stisknutím tlačítka **REC** se otevře výběr tohoto pluginu s nabídkou vzdálených boxů. Při nepovolení položky **„Výběr boxu tlačítkem REC (živé TV)“** se nabídka boxů neotevře a přijímač se bude chovat v OpenATV klasicky.
* **Všechny časovače (`Menu → Všechny časovače`):**
  * **OK:** Smazání vybraného časovače, i když právě probíhá - smaže se časovač a nahrávání, ne samotný záznam (je možné i hromadné smazání všech hotových a selhaných přes horní lištu).
  * **ČERVENÁ:** Zastavení probíhajícího nahrávání (**STOP REC** nebo **STOP REC & SMAZAT NAHRÁVKU**).
  * **MODRÁ:** Změna konce probíhajícího nebo čekajícího nahrávání (`VLEVO/VPRAVO` = ±1 min, `NAHORU/DOLŮ` = ±5 min).
  * **ŽLUTÁ / MENU:** Otevření nastavení boxů.


 > **Tip**: Doporučuji nastavit volbu Výběr boxu i tlačítkem REC na Ano (najdete v Pluginy → Vzdálené časovače - nastavení → Výběr boxu i tlačítkem REC). Alternativní cesta: Menu - Časovače - Nastavení vzdálených časovačů - Výběr boxu i tlačítkem REC. Pak bude veškeré ovládání nahrávání jednotné, včetně lokálního. V případě zákazu tohoto tlačítka je okamžité nahrávání řízeno systémem.

## Přehled změn (Changelog)

### 26.–27.11.2026

* **Volitelné tlačítko REC při živém vysílání:** Přidán přepínač (*Výběr boxu tlačítkem REC (živé TV)*) pro otevření výběru přijímačů přímo ze živého vysílání (plná podpora OpenATV 8.0).
* **Změna konce REC (MODRÉ tlačítko):** Přidána úprava času konce u probíhajících i čekajících časovačů ve *Všech časovačích* s 1minutovou bezpečnostní rezervou proti kolizi s následujícím čekajícím časovačem na stejném boxu.
* **Nekonečné nahrávání a blikající indikace:** Přidána volba *Nekonečné nahrávání* (24 hod.), zarovnaný symbol **`∞`** a blikající stav `[Nahrává]` (1× za sekundu) ve *Všech časovačích*.
* **Žluté upozornění na brzké plánované nahrávání:** Přijímače s naplánovaným časovačem do 100 minut se ve výběru zvýrazňují **žlutě** (`Plán. REC za: X min`).
* **Podpora roztáčení uspaných disků:** Odesílání vzdáleného časovače probíhá na pozadí s prodlouženým timeoutem a hláškou *Připojuji (roztáčím) disk...*, aby nedocházelo k zamrzání nebo chybám při probouzení disku.

Upozornění: pokud se vám přijímač po pár hodinách běhu zpomalí, nebo zcela zasekne, máte na některém vzdáleném boxu 2 stejná připojení na jeden disk (můj případ). Jedno připojení smažte.
