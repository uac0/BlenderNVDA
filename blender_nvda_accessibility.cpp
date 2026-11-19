#include <windows.h>
#include <functional>
#include <string>
#include "blender_ui_types.hpp"
#include "keyboard_hook.hpp"
#include "nvda_speech.hpp"
#include "pdb_resolver.hpp"
#include "trampoline.hpp"
#include "ui_button_query.hpp"

namespace {

void AppendCapturedString(const char* str, size_t str_len) {
    if (!str || str_len == 0 || str[0] == '\0') return;
    size_t actualLen = 0;
    while (actualLen < str_len && str[actualLen] != '\0') {
        ++actualLen;
    }
    if (actualLen == 0) return;
    if (actualLen == 1 && str[0] == '_') return;

    if (t_inWidgetDraw) {
        std::string piece(str, actualLen);
        if (!t_currentWidgetText.empty()) {
            t_currentWidgetText.push_back(' ');
        }
        t_currentWidgetText += piece;
    } else if (g_transformActive.load()) {
        std::string piece(str, actualLen);
        NvdaSpeechEngine::Instance().SpeakScreenTextFiltered(piece, false);
    }
}

void Hook_BLF_draw(int fontid, const char* str, size_t str_len, void* r_info) {
    if (str && str_len > 0 && str[0] != '\0') {
        AppendCapturedString(str, str_len);
    }
    if (g_orig_BLF_draw) {
        g_orig_BLF_draw(fontid, str, str_len, r_info);
    }
}

int Hook_BLF_draw_mono(int fontid, const char* str, size_t str_len, int cwidth, int tab_columns) {
    if (str && str_len > 0 && str[0] != '\0') {
        AppendCapturedString(str, str_len);
    }
    if (g_orig_BLF_draw_mono) {
        return g_orig_BLF_draw_mono(fontid, str, str_len, cwidth, tab_columns);
    }
    return 0;
}

void Hook_button_activate_over(void* C, void* region, void* but) {
    if (C != nullptr) {
        g_lastBlenderContext.store(C);
    }
    if (but != nullptr) {
        g_lastActivatedButton.store(but);
    }
    if (g_orig_button_activate_over) {
        g_orig_button_activate_over(C, region, but);
    }
}

LRESULT CALLBACK Hook_s_wndProc(HWND hwnd, UINT uMsg, WPARAM wParam, LPARAM lParam) {
    if (uMsg == WM_APP_NVDA_ACTIVATE) {
        ExecutePendingUiAction();
        return 0;
    }
    if (g_orig_s_wndProc) {
        return g_orig_s_wndProc(hwnd, uMsg, wParam, lParam);
    }
    return DefWindowProcW(hwnd, uMsg, wParam, lParam);
}

void Hook_draw_menu_item(
    const void* fstyle,
    BlenderRcti* rect,
    BlenderRcti* back_rect,
    float zoom,
    bool use_unpadded,
    const char* name,
    int iconid,
    int but_flag,
    int separator_type,
    int* r_xmax)
{
    g_searchMenuOpen.store(true);
    g_lastSearchDrawTick.store(GetTickCount64());

    bool prevInDraw = t_inWidgetDraw;
    std::string prevText = std::move(t_currentWidgetText);
    t_inWidgetDraw = true;
    t_currentWidgetText.clear();

    if (g_orig_draw_menu_item) {
        g_orig_draw_menu_item(fstyle, rect, back_rect, zoom, use_unpadded, name, iconid, but_flag, separator_type, r_xmax);
    }

    std::string captured = std::move(t_currentWidgetText);
    if (captured.empty() && name && name[0] != '\0') {
        captured = name;
    }

    t_inWidgetDraw = prevInDraw;
    t_currentWidgetText = std::move(prevText);

    if (captured.empty()) return;

    bool isHovered = ((but_flag & BLENDER_UI_HOVER) != 0);
    bool isPrefixPart = (isHovered && ((but_flag & BLENDER_BUT_INACTIVE) != 0) && back_rect != nullptr && r_xmax != nullptr);

    if (isHovered) {
        if (isPrefixPart) {
            t_pendingSearchPrefix = captured;
        } else {
            std::string fullItem = captured;
            if (!t_pendingSearchPrefix.empty()) {
                fullItem = t_pendingSearchPrefix + " " + captured;
                t_pendingSearchPrefix.clear();
            }
            uintptr_t itemId = 0xF3000000ULL ^ std::hash<std::string>{}(fullItem);
            NvdaSpeechEngine::Instance().SpeakFocusedItem(itemId, fullItem, false);
        }
    }
}

void Hook_draw_aligned_panel(
    const void* region,
    const void* style,
    const void* block,
    const BlenderRcti* rect,
    bool show_pin,
    bool show_background,
    bool region_search_filter_active)
{
    bool prevInDraw = t_inWidgetDraw;
    std::string prevText = std::move(t_currentWidgetText);
    t_inWidgetDraw = true;
    t_currentWidgetText.clear();

    if (g_orig_draw_aligned_panel) {
        g_orig_draw_aligned_panel(region, style, block, rect, show_pin, show_background, region_search_filter_active);
    }

    std::string panelTitle = CleanPanelText(t_currentWidgetText);
    t_inWidgetDraw = prevInDraw;
    t_currentWidgetText = std::move(prevText);

    if (!panelTitle.empty() && region != nullptr && rect != nullptr && block != nullptr) {
        const auto* winrct = reinterpret_cast<const BlenderRcti*>(reinterpret_cast<const uint8_t*>(region) + 0xA8);
        const short regionType = *reinterpret_cast<const short*>(reinterpret_cast<const uint8_t*>(region) + 0xC0);
        if (regionType == RGN_TYPE_WINDOW ||
            (regionType == RGN_TYPE_UI && reinterpret_cast<uintptr_t>(region) == g_lastActiveSidebarRegion.load()))
        {
            int winX = 0;
            int winY = 0;
            float bx = static_cast<float>(rect->xmin) + 24.0f;
            float by = static_cast<float>(rect->ymax) + 10.0f;
            BlockToWindowXY(region, block, bx, by, winX, winY);
            if (winX < winrct->xmin || winX > winrct->xmax) {
                return;
            }
            if (regionType != RGN_TYPE_WINDOW && (winY < winrct->ymin || winY > winrct->ymax)) {
                return;
            }
            const void* panel = *reinterpret_cast<const void* const*>(reinterpret_cast<const uint8_t*>(block) + 0x50);
            std::string stateSuffix;
            if (panel != nullptr) {
                bool isClosed = ((*reinterpret_cast<const uint8_t*>(reinterpret_cast<const uint8_t*>(panel) + 0x82) & 0x04) != 0);
                stateSuffix = isClosed ? " (свёрнута)" : " (открыта)";
            }

            NavButtonEntry entry{};
            entry.butPtr = reinterpret_cast<uintptr_t>(panel != nullptr ? panel : block) ^ 0x504E4C00ULL;
            entry.panelPtr = reinterpret_cast<uintptr_t>(panel);
            entry.regionPtr = reinterpret_cast<uintptr_t>(region);
            entry.areaPtr = 0;
            entry.winX = winX;
            entry.winY = winY;
            entry.butType = BUT_TYPE_TAB;
            entry.isPopupEntry = false;
            entry.text = "Панель: " + panelTitle + stateSuffix;
            entry.lastSeenTick = GetTickCount64();

            std::lock_guard<std::mutex> lock(g_navMutex);
            UpsertButtonInList(g_propButtons, entry, true);
        }
    }
}

void Hook_file_draw_list(const void* C, void* region) {
    if (C != nullptr) {
        g_lastBlenderContext.store(const_cast<void*>(C));
    }
    HWND fg = nullptr;
    if (GetActiveBlenderHwnd(fg)) {
        g_modalSpaceHwnd.store(fg);
    }
    g_lastModalSpaceDrawTick.store(GetTickCount64());
    g_lastModalSpaceType.store(static_cast<uint8_t>(SPACE_FILE));
    if (g_orig_file_draw_list) {
        g_orig_file_draw_list(C, region);
    }
}

void Hook_draw_button(const void* C, void* region, void* style, void* but, const BlenderRcti* rect) {
    if (C != nullptr) {
        g_lastBlenderContext.store(const_cast<void*>(C));
    }
    if (!but) {
        if (g_orig_draw_button) g_orig_draw_button(C, region, style, but, rect);
        return;
    }

    const auto* butBytes = reinterpret_cast<const uint8_t*>(but);
    const int butFlag = *reinterpret_cast<const int*>(butBytes + 0x10);
    const uint8_t butType = *reinterpret_cast<const uint8_t*>(butBytes + 0x1A);
    const void* butActive = *reinterpret_cast<const void* const*>(butBytes + 0x2A8);
    const char* butEditStr = *reinterpret_cast<const char* const*>(butBytes + 0x2C0);
    const void* butBlock = *reinterpret_cast<const void* const*>(butBytes + 0x288);

    if (butEditStr != nullptr) {
        g_isEditingText.store(true);
        g_lastEditDrawTick.store(GetTickCount64());
    }

    bool isHoveredOrActive =
        ((butFlag & BLENDER_UI_HOVER) != 0) ||
        (butActive != nullptr) ||
        (butEditStr != nullptr);

    bool prevInDraw = t_inWidgetDraw;
    std::string prevText = std::move(t_currentWidgetText);

    t_inWidgetDraw = true;
    t_currentWidgetText.clear();

    if (g_orig_draw_button) {
        g_orig_draw_button(C, region, style, but, rect);
    }

    std::string rawDrawn = std::move(t_currentWidgetText);

    t_inWidgetDraw = prevInDraw;
    t_currentWidgetText = std::move(prevText);

    // Ignore purely decorative separators/scrollbars/frames, but preserve ViewItem (49).
    if (butType == BUT_TYPE_SCROLL || butType == BUT_TYPE_ROUNDBOX ||
        (butType >= BUT_TYPE_SEPR && butType <= BUT_TYPE_DECORATOR)) {
        return;
    }

    bool isPopup = false;
    bool isPopupBlock = (butBlock != nullptr && g_fn_block_is_popup_any != nullptr && g_fn_block_is_popup_any(butBlock));
    bool isCtxPopup = (C != nullptr && g_fn_CTX_wm_region_popup != nullptr && g_fn_CTX_wm_region_popup(C) != nullptr);
    const BlenderRcti* winrct = nullptr;
    short regionType = -1;
    if (region != nullptr) {
        winrct = reinterpret_cast<const BlenderRcti*>(reinterpret_cast<const uint8_t*>(region) + 0xA8);
        regionType = *reinterpret_cast<const short*>(reinterpret_cast<const uint8_t*>(region) + 0xC0);
        // Never treat label-only hover tooltips (RGN_TYPE_TEMPORARY + BUT_TYPE_LABEL) as interactive popups.
        isPopup = isPopupBlock || isCtxPopup || (regionType == RGN_TYPE_TEMPORARY && butType != BUT_TYPE_LABEL);
    }

    std::string spokenText;
    std::string tooltipText;
    QueryNativeButtonInfo(C, but, rawDrawn, isHoveredOrActive, isPopup, spokenText, tooltipText);

    if (g_debugNavUi && region != nullptr && !isPopup &&
        (regionType == RGN_TYPE_NAV_BAR || butType == BUT_TYPE_CHECKBOX || butType == BUT_TYPE_CHECKBOXN || butType == BUT_TYPE_TAB))
    {
        std::fprintf(stderr, "DBG_BTN rType=%d bType=%d rect=(%d..%d,%d..%d) win=(%d..%d,%d..%d) spoken='%s' raw='%s'\n",
                     (int)regionType, (int)butType,
                     rect ? rect->xmin : -1, rect ? rect->xmax : -1, rect ? rect->ymin : -1, rect ? rect->ymax : -1,
                     winrct ? winrct->xmin : -1, winrct ? winrct->xmax : -1, winrct ? winrct->ymin : -1, winrct ? winrct->ymax : -1,
                     spokenText.c_str(), rawDrawn.c_str());
    }

    if (spokenText.empty()) return;

    ULONGLONG now = GetTickCount64();

    if (region != nullptr && rect != nullptr) {
        BlenderRcti localRect = *rect;
        if ((localRect.xmin == localRect.xmax || localRect.ymin == localRect.ymax) &&
            g_fn_button_to_pixelrect != nullptr && butBlock != nullptr) {
            g_fn_button_to_pixelrect(&localRect, region, butBlock, but);
        }
        int winX = winrct->xmin + (localRect.xmin + localRect.xmax) / 2;
        int winY = winrct->ymin + (localRect.ymin + localRect.ymax) / 2;

        if (isPopup) {
            bool isMenu = false;
            if (butBlock != nullptr && g_fn_block_is_menu != nullptr) {
                isMenu = g_fn_block_is_menu(butBlock);
            }
            if (isMenu) {
                g_nativeMenuOpen.store(true);
                g_lastMenuDrawTick.store(now);
            } else if (butType != BUT_TYPE_LABEL) {
                g_dialogPopupOpen.store(true);
                g_lastDialogDrawTick.store(now);
                NavButtonEntry entry{};
                entry.butPtr = reinterpret_cast<uintptr_t>(but);
                entry.panelPtr = 0;
                entry.regionPtr = reinterpret_cast<uintptr_t>(region);
                entry.areaPtr = 0;
                entry.winX = winX;
                entry.winY = winY;
                entry.butType = butType;
                entry.isPopupEntry = true;
                entry.text = spokenText;
                entry.tooltip = tooltipText;
                entry.lastSeenTick = now;
                std::lock_guard<std::mutex> lock(g_navMutex);
                if (g_activePopupRegion != reinterpret_cast<uintptr_t>(region)) {
                    g_activePopupRegion = reinterpret_cast<uintptr_t>(region);
                    g_popupButtons.clear();
                    g_popupIdx = 0;
                }
                UpsertButtonInList(g_popupButtons, entry, true);
            }
        } else if (butType != BUT_TYPE_LABEL && C != nullptr && g_fn_CTX_wm_area != nullptr) {
            const void* area = g_fn_CTX_wm_area(C);
            if (area != nullptr) {
                const auto* areaBytes = reinterpret_cast<const uint8_t*>(area);
                const char spacetype = *reinterpret_cast<const char*>(areaBytes + 0x48);

                if (winX < winrct->xmin || winX > winrct->xmax) {
                    return;
                }
                bool allowVerticalScroll = (regionType == RGN_TYPE_WINDOW) &&
                                           (spacetype == SPACE_PROPERTIES || spacetype == SPACE_USERPREF);
                if (!allowVerticalScroll && (winY < winrct->ymin || winY > winrct->ymax)) {
                    return;
                }

                NavButtonEntry entry{};
                entry.butPtr = reinterpret_cast<uintptr_t>(but);
                entry.panelPtr = 0;
                entry.regionPtr = reinterpret_cast<uintptr_t>(region);
                entry.areaPtr = reinterpret_cast<uintptr_t>(area);
                entry.winX = winX;
                entry.winY = winY;
                entry.butType = butType;
                entry.isPopupEntry = false;
                entry.text = spokenText;
                entry.tooltip = tooltipText;
                entry.lastSeenTick = now;

                if (spacetype == SPACE_USERPREF || spacetype == SPACE_FILE) {
                    HWND fg = nullptr;
                    if (GetActiveBlenderHwnd(fg)) {
                        g_modalSpaceHwnd.store(fg);
                    }
                    g_lastModalSpaceDrawTick.store(now);
                    g_lastModalSpaceType.store(static_cast<uint8_t>(spacetype));
                    std::lock_guard<std::mutex> lock(g_navMutex);
                    if (!g_modalSpaceWasActive.exchange(true)) {
                        g_propTabs.clear();
                        g_propButtons.clear();
                        g_propTabIdx = 0;
                        g_propButtonIdx = 0;
                    }
                    bool isNavTab =
                        (butType == BUT_TYPE_TAB) ||
                        (regionType == RGN_TYPE_NAV_BAR) ||
                        (butType == BUT_TYPE_ROW && regionType == RGN_TYPE_UI);
                    if (isNavTab) {
                        UpsertButtonInList(g_propTabs, entry, true);
                    } else if (regionType == RGN_TYPE_WINDOW || regionType == RGN_TYPE_EXECUTE ||
                               regionType == RGN_TYPE_HEADER || regionType == RGN_TYPE_TOOL_HEADER ||
                               regionType == RGN_TYPE_TOOLS || regionType == RGN_TYPE_UI) {
                        UpsertButtonInList(g_propButtons, entry, true);
                    }
                } else {
                    bool modalActiveNow = IsModalSpaceOpen();
                    std::lock_guard<std::mutex> lock(g_navMutex);
                    if (!modalActiveNow) {
                        if (spacetype == SPACE_VIEW3D) {
                            if (regionType == RGN_TYPE_WINDOW &&
                                (winrct->xmax - winrct->xmin) > 100 &&
                                (winrct->ymax - winrct->ymin) > 100)
                            {
                                g_view3dCenterX.store((winrct->xmin + winrct->xmax) / 2);
                                g_view3dCenterY.store((winrct->ymin + winrct->ymax) / 2);
                            }
                            if (regionType == RGN_TYPE_HEADER || regionType == RGN_TYPE_TOOL_HEADER || regionType == RGN_TYPE_UI) {
                                UpsertButtonInList(g_topMenuButtons, entry, false);
                            }
                        } else if (spacetype == SPACE_TOPBAR) {
                            UpsertButtonInList(g_topMenuButtons, entry, false);
                        } else if (spacetype == SPACE_OUTLINER) {
                            if (regionType == RGN_TYPE_WINDOW) {
                                UpsertButtonInList(g_outlinerButtons, entry, true);
                            }
                        } else if (spacetype == SPACE_PROPERTIES) {
                            if (butType == BUT_TYPE_TAB || regionType == RGN_TYPE_NAV_BAR) {
                                UpsertButtonInList(g_propTabs, entry, true);
                            } else if (regionType == RGN_TYPE_WINDOW) {
                                UpsertButtonInList(g_propButtons, entry, true);
                            }
                        } else if (spacetype == SPACE_NODE || spacetype == SPACE_GRAPH || spacetype == SPACE_IMAGE ||
                                   spacetype == SPACE_SEQ || spacetype == SPACE_TEXT || spacetype == SPACE_ACTION ||
                                   spacetype == SPACE_NLA || spacetype == SPACE_CONSOLE || spacetype == SPACE_INFO ||
                                   spacetype == SPACE_CLIP || spacetype == SPACE_SPREADSHEET) {
                            if (regionType == RGN_TYPE_UI) {
                                g_lastActiveSidebarRegion.store(reinterpret_cast<uintptr_t>(region));
                            }
                            if (regionType == RGN_TYPE_HEADER || regionType == RGN_TYPE_TOOL_HEADER) {
                                UpsertButtonInList(g_topMenuButtons, entry, false);
                            } else if (regionType == RGN_TYPE_WINDOW || regionType == RGN_TYPE_UI ||
                                       regionType == RGN_TYPE_TOOLS || regionType == RGN_TYPE_HUD) {
                                UpsertButtonInList(g_propButtons, entry, true);
                            }
                        }
                    }
                }
            }
        }
    }

    // Separate popup/menu focus from panel/zone focus:
    // - Popups & Shift+A menus speak strictly when the drawn widget belongs to an active popup.
    // - Panels/Zones speak passively only for activated or text-edited buttons so Zone 0 stays silent.
    bool allowPopupFocus = isPopup;
    bool allowPanelFocus = ((g_currentZone.load() != 0) || IsModalSpaceOpen()) &&
                           (but == g_lastActivatedButton.load() || butEditStr != nullptr);
    HWND activeHwnd = nullptr;
    if ((allowPopupFocus || allowPanelFocus) && isHoveredOrActive && GetActiveBlenderHwnd(activeHwnd)) {
        if (tooltipText.empty() && C != nullptr && g_fn_button_string_get_tooltip != nullptr) {
            MsvcString tipMsvc{};
            g_fn_button_string_get_tooltip(&tipMsvc, C, but);
            tooltipText = tipMsvc.ToStdString();
        }
        if (!tooltipText.empty()) {
            NvdaSpeechEngine::Instance().SetCurrentButtonTooltip(tooltipText);
        }
        NvdaSpeechEngine::Instance().SpeakFocusedItem(reinterpret_cast<uintptr_t>(but), spokenText, false);
    }
}

std::wstring GetModuleFolder(HMODULE hMod) {
    wchar_t buf[MAX_PATH * 2] = {0};
    DWORD len = GetModuleFileNameW(hMod, buf, MAX_PATH * 2);
    if (len == 0) return L"";
    std::wstring full(buf, len);
    size_t pos = full.find_last_of(L"\\/");
    return (pos != std::wstring::npos) ? full.substr(0, pos) : L"";
}

} // namespace

extern "C" __declspec(dllexport) int InitBlenderAccessibility() {
    bool expected = false;
    if (!g_hooksInstalled.compare_exchange_strong(expected, true)) {
        return 1;
    }

    HMODULE hExe = GetModuleHandleW(nullptr);
    std::wstring exeDir = GetModuleFolder(hExe);

    HMODULE hSelf = nullptr;
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(&InitBlenderAccessibility),
        &hSelf);
    std::wstring dllDir = GetModuleFolder(hSelf);

    if (!NvdaSpeechEngine::Instance().Initialize(dllDir)) {
        NvdaSpeechEngine::Instance().Initialize(exeDir);
    }

    std::wstring pdbPath = exeDir + L"\\blender.pdb";
    std::wstring cachePath = (!dllDir.empty() ? dllDir : exeDir) + L"\\blender_nvda_symbols.cache";
    ResolvedBlenderSymbols syms{};
    if (!BlenderSymbolResolver::ResolveFromPdb(hExe, pdbPath, syms, cachePath)) {
        return -1;
    }

    g_fn_button_string_get_label         = reinterpret_cast<pfn_button_string_get_label>(syms.fn_button_string_get_label);
    g_fn_button_string_get_rna_label     = reinterpret_cast<pfn_button_string_get_rna_label>(syms.fn_button_string_get_rna_label);
    g_fn_button_string_get_tooltip_label = reinterpret_cast<pfn_button_string_get_tooltip_label>(syms.fn_button_string_get_tooltip_label);
    g_fn_button_string_get_tooltip       = reinterpret_cast<pfn_button_string_get_tooltip>(syms.fn_button_string_get_tooltip);
    g_fn_button_rna_enum_item_get        = reinterpret_cast<pfn_button_rna_enum_item_get>(syms.fn_button_rna_enum_item_get);
    g_fn_RNA_property_ui_name            = reinterpret_cast<pfn_RNA_property_ui_name>(syms.fn_RNA_property_ui_name);
    g_fn_RNA_property_ui_description     = reinterpret_cast<pfn_RNA_property_ui_description>(syms.fn_RNA_property_ui_description);
    g_fn_RNA_property_array_check        = reinterpret_cast<pfn_RNA_property_array_check>(syms.fn_RNA_property_array_check);
    g_fn_RNA_property_array_item_char    = reinterpret_cast<pfn_RNA_property_array_item_char>(syms.fn_RNA_property_array_item_char);
    g_fn_block_is_popup_any              = reinterpret_cast<pfn_block_is_popup_any>(syms.fn_block_is_popup_any);
    g_fn_block_is_menu                   = reinterpret_cast<pfn_block_is_menu>(syms.fn_block_is_menu);
    g_fn_CTX_wm_region_popup             = reinterpret_cast<pfn_CTX_wm_region_popup>(syms.fn_CTX_wm_region_popup);
    g_fn_CTX_wm_area                     = reinterpret_cast<pfn_CTX_wm_area>(syms.fn_CTX_wm_area);
    g_fn_CTX_wm_window                   = reinterpret_cast<pfn_CTX_wm_window>(syms.fn_CTX_wm_window);
    g_fn_button_to_pixelrect             = reinterpret_cast<pfn_button_to_pixelrect>(syms.fn_button_to_pixelrect);
    g_fn_button_string_get               = reinterpret_cast<pfn_button_string_get>(syms.fn_button_string_get);
    g_fn_button_execute                  = reinterpret_cast<pfn_button_execute>(syms.fn_button_execute);
    g_fn_button_activate_event           = reinterpret_cast<pfn_button_activate_event>(syms.fn_button_activate_event);
    g_fn_textbutton_activate_but         = reinterpret_cast<pfn_textbutton_activate_but>(syms.fn_textbutton_activate_but);
    g_fn_CTX_wm_area_set                 = reinterpret_cast<pfn_CTX_wm_area_set>(syms.fn_CTX_wm_area_set);
    g_fn_CTX_wm_region_set               = reinterpret_cast<pfn_CTX_wm_region_set>(syms.fn_CTX_wm_region_set);
    g_fn_CTX_wm_region                   = reinterpret_cast<pfn_CTX_wm_region>(syms.fn_CTX_wm_region);
    g_fn_CTX_wm_screen                   = reinterpret_cast<pfn_CTX_wm_screen>(syms.fn_CTX_wm_screen);
    g_fn_ED_region_tag_redraw            = reinterpret_cast<pfn_ED_region_tag_redraw>(syms.fn_ED_region_tag_redraw);
    g_fn_CTX_wm_window_set               = reinterpret_cast<pfn_CTX_wm_window_set>(syms.fn_CTX_wm_window_set);
    g_debugNavUi                         = (GetEnvironmentVariableW(L"NVDA_DEBUG_UI", nullptr, 0) > 0);

    uint8_t* arena = FunctionInterceptor::AllocateNearAddress(reinterpret_cast<uintptr_t>(hExe));
    if (!arena) {
        return -2;
    }
    uint8_t* cursor = arena;

    if (syms.fn_BLF_draw) {
        FunctionInterceptor::InstallDetour(
            syms.fn_BLF_draw,
            reinterpret_cast<uintptr_t>(&Hook_BLF_draw),
            cursor,
            reinterpret_cast<void**>(&g_orig_BLF_draw));
    }
    if (syms.fn_BLF_draw_mono) {
        FunctionInterceptor::InstallDetour(
            syms.fn_BLF_draw_mono,
            reinterpret_cast<uintptr_t>(&Hook_BLF_draw_mono),
            cursor,
            reinterpret_cast<void**>(&g_orig_BLF_draw_mono));
    }
    if (syms.fn_draw_button) {
        FunctionInterceptor::InstallDetour(
            syms.fn_draw_button,
            reinterpret_cast<uintptr_t>(&Hook_draw_button),
            cursor,
            reinterpret_cast<void**>(&g_orig_draw_button));
    }
    if (syms.fn_draw_menu_item) {
        FunctionInterceptor::InstallDetour(
            syms.fn_draw_menu_item,
            reinterpret_cast<uintptr_t>(&Hook_draw_menu_item),
            cursor,
            reinterpret_cast<void**>(&g_orig_draw_menu_item));
    }
    if (syms.fn_button_activate_over) {
        FunctionInterceptor::InstallDetour(
            syms.fn_button_activate_over,
            reinterpret_cast<uintptr_t>(&Hook_button_activate_over),
            cursor,
            reinterpret_cast<void**>(&g_orig_button_activate_over));
    }

    int flags = 0;
    if (syms.fn_CTX_wm_window) {
        flags |= 1;
    }
    if (syms.fn_draw_aligned_panel) {
        flags |= 2;
        if (FunctionInterceptor::InstallDetour(
                syms.fn_draw_aligned_panel,
                reinterpret_cast<uintptr_t>(&Hook_draw_aligned_panel),
                cursor,
                reinterpret_cast<void**>(&g_orig_draw_aligned_panel)))
        {
            flags |= 4;
        }
    }
    if (syms.fn_file_draw_list) {
        flags |= 8;
        if (FunctionInterceptor::InstallDetour(
                syms.fn_file_draw_list,
                reinterpret_cast<uintptr_t>(&Hook_file_draw_list),
                cursor,
                reinterpret_cast<void**>(&g_orig_file_draw_list)))
        {
            flags |= 16;
        }
    }
    if (syms.fn_button_execute && syms.fn_button_activate_event && syms.fn_CTX_wm_screen && syms.fn_ED_region_tag_redraw) {
        flags |= 32;
    }
    if (syms.fn_s_wndProc) {
        if (FunctionInterceptor::InstallDetour(
                syms.fn_s_wndProc,
                reinterpret_cast<uintptr_t>(&Hook_s_wndProc),
                cursor,
                reinterpret_cast<void**>(&g_orig_s_wndProc)))
        {
            flags |= 64;
        }
    }
    g_hookFlags.store(flags);

    g_mainThreadId = GetCurrentThreadId();
    g_keyboardHook = SetWindowsHookExW(WH_KEYBOARD, BlenderKeyboardProc, nullptr, g_mainThreadId);

    return 1;
}

extern "C" __declspec(dllexport) void SpeakBlenderText(const char* utf8Text, int interrupt) {
    if (!utf8Text) return;
    NvdaSpeechEngine::Instance().SpeakDirect(utf8Text, interrupt != 0);
}

extern "C" __declspec(dllexport) int GetActiveBlenderZone() {
    return g_currentZone.load();
}

extern "C" __declspec(dllexport) void SetActiveBlenderZone(int zone) {
    if (zone >= 0 && zone <= 3) {
        g_currentZone.store(zone);
        g_nativeMenuOpen.store(false);
        g_dialogPopupOpen.store(false);
        g_searchMenuOpen.store(false);
    }
}

extern "C" __declspec(dllexport) int GetAccessibilityHookFlags() {
    return g_hookFlags.load();
}

extern "C" __declspec(dllexport) int IsBlenderPopupOpen() {
    bool inSearchMenu = false;
    bool inNativeMenu = false;
    bool inDialogPopup = false;
    return QueryLivePopupState(inSearchMenu, inNativeMenu, inDialogPopup) ? 1 : 0;
}

extern "C" __declspec(dllexport) void CenterMouseInView3D() {
    MoveCursorToWindowPos(g_view3dCenterX.load(), g_view3dCenterY.load());
}

extern "C" __declspec(dllexport) int GetZoneButtonCount(int zoneKind) {
    // zoneKind: 1=outliner, 2=props/panel buttons, 3=topbar, 4=prop tabs, 5=popup
    std::lock_guard<std::mutex> lock(g_navMutex);
    switch (zoneKind) {
        case 1: return static_cast<int>(g_outlinerButtons.size());
        case 2: return static_cast<int>(g_propButtons.size());
        case 3: return static_cast<int>(g_topMenuButtons.size());
        case 4: return static_cast<int>(g_propTabs.size());
        case 5: return static_cast<int>(g_popupButtons.size());
        default: return 0;
    }
}

extern "C" __declspec(dllexport) int ActivateZoneButtonBySubstring(int zoneKind, const char* utf8Substr) {
    if (!utf8Substr || utf8Substr[0] == '\0') return 0;
    std::string needle(utf8Substr);
    NavButtonEntry found{};
    bool ok = false;
    {
        std::lock_guard<std::mutex> lock(g_navMutex);
        const std::vector<NavButtonEntry>* vec = nullptr;
        switch (zoneKind) {
            case 1: vec = &g_outlinerButtons; break;
            case 2: vec = &g_propButtons; break;
            case 3: vec = &g_topMenuButtons; break;
            case 4: vec = &g_propTabs; break;
            case 5: vec = &g_popupButtons; break;
            default: break;
        }
        if (vec) {
            for (const auto& e : *vec) {
                if (e.text.find(needle) != std::string::npos) {
                    found = e;
                    ok = true;
                    break;
                }
            }
        }
    }
    if (!ok) return 0;
    return PostPendingUiActivation(found) ? 1 : 0;
}

extern "C" __declspec(dllexport) int GetLastUiExecStatus() {
    return g_lastUiExecStatus.load();
}

extern "C" __declspec(dllexport) int GetZoneItemInfo(int zoneKind, int idx, char* outBuf, int outCap, int* outType, int* outIsPanel) {
    std::lock_guard<std::mutex> lock(g_navMutex);
    const std::vector<NavButtonEntry>* vec = nullptr;
    switch (zoneKind) {
        case 1: vec = &g_outlinerButtons; break;
        case 2: vec = &g_propButtons; break;
        case 3: vec = &g_topMenuButtons; break;
        case 4: vec = &g_propTabs; break;
        case 5: vec = &g_popupButtons; break;
        default: break;
    }
    if (!vec || idx < 0 || idx >= static_cast<int>(vec->size())) return 0;
    const auto& e = (*vec)[idx];
    if (outType) *outType = static_cast<int>(e.butType);
    if (outIsPanel) *outIsPanel = (e.panelPtr != 0) ? 1 : 0;
    if (outBuf && outCap > 0) {
        int n = static_cast<int>((std::min)(e.text.size(), static_cast<size_t>(outCap - 1)));
        std::memcpy(outBuf, e.text.data(), n);
        outBuf[n] = '\0';
    }
    return 1;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved) {
    (void)lpReserved;
    if (ul_reason_for_call == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
    } else if (ul_reason_for_call == DLL_PROCESS_DETACH) {
        if (g_keyboardHook) {
            UnhookWindowsHookEx(g_keyboardHook);
            g_keyboardHook = nullptr;
        }
    }
    return TRUE;
}
