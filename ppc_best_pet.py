#!/usr/bin/env python3
"""Find the most expensive battle pets sold for Polished Pet Charm that you don't own yet.

Data:
  * Pets, prices and vendors come from Wowhead (pages are cached in .ppc_cache).
  * Your collection comes from the NoLogoutButton addon, which saves owned pet
    species to WTF/Account/*/SavedVariables/NoLogoutButton.lua on logout or /reload.

The script lives in the addon folder, so run it as:
  python3 "/Applications/World of Warcraft/_retail_/Interface/AddOns/NoLogoutButton/ppc_best_pet.py"

Usage:
  python3 ppc_best_pet.py                # top 10, English names
  python3 ppc_best_pet.py --top 20 --lang ru
  python3 ppc_best_pet.py --refresh      # re-download Wowhead data
"""

import argparse
import glob
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

CHARM_ID = 163036
DEFAULT_WOW = "/Applications/World of Warcraft/_retail_"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ppc_cache")
CACHE_MAX_AGE = 7 * 24 * 3600  # re-download pages older than a week
USER_AGENT = "Mozilla/5.0"  # Wowhead returns an empty 202 for unusual user agents


# ---------------------------------------------------------------- download

def fetch(path, lang, refresh):
    """Fetch a Wowhead page like 'item=163036', cached on disk."""
    prefix = "" if lang == "en" else f"/{lang}"
    url = f"https://www.wowhead.com{prefix}/{path}"
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{lang}_{path.replace('=', '_')}.html")
    if not refresh and os.path.exists(cache) and time.time() - os.path.getmtime(cache) < CACHE_MAX_AGE:
        with open(cache, encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    if resp.status != 200 or not html:
        raise RuntimeError(f"Wowhead вернул пустой ответ ({resp.status}) для {url}")
    with open(cache, "w", encoding="utf-8") as f:
        f.write(html)
    time.sleep(0.7)  # be polite to Wowhead
    return html


def listview_data(html, lv_id):
    """Return the 'data: [...]' array of a Wowhead Listview with the given id."""
    i = html.find(f"id: '{lv_id}'")
    if i < 0:
        return []
    start = html.find("data: [", i)
    if start < 0:
        return []
    start += len("data: ")
    depth, in_str, esc = 0, False, False
    for j in range(start, len(html)):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:j + 1])
                except json.JSONDecodeError:
                    return []
    return []


def charm_costs(cost_list):
    """Extract Polished Pet Charm amounts from a Wowhead 'cost' field."""
    out = []
    for entry in cost_list or []:
        if len(entry) >= 3:
            for item_id, amount in entry[2]:
                if item_id == CHARM_ID:
                    out.append(amount)
    return out


_zone_cache = {}

def zone_name(zone_id, lang, refresh):
    if zone_id in _zone_cache:
        return _zone_cache[zone_id]
    name = f"zone {zone_id}"
    try:
        html = fetch(f"zone={zone_id}", lang, refresh)
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        if m:
            name = m.group(1).split(" - ")[0].strip()
    except Exception:
        pass
    _zone_cache[zone_id] = name
    return name


# ---------------------------------------------------------------- collection

def load_owned(wow_dir):
    """Owned species IDs from the newest NoLogoutButton SavedVariables file."""
    files = glob.glob(os.path.join(wow_dir, "WTF", "Account", "*", "SavedVariables", "NoLogoutButton.lua"))
    best = None
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        m = re.search(r'\["ownedSpecies"\]\s*=\s*"([\d,]*)"', text)
        if not m:
            continue
        t = re.search(r'\["ownedUpdated"\]\s*=\s*(\d+)', text)
        updated = int(t.group(1)) if t else 0
        if best is None or updated > best[0]:
            species = {int(x) for x in m.group(1).split(",") if x}
            best = (updated, species, path)
    return best


# ---------------------------------------------------------------- main

def faction(react):
    if not react or len(react) < 2:
        return ""
    a, h = react[0] == 1, react[1] == 1
    if a and not h:
        return " [Альянс]"
    if h and not a:
        return " [Орда]"
    return ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wow", default=DEFAULT_WOW, help="WoW _retail_ folder")
    ap.add_argument("--lang", default="en", help="Wowhead language: en, ru, de, ... (default en)")
    ap.add_argument("--top", type=int, default=10, help="how many pets to show")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache and re-download")
    args = ap.parse_args()

    owned_info = load_owned(args.wow)
    if owned_info:
        updated, owned, path = owned_info
        when = datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M") if updated else "?"
        print(f"Коллекция: {len(owned)} видов питомцев (данные от {when}).")
    else:
        owned = None
        print("! Не нашёл данных коллекции от аддона NoLogoutButton.")
        print("  Зайдите в игру, подождите 10 секунд и сделайте /reload или выйдите из игры.")
        print("  Пока показываю всех питомцев, без проверки, есть ли они у вас.\n")

    print("Загружаю список питомцев за Polished Pet Charm с Wowhead…")
    items = listview_data(fetch(f"item={CHARM_ID}", args.lang, args.refresh), "currency-for")
    pet_items = [x for x in items if x.get("classs") == 15 and x.get("subclass") == 2]
    if not pet_items:
        sys.exit("Не удалось разобрать страницу Wowhead — возможно, изменилась её структура.")

    results = []
    for n, item in enumerate(pet_items, 1):
        print(f"\r  страница питомца {n}/{len(pet_items)}", end="", flush=True)
        costs = charm_costs(item.get("cost"))
        if not costs:
            continue
        html = fetch(f"item={item['id']}", args.lang, args.refresh)
        species = [p.get("species") for p in listview_data(html, "battle-pet") if p.get("species")]
        species_id = species[0] if species else None
        if owned is not None and species_id in owned:
            continue
        vendors = []
        for npc in listview_data(html, "sold-by"):
            npc_costs = charm_costs(npc.get("cost"))
            if npc_costs:
                vendors.append((npc, min(npc_costs)))
        results.append({
            "item": item,
            "species": species_id,
            "price": max(costs),
            "vendors": vendors,
        })
    print()

    if not results:
        print("Поздравляю: у вас есть все питомцы, которых продают за Polished Pet Charm!")
        return

    results.sort(key=lambda r: r["price"], reverse=True)
    word = "нет в коллекции" if owned is not None else "всего"
    print(f"\nПитомцев за Polished Pet Charm, которых {word}: {len(results)}. Самые дорогие:\n")

    for rank, r in enumerate(results[: args.top], 1):
        item = r["item"]
        unknown = "" if r["species"] or owned is None else "  (вид не определён — проверьте вручную)"
        print(f"{rank:2}. {item['name']} — {r['price']} амулетов{unknown}")
        print(f"    https://www.wowhead.com/item={item['id']}")
        if r["vendors"]:
            for npc, price in r["vendors"]:
                zones = ", ".join(zone_name(z, args.lang, args.refresh) for z in npc.get("location", [])) or "?"
                print(f"    Продавец: {npc['name']} — {zones}{faction(npc.get('react'))}, {price} амулетов")
                print(f"              https://www.wowhead.com/npc={npc['id']}")
        else:
            for src in item.get("sourcemore", []):
                if src.get("n"):
                    print(f"    Продавец: {src['n']} — {zone_name(src.get('z'), args.lang, args.refresh)}")
            if not item.get("sourcemore"):
                print("    Продавец: не указан на Wowhead — откройте ссылку выше.")
        print()


if __name__ == "__main__":
    main()
