#!/usr/bin/env python3
"""Which missing battle pets are easiest to get?

Reads the pets you don't have from the PetCharm addon's SavedVariables
(WTF/Account/*/SavedVariables/PetCharm.lua, written on logout or /reload) and
sorts them by how easy they are to get, using the source the game's pet journal
shows for each pet (the same data Rematch shows):

  1. Catch in the wild            (Pet Battle source; grouped by zone)
  2. Buy from a vendor for gold
  3. Quest, vendor for a special currency, Trading Post, other
  4. Profession, Discovery
  5. Achievement, unknown source
  6. Random drop, seasonal world event
  7. Promotion, Trading Card Game, In-Game Shop (real money / limited time)

Pets that can be traded are marked [аукцион]: they can also be bought on the
Auction House.

Run:
  python3 "/Applications/World of Warcraft/_retail_/Interface/AddOns/PetCharm/missing_pets.py"
  python3 missing_pets.py --top 30      # more lines per group
  python3 missing_pets.py --all         # everything
"""

import argparse
import glob
import os
import re
from collections import defaultdict
from datetime import datetime

DEFAULT_WOW = "/Applications/World of Warcraft/_retail_"

# BATTLE_PET_SOURCE_<n> index -> tier. Labels shown to you come from the game itself.
SOURCE_TIER = {
    5: 1,   # Pet Battle (wild)
    3: 2,   # Vendor (may be bumped to 3 if the price is not gold)
    2: 3,   # Quest
    4: 4,   # Profession
    11: 4,  # Discovery
    6: 5,   # Achievement
    1: 6,   # Drop
    7: 6,   # World Event
    8: 7,   # Promotion
    9: 7,   # Trading Card Game
    10: 7,  # In-Game Shop
}
UNKNOWN_SOURCE_TIER = 3  # newer source types (e.g. Trading Post)
TIER_TITLES = {
    1: "Поймать в дикой природе",
    2: "Купить у торговца за золото",
    3: "Задание, особая валюта, Торговая лавка и прочее",
    4: "Профессия или открытие",
    5: "Достижение или источник неизвестен",
    6: "Случайная добыча или сезонное событие",
    7: "Промо, карточная игра, магазин (реальные деньги или ограничено по времени)",
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


# ---------------------------------------------------------------- source text

MONEY_RE = re.compile(r"(\d[\d ,.]*)\s*\|TInterface\\MoneyFrame\\UI-GoldIcon[^|]*\|t", re.I)


def clean(text):
    text = re.sub(r"\|T[^|]*UI-(Gold|Silver|Copper)Icon[^|]*\|t",
                  lambda m: {"gold": "з", "silver": "с", "copper": "м"}[m.group(1).lower()], text, flags=re.I)
    text = re.sub(r"\|T[^|]*\|t", "¤", text)          # other icons = some currency
    text = re.sub(r"\|c[0-9A-Fa-f]{8}|\|r", "", text)  # colours
    text = text.replace("|n", "\n")
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def gold_price(raw):
    m = MONEY_RE.search(raw)
    if not m:
        return None
    try:
        return int(re.sub(r"[ ,.]", "", m.group(1)))
    except ValueError:
        return None


def has_other_currency(raw):
    icons = re.findall(r"\|T([^|]*)\|t", raw)
    return any("MoneyFrame" not in icon for icon in icons)


def wild_zones(lines, label):
    zones = []
    for ln in lines:
        if label and ln.startswith(label + ":"):
            zones += [z.strip() for z in ln[len(label) + 1:].split(",") if z.strip()]
    return zones or ["(зона не указана)"]


# ---------------------------------------------------------------- main

def load(wow_dir):
    best = None
    for path in glob.glob(os.path.join(wow_dir, "WTF", "Account", "*", "SavedVariables", "PetCharm.lua")):
        with open(path, encoding="utf-8", errors="replace") as f:
            db = parse_savedvariables(f.read()).get("PetCharmDB") or {}
        if "missingPets" in db and (best is None or db.get("ownedUpdated", 0) > best.get("ownedUpdated", 0)):
            best = db
    return best


def classify(pet, labels):
    sources = as_list(pet.get("sources"))
    raw = pet.get("source", "")
    tiers = []
    for s in sources:
        tier = SOURCE_TIER.get(s, UNKNOWN_SOURCE_TIER)
        if s == VENDOR and (gold_price(raw) is None or has_other_currency(raw)):
            tier = 3
        tiers.append((tier, s))
    if pet.get("wild"):
        tiers.append((1, WILD))
    if not tiers:
        tiers.append((5, None))
    return min(tiers)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wow", default=DEFAULT_WOW, help="WoW _retail_ folder")
    ap.add_argument("--top", type=int, default=15, help="lines per group (default 15)")
    ap.add_argument("--all", action="store_true", help="show everything")
    args = ap.parse_args()
    top = 10 ** 9 if args.all else args.top

    db = load(args.wow)
    if not db:
        print("Не нашёл списка недостающих питомцев от аддона PetCharm.")
        print("Обновите аддон, зайдите в игру и сделайте /reload (или выйдите из игры).")
        return

    labels = {k: v for k, v in (db.get("sourceLabels") or {}).items() if v}
    pets = as_list(db["missingPets"])
    when = datetime.fromtimestamp(db.get("ownedUpdated", 0)).strftime("%Y-%m-%d %H:%M")

    groups = defaultdict(list)
    for pet in pets:
        tier, src = classify(pet, labels)
        groups[tier].append((pet, src))

    print(f"Недостающих питомцев, которых можно получить: {len(pets)} (данные от {when})\n")
    for tier in sorted(TIER_TITLES):
        print(f"  {tier}. {TIER_TITLES[tier]:<75} {len(groups.get(tier, [])):4}")
    print()

    def mark(pet):
        return " [аукцион]" if pet.get("tradeable") else ""

    def one_line(pet):
        return "; ".join(clean(pet.get("source", "")))

    # 1. Wild: group by zone, zones with most pets first.
    if groups.get(1):
        zones = defaultdict(list)
        for pet, _ in groups[1]:
            for z in wild_zones(clean(pet.get("source", "")), labels.get(WILD)):
                zones[z].append(pet)
        print(f"=== 1. {TIER_TITLES[1]}: {len(groups[1])} питомцев, по зонам ===")
        for zone, zpets in sorted(zones.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:top]:
            names = ", ".join(sorted(p["name"] + mark(p) for p in zpets))
            print(f"  {zone} — {len(zpets)}: {names}")
        if len(zones) > top:
            print(f"  … и ещё {len(zones) - top} зон (--all)")
        print()

    # 2. Gold vendors: cheapest first.
    if groups.get(2):
        print(f"=== 2. {TIER_TITLES[2]}: {len(groups[2])} ===")
        rows = sorted(groups[2], key=lambda ps: gold_price(ps[0].get("source", "")) or 0)
        for pet, _ in rows[:top]:
            print(f"  {pet['name']}{mark(pet)} — {one_line(pet)}")
        if len(rows) > top:
            print(f"  … и ещё {len(rows) - top} (--all)")
        print()

    # 3..7: tradeable first (an easy way out), then by name.
    for tier in range(3, 8):
        rows = groups.get(tier)
        if not rows:
            continue
        print(f"=== {tier}. {TIER_TITLES[tier]}: {len(rows)} ===")
        rows = sorted(rows, key=lambda ps: (not ps[0].get("tradeable"), ps[0]["name"]))
        for pet, _ in rows[:top]:
            print(f"  {pet['name']}{mark(pet)} — {one_line(pet)}")
        if len(rows) > top:
            print(f"  … и ещё {len(rows) - top} (--all)")
        print()


if __name__ == "__main__":
    main()
