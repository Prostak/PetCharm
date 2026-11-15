# PetCharm

A small World of Warcraft (retail) addon plus two Python scripts for farming and
spending **Polished Pet Charms**.

*Русская версия — ниже.*

## Addon

Install: copy the `PetCharm` folder to `World of Warcraft/_retail_/Interface/AddOns/`.

- **`/charm` and a minimap button** (Polished Pet Charm icon): finds the nearest
  active world quest on your current continent that rewards Polished Pet Charms and
  super-tracks it. If the continent has none left, it suggests the next quest from
  the daily list made by `ppc_world_quests.py`: same expansion first, then the
  bigger reward. Completed and expired quests are skipped. Drag the button to move
  it around the minimap.
- **Bag highlight**: Polished Pet Charms pulse in the default bags. Bag
  replacement addons (Bagnon, Baganator, …) are not supported.
- **Escape menu**: the *Log Out* button is greyed out. The idea is to log out with
  a macro that revives your battle pets first:
  ```
  #showtooltip Revive Battle Pets
  /cast Revive Battle Pets
  /logout
  ```
- **Collection export**: saves the species IDs of the pets you own to
  SavedVariables (on logout or `/reload`) for `ppc_best_pet.py`.

Chat messages are in Russian.

## Scripts

Python 3, standard library only. Data comes from Wowhead.

- **`ppc_world_quests.py [--region na|eu]`** — active world quests that reward
  Polished Pet Charms, grouped by zone, with the charm count per quest and per zone,
  time left and coordinates. Also writes `PPCQuests.lua` for the addon. Run it once
  a day, then `/reload` in game.
- **`ppc_best_pet.py [--top N] [--lang en|ru]`** — the most expensive pets sold for
  Polished Pet Charms that are not in your collection yet, and where to buy them.
  Wowhead pages are cached in `.ppc_cache` for a week.

The default game path is the macOS one (`/Applications/World of Warcraft/_retail_`);
use `--wow PATH` with `ppc_best_pet.py` on other systems.

## License

[CC0 1.0](LICENSE) — public domain. Do whatever you like with it.

---

# PetCharm (по-русски)

Аддон для World of Warcraft (retail) и два скрипта на Python для **Polished Pet Charm**.

## Аддон

Установка: скопируйте папку `PetCharm` в `World of Warcraft/_retail_/Interface/AddOns/`.

- **`/charm` и кнопка у миникарты** ищут ближайшее локальное задание с Polished Pet
  Charm на текущем континенте и делают его отслеживаемым. Если на континенте таких
  заданий нет, аддон берёт следующее из ежедневного списка `ppc_world_quests.py`:
  сначала то же дополнение, потом бо́льшая награда. Выполненные и истёкшие задания
  пропускаются. Кнопку можно перетаскивать по краю миникарты.
- **Подсветка в сумках**: Polished Pet Charm пульсирует в стандартных сумках.
- **Меню Escape**: кнопка «Выход» неактивна — выходите макросом, который сначала
  воскрешает питомцев (см. выше).
- **Экспорт коллекции** для `ppc_best_pet.py` при выходе из игры или `/reload`.

## Скрипты

Python 3, только стандартная библиотека. Данные берутся с Wowhead.

- `ppc_world_quests.py [--region na|eu]` — активные задания с амулетами по зонам;
  заодно пишет `PPCQuests.lua` для аддона. Запускать раз в день, потом `/reload`.
- `ppc_best_pet.py [--top N] [--lang en|ru]` — самые дорогие питомцы за амулеты,
  которых ещё нет в коллекции, и где их купить.

## Лицензия

[CC0 1.0](LICENSE) — общественное достояние, используйте как угодно.
