#pragma once

#include <algorithm>
#include <cmath>
#include "blender_ui_types.hpp"
#include "nvda_speech.hpp"

// Extract native button label, value, and tooltip directly from Blender's Button & RNA APIs.
inline void QueryNativeButtonInfo(
    const void* C,
    void* but,
    const std::string& rawDrawnText,
    bool fetchTooltip,
    bool isPopupContext,
    std::string& outSpokenText,
    std::string& outTooltipText)
{
    const auto* butBytes = reinterpret_cast<const uint8_t*>(but);
    const int butFlag = *reinterpret_cast<const int*>(butBytes + 0x10);
    const uint8_t butType = *reinterpret_cast<const uint8_t*>(butBytes + 0x1A);

    // Read Button::str (+0x40) and Button::drawstr (+0x60) in-place without allocation.
    const auto* msvcStr = reinterpret_cast<const MsvcString*>(butBytes + 0x40);
    const auto* msvcDrawStr = reinterpret_cast<const MsvcString*>(butBytes + 0x60);

    std::string butStr = msvcStr->ToStdString();
    if (!butStr.empty()) {
        size_t sepPos = butStr.find('|');
        if (sepPos != std::string::npos) {
            butStr = butStr.substr(0, sepPos);
        }
    }

    std::string drawStr = !rawDrawnText.empty() ? rawDrawnText : msvcDrawStr->ToStdString();
    if (drawStr.empty() && g_fn_button_string_get != nullptr) {
        const void* rnaPropCheck = *reinterpret_cast<const void* const*>(butBytes + 0x260);
        if (butType == BUT_TYPE_NUM || butType == BUT_TYPE_NUMSLIDER ||
            (rnaPropCheck != nullptr &&
             (butType == BUT_TYPE_TEXT || butType == BUT_TYPE_TEXTBOX ||
              butType == BUT_TYPE_SEARCHMENU || butType == BUT_TYPE_TAB))) {
            char nativeBuf[256] = {};
            g_fn_button_string_get(but, nativeBuf, sizeof(nativeBuf));
            if (nativeBuf[0] != '\0') {
                drawStr = nativeBuf;
            }
        }
    }
    if (!drawStr.empty()) {
        size_t sepPos = drawStr.find('|');
        if (sepPos != std::string::npos) {
            drawStr = drawStr.substr(0, sepPos);
        }
    }

    // PointerRNA is at +0x208, PropertyRNA* rnaprop is at +0x260, int rnaindex is at +0x268.
    const void* rnaPoin = reinterpret_cast<const void*>(butBytes + 0x208);
    const void* rnaProp = *reinterpret_cast<const void* const*>(butBytes + 0x260);
    const int   rnaIndex = *reinterpret_cast<const int*>(butBytes + 0x268);

    std::string rnaLabel;
    std::string rnaDesc;
    if (rnaProp != nullptr) {
        if (g_fn_RNA_property_ui_name) {
            const char* nameC = g_fn_RNA_property_ui_name(rnaProp, rnaPoin);
            if (nameC && nameC[0] != '\0') {
                rnaLabel = nameC;
            }
        }
        if (fetchTooltip && g_fn_RNA_property_ui_description) {
            const char* descC = g_fn_RNA_property_ui_description(rnaProp, rnaPoin);
            if (descC && descC[0] != '\0') {
                rnaDesc = descC;
            }
        }
        if (g_fn_RNA_property_array_check && g_fn_RNA_property_array_item_char) {
            if (g_fn_RNA_property_array_check(rnaProp) && rnaIndex >= 0) {
                char axisCh = g_fn_RNA_property_array_item_char(rnaProp, rnaIndex);
                if (axisCh != '\0') {
                    std::string& targetLbl = !butStr.empty() ? butStr : rnaLabel;
                    if (!targetLbl.empty()) {
                        std::string suffix = std::string(" ") + axisCh;
                        if (targetLbl.size() < 2 || targetLbl.back() != axisCh) {
                            targetLbl += suffix;
                        }
                    }
                }
            }
        }
    }

    // Only resolve enum item text on hovered/active controls, popups, or enum-bearing widget types
    // so drawing hundreds of unfocused panel/toolbar widgets never stalls startup or redraws.
    bool shouldQueryEnum =
        fetchTooltip || isPopupContext ||
        butType == BUT_TYPE_TAB || butType == BUT_TYPE_MENU ||
        butType == BUT_TYPE_ROW || butType == BUT_TYPE_BUTMENU ||
        butType == BUT_TYPE_PULLDOWN;
    std::string enumName;
    std::string enumDesc;
    if (shouldQueryEnum && C != nullptr && g_fn_button_rna_enum_item_get != nullptr) {
        BlenderOptionalEnumItem optItem{};
        g_fn_button_rna_enum_item_get(&optItem, C, but);
        if (optItem.has_value) {
            if (optItem.name && optItem.name[0] != '\0') {
                enumName = optItem.name;
            }
            if (fetchTooltip && optItem.description && optItem.description[0] != '\0') {
                enumDesc = optItem.description;
            }
        }
    }

    // Check quick tooltip label for icon-only buttons/tools if we still have no label.
    std::string tipLabel;
    if (butStr.empty() && rnaLabel.empty() && enumName.empty() && drawStr.empty()) {
        if (g_fn_button_string_get_tooltip_label) {
            MsvcString tmp{};
            g_fn_button_string_get_tooltip_label(&tmp, but);
            tipLabel = tmp.ToStdString();
        }
        if (tipLabel.empty() && g_fn_button_string_get_label) {
            MsvcString tmp{};
            g_fn_button_string_get_label(&tmp, but);
            tipLabel = tmp.ToStdString();
        }
    }

    std::string primaryLabel = !butStr.empty() ? butStr : (!rnaLabel.empty() ? rnaLabel : tipLabel);

    if (butType == BUT_TYPE_TAB) {
        std::string tabTitle = !enumName.empty() ? enumName : (!primaryLabel.empty() ? primaryLabel : drawStr);
        if (!tabTitle.empty()) {
            outSpokenText = "Вкладка: " + tabTitle;
        }
    } else if (!primaryLabel.empty() && !drawStr.empty()) {
        if (drawStr.find(primaryLabel) == 0 || primaryLabel.find(drawStr) == 0) {
            outSpokenText = drawStr;
            if (!enumName.empty() && outSpokenText.find(enumName) == std::string::npos) {
                outSpokenText += ": " + enumName;
            }
        } else {
            outSpokenText = primaryLabel + ": " + drawStr;
        }
    } else if (!drawStr.empty()) {
        outSpokenText = drawStr;
    } else if (!enumName.empty()) {
        if (!primaryLabel.empty() && primaryLabel != enumName) {
            outSpokenText = primaryLabel + ": " + enumName;
        } else {
            outSpokenText = enumName;
        }
    } else {
        outSpokenText = primaryLabel;
    }

    if (butType == BUT_TYPE_CHECKBOX || butType == BUT_TYPE_CHECKBOXN) {
        bool isChecked = ((butFlag & (BLENDER_UI_SELECT | BLENDER_UI_SELECT_DRAW)) != 0);
        if (!outSpokenText.empty()) {
            outSpokenText += isChecked ? " (включено)" : " (выключено)";
        }
    }

    if (!enumDesc.empty() && !rnaDesc.empty() && enumDesc != rnaDesc) {
        outTooltipText = rnaDesc + ". " + enumDesc;
    } else if (!enumDesc.empty()) {
        outTooltipText = enumDesc;
    } else {
        outTooltipText = rnaDesc;
    }
}

inline void UpsertButtonInList(std::vector<NavButtonEntry>& list, const NavButtonEntry& entry, bool sortVertical) {
    ULONGLONG now = entry.lastSeenTick;
    // Keep buttons across pauses and partial redraws for 15 seconds, while immediately pruning
    // stale widgets from closed tabs once they disappear from the region's live uiblocks.
    list.erase(
        std::remove_if(list.begin(), list.end(),
            [now, &entry](const NavButtonEntry& b) {
                if (entry.regionPtr != 0 && b.regionPtr != 0 && b.regionPtr != entry.regionPtr) {
                    return false;
                }
                if (entry.regionPtr != 0 && b.regionPtr == entry.regionPtr) {
                    void* tmpPanel = nullptr;
                    void* tmpBut = nullptr;
                    if (!ValidateTargetInRegion(reinterpret_cast<void*>(entry.regionPtr), b.panelPtr, b.butPtr, tmpPanel, tmpBut)) {
                        return true;
                    }
                }
                return (now > b.lastSeenTick) && ((now - b.lastSeenTick) > 15000ULL);
            }),
        list.end());

    bool updatedMoved = false;
    for (auto& b : list) {
        bool ptrMatch = (entry.panelPtr != 0)
            ? (b.panelPtr == entry.panelPtr)
            : (b.panelPtr == 0 && b.butPtr == entry.butPtr);
        bool posMatch = (b.panelPtr == entry.panelPtr) && (b.butType == entry.butType) &&
                        (std::abs(b.winX - entry.winX) < 5 && std::abs(b.winY - entry.winY) < 5);
        if (ptrMatch || posMatch) {
            bool samePos = (std::abs(b.winX - entry.winX) < 5 && std::abs(b.winY - entry.winY) < 5);
            b.butPtr = entry.butPtr;
            b.panelPtr = entry.panelPtr;
            b.regionPtr = entry.regionPtr;
            b.areaPtr = entry.areaPtr;
            b.winX = entry.winX;
            b.winY = entry.winY;
            b.butType = entry.butType;
            b.isPopupEntry = entry.isPopupEntry;
            b.text = entry.text;
            b.tooltip = entry.tooltip;
            b.lastSeenTick = entry.lastSeenTick;
            if (samePos) {
                return;
            }
            updatedMoved = true;
            break;
        }
    }
    if (!updatedMoved) {
        list.push_back(entry);
    }

    if (sortVertical) {
        // Sort top-to-bottom (winY descending), then left-to-right (winX ascending).
        std::sort(list.begin(), list.end(), [](const NavButtonEntry& a, const NavButtonEntry& b) {
            if (std::abs(a.winY - b.winY) > 8) {
                return a.winY > b.winY;
            }
            return a.winX < b.winX;
        });
    } else {
        // Sort left-to-right (winX ascending), then top-to-bottom (winY descending).
        std::sort(list.begin(), list.end(), [](const NavButtonEntry& a, const NavButtonEntry& b) {
            if (std::abs(a.winX - b.winX) > 12) {
                return a.winX < b.winX;
            }
            return a.winY > b.winY;
        });
    }
}

inline bool StepButtonVector(std::vector<NavButtonEntry>& list, int& idx, int step, bool clickOnStep) {
    NavButtonEntry target{};
    {
        std::lock_guard<std::mutex> lock(g_navMutex);
        if (list.empty()) return false;
        int count = static_cast<int>(list.size());
        if (g_hasLastFocusedButton.load()) {
            int matched = -1;
            for (int i = 0; i < count; ++i) {
                if (list[i].butPtr == g_lastFocusedButton.butPtr) {
                    matched = i;
                    break;
                }
            }
            if (matched < 0 && !g_lastFocusedButton.text.empty()) {
                for (int i = 0; i < count; ++i) {
                    if (list[i].text == g_lastFocusedButton.text) {
                        matched = i;
                        break;
                    }
                }
            }
            if (matched >= 0) {
                idx = matched;
            }
        }
        idx = (idx + step + count) % count;
        target = list[idx];
        g_lastFocusedButton = target;
        g_hasLastFocusedButton.store(true);
    }

    if (clickOnStep) {
        PostPendingUiActivation(target);
    }

    if (!target.tooltip.empty()) {
        NvdaSpeechEngine::Instance().SetCurrentButtonTooltip(target.tooltip);
    }
    NvdaSpeechEngine::Instance().SpeakFocusedItem(target.butPtr, target.text, true);
    return true;
}

inline bool ActivateCurrentZoneButton() {
    int zone = g_currentZone.load();
    NavButtonEntry target{};
    bool found = false;
    bool inS = false, inM = false, inD = false;
    QueryLivePopupState(inS, inM, inD);
    {
        std::lock_guard<std::mutex> lock(g_navMutex);
        if ((inD || inM) && !g_popupButtons.empty()) {
            if (g_popupIdx < 0 || g_popupIdx >= static_cast<int>(g_popupButtons.size())) g_popupIdx = 0;
            target = g_popupButtons[g_popupIdx];
            found = true;
        } else if (g_hasLastFocusedButton.load()) {
            target = g_lastFocusedButton;
            found = true;
            const std::vector<NavButtonEntry>* activeList = nullptr;
            if (zone == 1) {
                activeList = &g_outlinerButtons;
            } else if (zone == 2 || IsModalSpaceOpen()) {
                activeList = &g_propButtons;
            } else if (zone == 3) {
                activeList = &g_topMenuButtons;
            }
            if (activeList != nullptr) {
                for (const auto& entry : *activeList) {
                    bool ptrSame = (target.panelPtr != 0)
                        ? (entry.panelPtr == target.panelPtr)
                        : (entry.panelPtr == 0 && entry.butPtr == target.butPtr);
                    if (ptrSame) {
                        target = entry;
                        g_lastFocusedButton = entry;
                        break;
                    }
                }
            }
        } else if (zone == 1 && !g_outlinerButtons.empty()) {
            if (g_outlinerIdx < 0 || g_outlinerIdx >= static_cast<int>(g_outlinerButtons.size())) g_outlinerIdx = 0;
            target = g_outlinerButtons[g_outlinerIdx];
            found = true;
        } else if ((zone == 2 || IsModalSpaceOpen()) && !g_propButtons.empty()) {
            if (g_propButtonIdx < 0 || g_propButtonIdx >= static_cast<int>(g_propButtons.size())) g_propButtonIdx = 0;
            target = g_propButtons[g_propButtonIdx];
            found = true;
        } else if (zone == 3 && !g_topMenuButtons.empty()) {
            if (g_topMenuIdx < 0 || g_topMenuIdx >= static_cast<int>(g_topMenuButtons.size())) g_topMenuIdx = 0;
            target = g_topMenuButtons[g_topMenuIdx];
            found = true;
        }
    }
    if (!found) return false;
    return PostPendingUiActivation(target);
}

inline void CycleMainZone(int step) {
    int nextZone = (g_currentZone.load() + step + 4) % 4;
    g_currentZone.store(nextZone);

    g_nativeMenuOpen.store(false);
    g_dialogPopupOpen.store(false);
    g_searchMenuOpen.store(false);
    g_isEditingText.store(false);
    g_hasLastFocusedButton.store(false);

    if (nextZone == 0) {
        MoveCursorToWindowPos(g_view3dCenterX.load(), g_view3dCenterY.load());
        NvdaSpeechEngine::Instance().SpeakDirect(
            "3D-сцена. Стрелки и PageUp PageDown: шаг, Alt+Стрелки: поворот, F: что впереди, C: координаты, E: захват детали, L: метка детали, J: кадр и свет, V: скан формы, F10: снимок, Shift+P: разделы и вкладки, N: ввод От и До, Shift+A: добавить",
            true);
    } else if (nextZone == 1) {
        NavButtonEntry first{};
        bool hasBtn = false;
        {
            std::lock_guard<std::mutex> lock(g_navMutex);
            if (!g_outlinerButtons.empty()) {
                if (g_outlinerIdx < 0 || g_outlinerIdx >= static_cast<int>(g_outlinerButtons.size())) g_outlinerIdx = 0;
                first = g_outlinerButtons[g_outlinerIdx];
                hasBtn = true;
            }
        }
        if (hasBtn) {
            {
                std::lock_guard<std::mutex> lock(g_navMutex);
                g_lastFocusedButton = first;
                g_hasLastFocusedButton.store(true);
            }
            NvdaSpeechEngine::Instance().SpeakDirect("Список объектов сцены: " + first.text, true);
        } else {
            NvdaSpeechEngine::Instance().SpeakDirect("Список объектов сцены. Стрелки Вверх и Вниз: выбор объекта", true);
        }
    } else if (nextZone == 2) {
        NavButtonEntry first{};
        std::string tabName;
        bool hasBtn = false;
        {
            std::lock_guard<std::mutex> lock(g_navMutex);
            if (!g_propTabs.empty() && g_propTabIdx >= 0 && g_propTabIdx < static_cast<int>(g_propTabs.size())) {
                tabName = g_propTabs[g_propTabIdx].text;
            }
            if (!g_propButtons.empty()) {
                if (g_propButtonIdx < 0 || g_propButtonIdx >= static_cast<int>(g_propButtons.size())) g_propButtonIdx = 0;
                first = g_propButtons[g_propButtonIdx];
                hasBtn = true;
            }
        }
        std::string msg = "Настройки и свойства";
        if (!tabName.empty()) msg += ". " + tabName;
        if (hasBtn) {
            {
                std::lock_guard<std::mutex> lock(g_navMutex);
                g_lastFocusedButton = first;
                g_hasLastFocusedButton.store(true);
            }
            msg += ". " + first.text;
        }
        NvdaSpeechEngine::Instance().SpeakDirect(msg, true);
    } else if (nextZone == 3) {
        NavButtonEntry first{};
        bool hasBtn = false;
        {
            std::lock_guard<std::mutex> lock(g_navMutex);
            if (!g_topMenuButtons.empty()) {
                if (g_topMenuIdx < 0 || g_topMenuIdx >= static_cast<int>(g_topMenuButtons.size())) g_topMenuIdx = 0;
                first = g_topMenuButtons[g_topMenuIdx];
                hasBtn = true;
            }
        }
        std::string msg = "Верхнее меню и панель инструментов";
        if (hasBtn) {
            {
                std::lock_guard<std::mutex> lock(g_navMutex);
                g_lastFocusedButton = first;
                g_hasLastFocusedButton.store(true);
            }
            msg += ": " + first.text;
        }
        NvdaSpeechEngine::Instance().SpeakDirect(msg, true);
    }
}
