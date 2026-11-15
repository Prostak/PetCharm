#!/usr/bin/env python3
"""Which missing battle pets are easiest to get?

Reads the pets you don't have from the PetCharm addon's SavedVariables
(WTF/Account/*/SavedVariables/PetCharm.lua, written on logout or /reload) and
sorts them by how easy they are to get, using the source the game's pet journal
shows for each pet (the same data Rematch shows):

  1. Catch in the wild            (Pet Battle source; grouped by zone)
  2. Buy from a vendor for gold
  3. Quest, vendor for a special currency, treasure, reputation, Trading Post
  4. Profession, Discovery
  5. Achievement, PvP, unknown source
  6. Random drop, raid, seasonal or special event
  7. Promotion, Trading Card Game, In-Game Shop (real money / limited time)

A pet with several sources counts by its easiest one. Pets that can be traded
are marked [аукцион]: they can also be bought on the Auction House.
Currency and item names in prices are looked up on Wowhead (cached).

Run:
  python3 "/Applications/World of Warcraft/_retail_/Interface/AddOns/PetCharm/missing_pets.py"
  python3 missing_pets.py --top 30      # more lines per group
  python3 missing_pets.py --all         # everything
"""

import argparse
import glob
import json
import os
import re
import urllib.request
from collections import defaultdict
from datetime import datetime

DEFAULT_WOW = "/Applications/World of Warcraft/_retail_"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ppc_cache", "names.json")

# BATTLE_PET_SOURCE_<n> index -> tier. The labels themselves come from the game.
SOURCE_TIER = {
    5: 1,   # Pet Battle (wild)
    3: 2,   # Vendor (bumped to 3 when the price is not plain gold)
    2: 3,   # Quest
    12: 3,  # Trading Post
    4: 4,   # Profession
    11: 4,  # Discovery
    6: 5,   # Achievement
    1: 6,   # Drop
    7: 6,   # World Event
    8: 7,   # Promotion
    9: 7,   # Trading Card Game
    10: 7,  # In-Game Shop
}
# Source lines the journal shows that are not BATTLE_PET_SOURCE_* types.
EXTRA_TIER = {
    "Treasure": 3, "Renown": 3, "Reputation": 3, "Ritual Site": 3,
    "PvP": 5,
    "Raid": 6, "Special Event": 6, "Event": 6,
}
UNKNOWN_TIER = 5
TIER_TITLES = {
    1: "Поймать в дикой природе",
    2: "Купить у торговца за золото",
    3: "Задание, особая валюта, сокровище, репутация, Торговая лавка",
    4: "Профессия или открытие",
    5: "Достижение, PvP или источник неизвестен",
    6: "Случайная добыча, рейд или событие",
    7: "Промо, карточная игра, магазин (реальные деньги / ограничено по времени)",
}
WILD, VENDOR = 5, 3


# ---------------------------------------------------------------- SavedVariables parser

TOKEN_RE = re.compile(r'''
    (?P<ws>\s+|--[^\n]*)
  | (?P<str>"(?:[^"\\]|\\.|\\\n)*")
  | (?P<num>-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<sym>[{}\[\]=,;])
''', re.X | re.S)


def lua_unescape(s):
    def repl(m):
        e = m.group(1)
        if e.isdigit():
            return chr(int(e))
        return {"n": "\n", "t": "\t", "r": "\r", "\n": "\n", "\\": "\\", '"': '"', "'": "'"}.get(e, e)
    return re.sub(r'\\(\d{1,3}|.)', repl, s[1:-1], flags=re.S)


def tokenize(text):
    pos = 0
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m:
            raise ValueError(f"bad SavedVariables syntax at {pos}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        val = m.group(kind)
        if kind == "str":
            yield ("val", lua_unescape(val))
        elif kind == "num":
            yield ("val", float(val) if any(c in val for c in ".eE") else int(val))
        elif kind == "name" and val in ("true", "false", "nil"):
            yield ("val", {"true": True, "false": False, "nil": None}[val])
        else:
            yield (kind, val)


def parse_savedvariables(text):
    toks = list(tokenize(text))
    i = 0

    def value():
        nonlocal i
        kind, val = toks[i]
        if kind == "val":
            i += 1
            return val
        if (kind, val) == ("sym", "{"):
            i += 1
            return table()
        raise ValueError(f"unexpected {val!r}")

    def table():
        nonlocal i
        result, n = {}, 1
        while toks[i] != ("sym", "}"):
            if toks[i] == ("sym", "["):
                i += 1
                key = value()
                i += 2  # ] =
                result[key] = value()
            elif toks[i][0] == "name" and toks[i + 1] == ("sym", "="):
                key = toks[i][1]
                i += 2
                result[key] = value()
            else:
                result[n] = value()
                n += 1
            if toks[i] in (("sym", ","), ("sym", ";")):
                i += 1
        i += 1
        return result

    out = {}
    while i < len(toks):
        name = toks[i][1]
        i += 2  # name =
        out[name] = value()
    return out


def as_list(t):
    """Lua array table (dict with 1..n keys) -> Python list."""
    if isinstance(t, dict):
        return [t[k] for k in sorted(k for k in t if isinstance(k, int))]
    return t or []


# ---------------------------------------------------------------- currency / item names

class Names:
    """Currency and item names from Wowhead, cached in .ppc_cache/names.json."""

    def __init__(self, offline):
        self.offline = offline
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                self.cache = json.load(f)
        except (OSError, ValueError):
            self.cache = {}
        self.dirty = False

    def get(self, kind, ident):
        key = f"{kind}={ident}"
        if key not in self.cache and not self.offline:
            name = None
            try:
                req = urllib.request.Request(f"https://www.wowhead.com/{key}", headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    m = re.search(r"<title>(.*?)</title>", resp.read().decode("utf-8", "replace"), re.S)
                    if m:
                        name = m.group(1).split(" - ")[0].strip()
            except Exception:
                pass
            if name:
                self.cache[key] = name
                self.dirty = True
        return self.cache.get(key) or f"{'валюта' if kind == 'currency' else 'предмет'} {ident}"

    def save(self):
        if self.dirty:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=0)


# ---------------------------------------------------------------- source text

ICON_RE = re.compile(r"\|T([^|]*)\|t")
LINK_RE = re.compile(r"\|H(currency|item):(\d+)[^|]*\|h(.*?)\|h", re.S)
MONEY_RE = re.compile(r"(\d[\d ,.]*)\s*\|T[^|]*UI-GoldIcon[^|]*\|t", re.I)


def clean(text, names=None):
    """Source text -> list of plain lines. Links become currency/item names."""
    def link(m):
        kind, ident = m.group(1), m.group(2)
        return " " + (names.get(kind, ident) if names else f"{kind} {ident}")
    text = LINK_RE.sub(link, text)
    text = re.sub(r"\|T[^|]*UI-(Gold|Silver|Copper)Icon[^|]*\|t",
                  lambda m: {"gold": "з", "silver": "с", "copper": "м"}[m.group(1).lower()], text, flags=re.I)
    text = ICON_RE.sub("¤", text)                      # other icons: some currency
    text = re.sub(r"\|c[0-9A-Fa-f]{8}|\|r", "", text)  # colours
    text = text.replace("|n", "\n")
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]


def line_label(line):
    return (line.split(":", 1)[0] if ":" in line else line).strip()


def gold_price(raw):
    m = MONEY_RE.search(raw)
    if not m:
        return None
    try:
        return int(re.sub(r"[ ,.]", "", m.group(1)))
    except ValueError:
        return None


def only_gold(raw):
    icons = ICON_RE.findall(raw)
    return bool(icons) and all("moneyframe" in icon.lower() for icon in icons) and "|H" not in raw


def split_zones(text):
    """'Tazavesh, the Veiled Market, Elwynn Forest' -> keep 'Tazavesh, the Veiled Market' together."""
    zones = []
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        if zones and part[0].islower():
            zones[-1] += ", " + part
        else:
            zones.append(part)
    return zones


def classify(pet, label_index):
    """-> (tier, zones for wild pets)."""
    raw = pet.get("source", "")
    lines = clean(raw)
    types = set(as_list(pet.get("sources")))
    tiers = []
    for ln in lines:
        label = line_label(ln)
        if label in label_index:
            types.add(label_index[label])
        elif label in EXTRA_TIER:
            tiers.append(EXTRA_TIER[label])
    for t in types:
        tier = SOURCE_TIER.get(t, UNKNOWN_TIER)
        if t == VENDOR and not only_gold(raw):
            tier = 3
        tiers.append(tier)

    zones = []
    wild_label = next((k for k, v in label_index.items() if v == WILD), None)
    if WILD in types:
        for ln in lines:
            if wild_label and ln.startswith(wild_label):
                zones += split_zones(ln[len(wild_label):].lstrip(": "))
    elif not tiers and pet.get("wild"):
        # Newer pets: no "Pet Battle:" line, only "Zone: X" — still catchable there.
        for ln in lines:
            if line_label(ln) == "Zone":
                zones += split_zones(ln.split(":", 1)[1])
        if zones:
            tiers.append(1)
    return (min(tiers) if tiers else UNKNOWN_TIER), zones or ["(зона не указана)"]


# ---------------------------------------------------------------- main

def load(wow_dir):
    best = None
    for path in glob.glob(os.path.join(wow_dir, "WTF", "Account", "*", "SavedVariables", "PetCharm.lua")):
        with open(path, encoding="utf-8", errors="replace") as f:
            db = parse_savedvariables(f.read()).get("PetCharmDB") or {}
        if "missingPets" in db and (best is None or db.get("ownedUpdated", 0) > best.get("ownedUpdated", 0)):
            best = db
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wow", default=DEFAULT_WOW, help="WoW _retail_ folder")
    ap.add_argument("--top", type=int, default=15, help="lines per group (default 15)")
    ap.add_argument("--all", action="store_true", help="show everything")
    ap.add_argument("--offline", action="store_true", help="don't look up currency names on Wowhead")
    args = ap.parse_args()
    top = 10 ** 9 if args.all else args.top

    db = load(args.wow)
    if not db:
        print("Не нашёл списка недостающих питомцев от аддона PetCharm.")
        print("Обновите аддон, зайдите в игру и сделайте /reload (или выйдите из игры).")
        return

    labels = db.get("sourceLabels") or {}
    label_index = {v: k for k, v in labels.items() if v}
    pets = [p for p in as_list(db["missingPets"]) if not p.get("name", "").startswith("[DNT]")]
    when = datetime.fromtimestamp(db.get("ownedUpdated", 0)).strftime("%Y-%m-%d %H:%M")
    names = Names(args.offline)

    groups = defaultdict(list)
    for pet in pets:
        tier, zones = classify(pet, label_index)
        groups[tier].append((pet, zones))

    print(f"Недостающих питомцев, которых можно получить: {len(pets)} (данные от {when})\n")
    for tier in sorted(TIER_TITLES):
        print(f"  {tier}. {TIER_TITLES[tier]:<72} {len(groups.get(tier, [])):4}")
    print()

    def mark(pet):
        return " [аукцион]" if pet.get("tradeable") else ""

    def one_line(pet):
        return "; ".join(clean(pet.get("source", ""), names)) or "(источник не указан)"

    def more(n):
        if n > top:
            print(f"  … и ещё {n - top} (--all)")
        print()

    # 1. Wild: group by zone, zones with most pets first.
    if groups.get(1):
        zones = defaultdict(list)
        for pet, pet_zones in groups[1]:
            for z in pet_zones:
                zones[z].append(pet)
        print(f"=== 1. {TIER_TITLES[1]}: {len(groups[1])}, по зонам ===")
        for zone, zpets in sorted(zones.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:top]:
            print(f"  {zone} — {len(zpets)}: " + ", ".join(sorted(p["name"] + mark(p) for p in zpets)))
        more(len(zones))

    # 2. Gold vendors: cheapest first.
    if groups.get(2):
        rows = sorted(groups[2], key=lambda r: (gold_price(r[0].get("source", "")) or 0, r[0]["name"]))
        print(f"=== 2. {TIER_TITLES[2]}: {len(rows)} ===")
        for pet, _ in rows[:top]:
            print(f"  {pet['name']}{mark(pet)} — {one_line(pet)}")
        more(len(rows))

    # 3..7: tradeable first (the Auction House is an easy way out), then by name.
    for tier in range(3, 8):
        rows = groups.get(tier)
        if not rows:
            continue
        rows = sorted(rows, key=lambda r: (not r[0].get("tradeable"), r[0]["name"]))
        print(f"=== {tier}. {TIER_TITLES[tier]}: {len(rows)} ===")
        for pet, _ in rows[:top]:
            print(f"  {pet['name']}{mark(pet)} — {one_line(pet)}")
        more(len(rows))

    names.save()


if __name__ == "__main__":
    main()
