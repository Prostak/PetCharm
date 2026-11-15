#!/usr/bin/env python3
"""Active world quests that reward Polished Pet Charm, grouped by zone.

Reads Wowhead's live world-quest pages (one per expansion), keeps the quests
whose reward is Polished Pet Charm, and prints them by zone with the charm count
per quest and per zone, time left and map coordinates (when Wowhead has a pin).
It also saves the list to PPCQuests.lua next to this script, so the addon's
/charm button can suggest the next quest when your continent has none left.

Run:
  python3 "/Applications/World of Warcraft/_retail_/Interface/AddOns/PetCharm/ppc_world_quests.py"
  python3 ppc_world_quests.py --region eu
"""

import argparse
import json
import os
import re
import time
import urllib.request
from collections import defaultdict

CHARM_ID = 163036
EXPANSIONS = [  # Wowhead slug, label
    ("legion", "Legion"),
    ("bfa", "Battle for Azeroth"),
    ("sl", "Shadowlands"),
    ("df", "Dragonflight"),
    ("tww", "The War Within"),
    ("midnight", "Midnight"),
]
USER_AGENT = "Mozilla/5.0"  # Wowhead returns an empty 202 for unusual user agents

ZONE_RE = re.compile(r'<a href="/zone=(\d+)[^"]*">([^<]+)</a></h2>')
PIN_RE = re.compile(r'\[([\d.]+),([\d.]+),\{"url":"\\/quest=(\d+)\\/')
NAME_RE = re.compile(r'"(\d+)":\{"name_enus":("(?:[^"\\]|\\.)*")')


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
        if resp.status != 200 or not html:
            raise RuntimeError(f"Wowhead вернул пустой ответ ({resp.status})")
        return html


def json_array_after(html, marker):
    """Parse the JSON array that follows `marker` ("data":[ ... ])."""
    i = html.find(marker)
    if i < 0:
        return []
    start = html.find("[", i + len(marker) - 1)
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
                return json.loads(html[start:j + 1])
    return []


_zone_names = {}

def zone_name(zone_id):
    if zone_id not in _zone_names:
        name = f"zone {zone_id}"
        try:
            m = re.search(r"<title>(.*?)</title>", fetch(f"https://www.wowhead.com/zone={zone_id}"), re.S)
            if m:
                name = m.group(1).split(" - ")[0].strip()
        except Exception:
            pass
        _zone_names[zone_id] = name
    return _zone_names[zone_id]


def time_left(ending_ms):
    secs = ending_ms / 1000 - time.time()
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d} д {h} ч"
    if h:
        return f"{h} ч {m} мин"
    return f"{m} мин"


def parse_page(html, expansion):
    for zid, zname in ZONE_RE.findall(html):
        _zone_names.setdefault(int(zid), zname.strip())
    names = {int(q): json.loads(n) for q, n in NAME_RE.findall(html)}
    coords = {int(q): (float(x), float(y)) for x, y, q in PIN_RE.findall(html)}
    now_ms = time.time() * 1000

    for wq in json_array_after(html, '"id":"lv-world-quests","template":"worldquests","data":['):
        rewards = wq.get("rewards") or {}
        items = rewards.get("items", []) if isinstance(rewards, dict) else []
        count = sum(it.get("qty", 1) for it in items if it.get("id") == CHARM_ID)
        if not count or wq.get("ending", 0) <= now_ms:
            continue
        zones = wq.get("zones") or [0]
        yield {
            "id": wq["id"], "name": names.get(wq["id"], f"Quest {wq['id']}"), "count": count,
            "zone_id": zones[0], "ending": wq["ending"], "coords": coords.get(wq["id"]),
            "expansion": expansion,
        }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="na", choices=["na", "eu"], help="realm region (default na)")
    args = ap.parse_args()

    quests = {}
    for slug, label in EXPANSIONS:
        try:
            html = fetch(f"https://www.wowhead.com/world-quests/{slug}/{args.region}")
        except Exception as e:
            print(f"! {label}: не удалось загрузить ({e})")
            continue
        for q in parse_page(html, label):
            quests.setdefault(q["id"], q)
        time.sleep(0.5)

    if not quests:
        print(f"Сейчас нет активных заданий с Polished Pet Charm ({args.region.upper()}).")
        write_addon_data(quests, args.region)
        return

    by_zone = defaultdict(list)
    for q in quests.values():
        by_zone[(q["expansion"], zone_name(q["zone_id"]))].append(q)

    total = sum(q["count"] for q in quests.values())
    print(f"Задания с Polished Pet Charm, {args.region.upper()}: "
          f"{len(quests)} заданий, {total} амулетов\n")

    for (expansion, zone), qs in sorted(by_zone.items(), key=lambda kv: -sum(q["count"] for q in kv[1])):
        print(f"{zone} ({expansion}) — {sum(q['count'] for q in qs)} амулетов")
        for q in sorted(qs, key=lambda q: -q["count"]):
            way = f"/way {q['coords'][0]:.1f} {q['coords'][1]:.1f}" if q["coords"] else "(нет координат)"
            print(f"   {q['count']:3}  {q['name']:<32} {time_left(q['ending']):>12}   {way:<16}"
                  f"   https://www.wowhead.com/quest={q['id']}")
        print()

    write_addon_data(quests, args.region)


def lua_str(s):
    return json.dumps(s, ensure_ascii=False)  # JSON string escapes are valid Lua


LEVEL_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ppc_cache", "quest_levels.json")


def required_levels(quest_ids):
    """Minimum character level per quest, from each quest's Wowhead page (cached forever)."""
    try:
        with open(LEVEL_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    changed = False
    for qid in quest_ids:
        if str(qid) in cache:
            continue
        try:
            html = fetch(f"https://www.wowhead.com/quest={qid}")
            m = re.search(rf'g_quests\[{qid}\], \{{[^}}]*"reqlevel":(\d+)', html)
            if m:
                cache[str(qid)] = int(m.group(1))
                changed = True
            time.sleep(0.3)
        except Exception:
            pass
    if changed:
        os.makedirs(os.path.dirname(LEVEL_CACHE), exist_ok=True)
        with open(LEVEL_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    return {int(k): v for k, v in cache.items()}


def write_addon_data(quests, region):
    """Save the list for the PetCharm addon (read on login or /reload)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PPCQuests.lua")
    levels = required_levels(quests.keys())
    lines = [
        "-- Generated by ppc_world_quests.py. Do not edit by hand.",
        "PetCharm_WQ = {",
        f"    generated = {int(time.time())},",
        f"    region = {lua_str(region)},",
        "    quests = {",
    ]
    for q in sorted(quests.values(), key=lambda q: -q["count"]):
        x, y = q["coords"] or (0, 0)
        lines.append(
            f"        {{ id = {q['id']}, name = {lua_str(q['name'])}, count = {q['count']}, "
            f"zone = {lua_str(zone_name(q['zone_id']))}, expansion = {lua_str(q['expansion'])}, "
            f"ending = {int(q['ending'] // 1000)}, x = {x}, y = {y}, minLevel = {levels.get(q['id'], 0)} }},"
        )
    lines += ["    },", "}", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Список для аддона сохранён: {path}")
    print("Если игра уже запущена, сделайте /reload.")


if __name__ == "__main__":
    main()
