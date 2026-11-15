-- PetCharm: greys out the "Log Out" button in the Escape (Game) menu,
-- so logging out goes through the macro that revives battle pets first.
--
-- Only the button's look and enabled state are changed; its click handler is
-- left alone, which keeps the risk of "Interface action blocked" errors low.

local HINT = "Выход — через макрос!"   -- text shown on the disabled button

-- Texts to look for. LOG_OUT is the game's own localized string
-- ("Выход" on a Russian client, "Log Out" on English).
-- To also block "Exit Game", add QUIT to this list.
local TARGETS = {}
for _, s in ipairs({ LOG_OUT, "Log Out", "Выход" }) do
    if s then TARGETS[s] = true end
end

local function Block(button)
    if not button or not button.GetText then return end
    local text = button:GetText()
    if text ~= HINT and not TARGETS[text] then return end
    button:SetText(HINT)
    button:SetEnabled(false)
    if button.SetMotionScriptsWhileDisabled then
        button:SetMotionScriptsWhileDisabled(true)
    end
end

if GameMenuFrame and GameMenuFrame.InitButtons and GameMenuFrame.buttonPool then
    -- Retail 11.0+: the menu rebuilds its buttons from a pool every time it opens.
    hooksecurefunc(GameMenuFrame, "InitButtons", function(self)
        for button in self.buttonPool:EnumerateActive() do
            Block(button)
        end
    end)
elseif GameMenuButtonLogout then
    -- Older clients: one fixed, named button.
    GameMenuFrame:HookScript("OnShow", function()
        Block(GameMenuButtonLogout)
    end)
end

---------------------------------------------------------------------------
-- /charm: super-track the nearest world quest on the current continent
-- that rewards Polished Pet Charm. Macro: just "/charm".
---------------------------------------------------------------------------

local CHARM_ID = 163036  -- Polished Pet Charm
local PREFIX = "|cff66ccffCharm:|r "
local function Say(msg) print(PREFIX .. msg) end

local GetQuestsOnMap = C_TaskQuest.GetQuestsOnMap or C_TaskQuest.GetQuestsForPlayerByMapID

local function CharmName()
    local name = C_Item.GetItemNameByID and C_Item.GetItemNameByID(CHARM_ID)
    if not name and C_Item.RequestLoadItemDataByID then
        C_Item.RequestLoadItemDataByID(CHARM_ID)
    end
    return name
end

-- Walk up the map tree from the player's map to the continent.
local function ContinentOf(mapID)
    local info = C_Map.GetMapInfo(mapID)
    while info and info.mapType > Enum.UIMapType.Continent
          and info.parentMapID and info.parentMapID > 0 do
        info = C_Map.GetMapInfo(info.parentMapID)
    end
    if info and info.mapType == Enum.UIMapType.Continent then
        return info.mapID
    end
    return mapID
end

-- true / false, or nil when reward data is not loaded yet.
local function GivesCharm(questID, charmName)
    if not HaveQuestRewardData(questID) then
        C_TaskQuest.RequestPreloadRewardData(questID)
        return nil
    end
    for i = 1, GetNumQuestLogRewards(questID) do
        local name, _, _, _, _, itemID = GetQuestLogRewardInfo(i, questID)
        if itemID == CHARM_ID or (charmName and name == charmName) then
            return true
        end
    end
    if C_QuestLog.GetQuestRewardCurrencies then
        for _, c in ipairs(C_QuestLog.GetQuestRewardCurrencies(questID) or {}) do
            if charmName and c.name == charmName then return true end
        end
    end
    return false
end

local function WorldPos(mapID, x, y)
    if not (mapID and x and y) then return end
    return C_Map.GetWorldPosFromMapPos(mapID, CreateVector2D(x, y))
end

---------------------------------------------------------------------------
-- Fallback: when the current continent has no charm quests left, pick the
-- next one from PPCQuests.lua (written by ppc_world_quests.py).
-- Priority: same expansion as where you are, then bigger reward, then the
-- one that expires sooner. Completed and expired quests are skipped.
---------------------------------------------------------------------------

-- Continent/zone map IDs → expansion label used in PPCQuests.lua.
local MAP_EXPANSION = {
    [619] = "Legion", [905] = "Legion",
    [875] = "Battle for Azeroth", [876] = "Battle for Azeroth", [1355] = "Battle for Azeroth",
    [1550] = "Shadowlands", [1543] = "Shadowlands", [1961] = "Shadowlands", [1970] = "Shadowlands",
    [1978] = "Dragonflight", [2133] = "Dragonflight", [2151] = "Dragonflight", [2200] = "Dragonflight",
    [2274] = "The War Within", [2346] = "The War Within", [2371] = "The War Within",
}

local function CurrentExpansion(playerMap)
    -- 1) Known map IDs, walking up from the player's map.
    local mapID = playerMap
    while mapID and mapID > 0 do
        if MAP_EXPANSION[mapID] then return MAP_EXPANSION[mapID] end
        local info = C_Map.GetMapInfo(mapID)
        mapID = info and info.parentMapID
    end
    -- 2) A quest from the list that lies on the same continent.
    local continent = ContinentOf(playerMap)
    for _, q in ipairs(PetCharm_WQ and PetCharm_WQ.quests or {}) do
        local zone = C_TaskQuest.GetQuestZoneID(q.id)
        if zone and ContinentOf(zone) == continent then return q.expansion end
    end
end

local function FormatLeft(secs)
    local h = math.floor(secs / 3600)
    if h >= 24 then return ("%d д %d ч"):format(math.floor(h / 24), h % 24) end
    return ("%d ч %d мин"):format(h, math.floor(secs % 3600 / 60))
end

local function SuggestFromList(playerMap)
    local data = PetCharm_WQ
    if not data or not data.quests then
        Say("на континенте заданий нет, а списка от ppc_world_quests.py нет — запустите скрипт и сделайте /reload.")
        return
    end
    local now = GetServerTime()
    local exp = CurrentExpansion(playerMap)
    local level = UnitLevel("player")
    local candidates, tooLow, lowest = {}, 0, nil
    for _, q in ipairs(data.quests) do
        if q.ending > now and not C_QuestLog.IsQuestFlaggedCompleted(q.id) then
            -- Only the level is checked; quests that need an intro chain are kept.
            if (q.minLevel or 0) > level then
                tooLow = tooLow + 1
                lowest = math.min(lowest or q.minLevel, q.minLevel)
            else
                candidates[#candidates + 1] = q
            end
        end
    end
    if #candidates == 0 then
        if tooLow > 0 then
            Say(("на континенте заданий нет, а остальным %d заданиям нужен уровень %d+ (у вас %d).")
                :format(tooLow, lowest, level))
        else
            Say("на континенте заданий нет, и все задания из списка выполнены или истекли.")
        end
        return
    end
    table.sort(candidates, function(a, b)
        local sa, sb = a.expansion == exp, b.expansion == exp
        if sa ~= sb then return sa end
        if a.count ~= b.count then return a.count > b.count end
        return a.ending < b.ending
    end)

    local q = candidates[1]
    if C_QuestLog.AddWorldQuestWatch then C_QuestLog.AddWorldQuestWatch(q.id) end
    C_SuperTrack.SetSuperTrackedQuestID(q.id)  -- just select the quest; no map pin

    Say(("на этом континенте заданий нет. Следующее: |cffffff00%s|r — %s (%s), %d амулетов, осталось %s.")
        :format(q.name, q.zone, q.expansion, q.count, FormatLeft(q.ending - now)))
    if q.x > 0 then Say(("Координаты: %.1f %.1f"):format(q.x, q.y)) end
    if #candidates > 1 then
        Say(("Ещё в списке: %d заданий, %d амулетов."):format(#candidates - 1,
            (function() local s = 0 for i = 2, #candidates do s = s + candidates[i].count end return s end)()))
    end
    if tooLow > 0 then
        Say(("Пропущено по уровню: %d (нужен %d+)."):format(tooLow, lowest))
    end
    if now - (data.generated or 0) > 20 * 3600 then
        Say("|cffff8800Список устарел (старше 20 ч) — перезапустите ppc_world_quests.py.|r")
    end
end

local function FindCharm(isRetry)
    local playerMap = C_Map.GetBestMapForUnit("player")
    local playerXY = playerMap and C_Map.GetPlayerMapPosition(playerMap, "player")
    if not playerXY then
        Say("не могу определить ваше положение (подземелье?).")
        return
    end
    local pCont, pPos = C_Map.GetWorldPosFromMapPos(playerMap, playerXY)
    local px, py = pPos:GetXY()

    -- Collect world quests from the continent and all its zones.
    local continent = ContinentOf(playerMap)
    local maps = { continent }
    for _, child in ipairs(C_Map.GetMapChildrenInfo(continent, Enum.UIMapType.Zone, true) or {}) do
        maps[#maps + 1] = child.mapID
    end

    local charmName = CharmName()
    local seen, pending = {}, 0
    local bestID, bestDist

    for _, mapID in ipairs(maps) do
        for _, q in ipairs(GetQuestsOnMap(mapID) or {}) do
            local qid = q.questID or q.questId
            if qid and not seen[qid] and C_QuestLog.IsWorldQuest(qid) then
                seen[qid] = true
                local gives = GivesCharm(qid, charmName)
                if gives == nil then
                    pending = pending + 1
                elseif gives then
                    local zone = C_TaskQuest.GetQuestZoneID(qid) or q.mapID or mapID
                    local x, y = C_TaskQuest.GetQuestLocation(qid, zone)
                    if not x then zone, x, y = q.mapID or mapID, q.x, q.y end
                    local cont, pos = WorldPos(zone, x, y)
                    if pos and cont == pCont then
                        local qx, qy = pos:GetXY()
                        local d = math.sqrt((qx - px) ^ 2 + (qy - py) ^ 2)
                        if not bestDist or d < bestDist then
                            bestID, bestDist = qid, d
                        end
                    end
                end
            end
        end
    end

    if bestID then
        C_SuperTrack.SetSuperTrackedQuestID(bestID)
        if C_QuestLog.AddWorldQuestWatch then C_QuestLog.AddWorldQuestWatch(bestID) end
        local title = C_TaskQuest.GetQuestInfoByQuestID(bestID) or ("#" .. bestID)
        Say(("|cffffff00%s|r — %d ярдов. Отслеживается."):format(title, bestDist))
        if pending > 0 then
            Say(("(%d заданий ещё без данных о наградах — ближе может найтись при повторе.)"):format(pending))
        end
    elseif pending > 0 and not isRetry then
        Say("загружаю награды заданий…")
        C_Timer.After(2, function() FindCharm(true) end)
    else
        if pending > 0 then
            Say(("(у %d заданий на континенте награды не загрузились — можно нажать ещё раз.)"):format(pending))
        end
        SuggestFromList(playerMap)
    end
end

SLASH_PETCHARM1 = "/charm"
SlashCmdList.PETCHARM = function() FindCharm(false) end

---------------------------------------------------------------------------
-- Minimap button: Polished Pet Charm icon on the minimap edge.
-- Left click = /charm, drag = move it around the minimap.
-- Its position is saved in PetCharmDB.angle (degrees).
---------------------------------------------------------------------------

local function CreateMinimapButton()
    PetCharmDB = PetCharmDB or {}
    local db = PetCharmDB

    local btn = CreateFrame("Button", "PetCharmMinimapButton", Minimap)
    btn:SetSize(31, 31)
    btn:SetFrameStrata("MEDIUM")
    btn:SetFrameLevel(8)
    btn:RegisterForClicks("LeftButtonUp")
    btn:RegisterForDrag("LeftButton")
    btn:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")

    local bg = btn:CreateTexture(nil, "BACKGROUND")
    bg:SetSize(20, 20)
    bg:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
    bg:SetPoint("TOPLEFT", 7, -5)

    local icon = btn:CreateTexture(nil, "ARTWORK")
    icon:SetSize(17, 17)
    icon:SetPoint("TOPLEFT", 7, -6)
    icon:SetTexture(C_Item.GetItemIconByID(CHARM_ID) or 134400)
    icon:SetTexCoord(0.05, 0.95, 0.05, 0.95)

    local border = btn:CreateTexture(nil, "OVERLAY")
    border:SetSize(53, 53)
    border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
    border:SetPoint("TOPLEFT")

    local function UpdatePosition()
        local a = math.rad(db.angle or 225)
        local r = Minimap:GetWidth() / 2 + 10
        btn:ClearAllPoints()
        btn:SetPoint("CENTER", Minimap, "CENTER", math.cos(a) * r, math.sin(a) * r)
    end

    btn:SetScript("OnDragStart", function(self)
        self:SetScript("OnUpdate", function()
            local mx, my = Minimap:GetCenter()
            local cx, cy = GetCursorPosition()
            local scale = Minimap:GetEffectiveScale()
            db.angle = math.deg(math.atan2(cy / scale - my, cx / scale - mx))
            UpdatePosition()
        end)
    end)
    btn:SetScript("OnDragStop", function(self)
        self:SetScript("OnUpdate", nil)
    end)

    btn:SetScript("OnClick", function() FindCharm(false) end)

    btn:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_LEFT")
        GameTooltip:SetText(CharmName() or "Polished Pet Charm")
        GameTooltip:AddLine("Клик: ближайшее задание с амулетом", 1, 1, 1)
        GameTooltip:AddLine("Перетащить: переместить кнопку", 0.7, 0.7, 0.7)
        GameTooltip:Show()
    end)
    btn:SetScript("OnLeave", function() GameTooltip:Hide() end)

    UpdatePosition()
end

---------------------------------------------------------------------------
-- Bag highlight: pulsing glow on Polished Pet Charm in the default bags
-- (separate bags and the combined backpack). Bag-replacement addons such
-- as Bagnon or ArkInventory use their own frames and are not covered.
---------------------------------------------------------------------------

local function GetGlow(button)
    if button.petCharmGlow then return button.petCharmGlow end
    local g = button:CreateTexture(nil, "OVERLAY", nil, 7)
    g:SetTexture("Interface\\Buttons\\UI-ActionButton-Border")
    g:SetBlendMode("ADD")
    g:SetVertexColor(0.3, 0.9, 1)
    g:SetPoint("CENTER")
    g:SetSize(button:GetWidth() * 1.9, button:GetHeight() * 1.9)
    local ag = g:CreateAnimationGroup()
    ag:SetLooping("BOUNCE")
    local a = ag:CreateAnimation("Alpha")
    a:SetFromAlpha(1)
    a:SetToAlpha(0.3)
    a:SetDuration(0.8)
    g.anim = ag
    g:Hide()
    button.petCharmGlow = g
    return g
end

local function MarkButton(button)
    if not (button.GetBagID and button.GetID) then return end
    local itemID = C_Container.GetContainerItemID(button:GetBagID(), button:GetID())
    if itemID == CHARM_ID then
        local g = GetGlow(button)
        g:Show()
        if not g.anim:IsPlaying() then g.anim:Play() end
    elseif button.petCharmGlow then
        button.petCharmGlow.anim:Stop()
        button.petCharmGlow:Hide()
    end
end

local function BagFrames()
    local frames = { ContainerFrameCombinedBags }
    for i = 1, 13 do frames[#frames + 1] = _G["ContainerFrame" .. i] end
    return frames
end

local function RefreshBags()
    for _, frame in ipairs(BagFrames()) do
        if frame and frame:IsShown() and frame.EnumerateValidItems then
            for _, button in frame:EnumerateValidItems() do
                MarkButton(button)
            end
        end
    end
end

local function RefreshSoon() C_Timer.After(0, RefreshBags) end

local function SetupBagHighlight()
    for _, frame in ipairs(BagFrames()) do
        if frame then
            frame:HookScript("OnShow", RefreshSoon)
            if frame.UpdateItems then hooksecurefunc(frame, "UpdateItems", RefreshSoon) end
        end
    end
end

---------------------------------------------------------------------------
-- Export the pet collection to SavedVariables for the out-of-game scripts:
--   ownedSpecies  – species you have (ppc_best_pet.py)
--   missingPets   – obtainable species you don't have, with the journal's
--                   source text and source types (missing_pets.py)
-- The file is written by the game on logout or /reload.
---------------------------------------------------------------------------

local MAX_SPECIES = 6000
local MAX_SOURCE = 20  -- BATTLE_PET_SOURCE_1 .. _N globals (Drop, Quest, Vendor, ...)

-- Source type indexes whose localized label ("Vendor:", "Торговец:") appears in the text.
local function SourceTypes(text)
    local found = {}
    for i = 1, MAX_SOURCE do
        local label = _G["BATTLE_PET_SOURCE_" .. i]
        if label and text:find(label .. ":", 1, true) then found[#found + 1] = i end
    end
    return found
end

local function ExportOwnedPets()
    PetCharmDB = PetCharmDB or {}
    local owned, missing = {}, {}
    for speciesID = 1, MAX_SPECIES do
        local count = C_PetJournal.GetNumCollectedInfo(speciesID)
        if count and count > 0 then
            owned[#owned + 1] = speciesID
        elseif count then
            local name, _, petType, _, source, _, isWild, canBattle, tradeable, _, obtainable =
                C_PetJournal.GetPetInfoBySpeciesID(speciesID)
            if name and obtainable then
                missing[#missing + 1] = {
                    id = speciesID, name = name, type = petType, source = source or "",
                    sources = SourceTypes(source or ""), wild = isWild, battle = canBattle,
                    tradeable = tradeable,
                }
            end
        end
    end
    if #owned > 0 then  -- skip if the journal was not ready yet
        local labels = {}
        for i = 1, MAX_SOURCE do labels[i] = _G["BATTLE_PET_SOURCE_" .. i] or false end
        PetCharmDB.ownedSpecies = table.concat(owned, ",")
        PetCharmDB.missingPets = missing
        PetCharmDB.sourceLabels = labels
        PetCharmDB.ownedUpdated = time()
    end
end

local loader = CreateFrame("Frame")
loader:RegisterEvent("PLAYER_LOGIN")
loader:RegisterEvent("PLAYER_LOGOUT")
loader:RegisterEvent("BAG_UPDATE_DELAYED")
loader:SetScript("OnEvent", function(_, event)
    if event == "PLAYER_LOGIN" then
        CreateMinimapButton()
        SetupBagHighlight()
        C_Timer.After(10, ExportOwnedPets)
    elseif event == "PLAYER_LOGOUT" then
        ExportOwnedPets()
    else
        RefreshSoon()
    end
end)
