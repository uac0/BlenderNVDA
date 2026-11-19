#include <windows.h>
#include <string>
#include <vector>
#include <mutex>
#include <atomic>
#include <algorithm>
#include <cstring>
#include <cmath>
#include "nvda_speech.hpp"
#include "pdb_resolver.hpp"
#include "trampoline.hpp"

namespace {

struct BlenderRcti {
    int xmin;
    int xmax;
    int ymin;
    int ymax;
};

struct MsvcString {
    union {
        char  buf[16];
        char* ptr;
    };
    size_t size;
    size_t capacity;

    std::string ToStdString() const {
        if (size == 0 || size > 4096) return std::string();
        const char* data = (capacity <= 15) ? buf : ptr;
        if (!data) return std::string();
        return std::string(data, size);
    }
};

struct BlenderOptionalEnumItem {
    int         value;
    int         _pad0;
    const char* identifier;
    int         icon;
    int         _pad1;
    const char* name;
    const char* description;
    bool        has_value;
    uint8_t     _pad2[7];
};

typedef void (*pfn_BLF_draw)(int fontid, const char* str, size_t str_len, void* r_info);
typedef int  (*pfn_BLF_draw_mono)(int fontid, const char* str, size_t str_len, int cwidth, int tab_columns);
typedef void (*pfn_draw_button)(const void* C, void* region, void* style, void* but, const BlenderRcti* rect);
typedef void (*pfn_draw_menu_item)(
    const void* fstyle,
    BlenderRcti* rect,
    BlenderRcti* back_rect,
    float zoom,
    bool use_unpadded,
    const char* name,
    int iconid,
    int but_flag,
    int separator_type,
    int* r_xmax);
typedef void (*pfn_button_activate_over)(void* C, void* region, void* but);

typedef MsvcString* (*pfn_button_string_get_label)(MsvcString* out, void* but);
typedef MsvcString* (*pfn_button_string_get_rna_label)(MsvcString* out, void* but);
typedef MsvcString* (*pfn_button_string_get_tooltip_label)(MsvcString* out, const void* but);
typedef MsvcString* (*pfn_button_string_get_tooltip)(MsvcString* out, const void* C, void* but);
typedef BlenderOptionalEnumItem* (*pfn_button_rna_enum_item_get)(BlenderOptionalEnumItem* out, const void* C, void* but);
typedef const char* (*pfn_RNA_property_ui_name)(const void* prop, const void* ptr);
typedef const char* (*pfn_RNA_property_ui_description)(const void* prop, const void* ptr);
typedef bool (*pfn_RNA_property_array_check)(const void* prop);
typedef char (*pfn_RNA_property_array_item_char)(const void* prop, int index);
typedef bool (*pfn_block_is_popup_any)(const void* block);
typedef bool (*pfn_block_is_menu)(const void* block);
typedef void* (*pfn_CTX_wm_region_popup)(const void* C);
typedef void* (*pfn_CTX_wm_area)(const void* C);
typedef void* (*pfn_CTX_wm_window)(const void* C);
typedef void (*pfn_button_to_pixelrect)(BlenderRcti* rect, const void* region, const void* block, const void* but);
typedef void (*pfn_button_string_get)(void* but, char* str, size_t str_maxncpy);
typedef void (*pfn_draw_aligned_panel)(
    const void* region,
    const void* style,
    const void* block,
    const BlenderRcti* rect,
    bool show_pin,
    bool show_background,
    bool region_search_filter_active);
typedef void (*pfn_file_draw_list)(const void* C, void* region);

pfn_BLF_draw                        g_orig_BLF_draw = nullptr;
pfn_BLF_draw_mono                   g_orig_BLF_draw_mono = nullptr;
pfn_draw_button                     g_orig_draw_button = nullptr;
pfn_draw_menu_item                  g_orig_draw_menu_item = nullptr;
pfn_button_activate_over            g_orig_button_activate_over = nullptr;
pfn_draw_aligned_panel              g_orig_draw_aligned_panel = nullptr;
pfn_file_draw_list                  g_orig_file_draw_list = nullptr;

pfn_button_string_get_label         g_fn_button_string_get_label = nullptr;
pfn_button_string_get_rna_label     g_fn_button_string_get_rna_label = nullptr;
pfn_button_string_get_tooltip_label g_fn_button_string_get_tooltip_label = nullptr;
pfn_button_string_get_tooltip       g_fn_button_string_get_tooltip = nullptr;
pfn_button_rna_enum_item_get        g_fn_button_rna_enum_item_get = nullptr;
pfn_RNA_property_ui_name            g_fn_RNA_property_ui_name = nullptr;
pfn_RNA_property_ui_description     g_fn_RNA_property_ui_description = nullptr;
pfn_RNA_property_array_check        g_fn_RNA_property_array_check = nullptr;
pfn_RNA_property_array_item_char    g_fn_RNA_property_array_item_char = nullptr;
pfn_block_is_popup_any              g_fn_block_is_popup_any = nullptr;
pfn_block_is_menu                   g_fn_block_is_menu = nullptr;
pfn_CTX_wm_region_popup             g_fn_CTX_wm_region_popup = nullptr;
pfn_CTX_wm_area                     g_fn_CTX_wm_area = nullptr;
pfn_CTX_wm_window                   g_fn_CTX_wm_window = nullptr;
pfn_button_to_pixelrect             g_fn_button_to_pixelrect = nullptr;
pfn_button_string_get               g_fn_button_string_get = nullptr;

constexpr int BLENDER_UI_SELECT       = (1 << 0);
constexpr int BLENDER_UI_HOVER        = (1 << 2);
constexpr int BLENDER_UI_SELECT_DRAW  = (1 << 5);
constexpr int BLENDER_BUT_HAS_SEP     = (1 << 21);
constexpr int BLENDER_BUT_DISABLED    = (1 << 13);
constexpr int BLENDER_BUT_INACTIVE    = (1 << 18);

constexpr short RGN_TYPE_WINDOW       = 0;
constexpr short RGN_TYPE_HEADER       = 1;
constexpr short RGN_TYPE_TEMPORARY    = 3;
constexpr short RGN_TYPE_UI           = 4;
constexpr short RGN_TYPE_TOOLS        = 5;
constexpr short RGN_TYPE_HUD          = 8;
constexpr short RGN_TYPE_NAV_BAR      = 9;
constexpr short RGN_TYPE_EXECUTE      = 10;
constexpr short RGN_TYPE_TOOL_HEADER  = 12;

constexpr char SPACE_VIEW3D           = 1;
constexpr char SPACE_GRAPH            = 2;
constexpr char SPACE_OUTLINER         = 3;
constexpr char SPACE_PROPERTIES       = 4;
constexpr char SPACE_FILE             = 5;
constexpr char SPACE_IMAGE            = 6;
constexpr char SPACE_INFO             = 7;
constexpr char SPACE_SEQ              = 8;
constexpr char SPACE_TEXT             = 9;
constexpr char SPACE_ACTION           = 12;
constexpr char SPACE_NLA              = 13;
constexpr char SPACE_NODE             = 16;
constexpr char SPACE_CONSOLE          = 18;
constexpr char SPACE_USERPREF         = 19;
constexpr char SPACE_CLIP             = 20;
constexpr char SPACE_TOPBAR           = 21;
constexpr char SPACE_STATUSBAR        = 22;
constexpr char SPACE_SPREADSHEET      = 23;

constexpr uint8_t BUT_TYPE_ROW        = 2;
constexpr uint8_t BUT_TYPE_TEXT       = 3;
constexpr uint8_t BUT_TYPE_TEXTBOX    = 4;
constexpr uint8_t BUT_TYPE_MENU       = 5;
constexpr uint8_t BUT_TYPE_BUTMENU    = 6;
constexpr uint8_t BUT_TYPE_NUM        = 7;
constexpr uint8_t BUT_TYPE_NUMSLIDER  = 8;
constexpr uint8_t BUT_TYPE_CHECKBOX   = 14;
constexpr uint8_t BUT_TYPE_CHECKBOXN  = 15;
constexpr uint8_t BUT_TYPE_TAB        = 17;
constexpr uint8_t BUT_TYPE_POPOVER    = 18;
constexpr uint8_t BUT_TYPE_SCROLL     = 19;
constexpr uint8_t BUT_TYPE_BLOCK      = 20;
constexpr uint8_t BUT_TYPE_LABEL      = 21;
constexpr uint8_t BUT_TYPE_PULLDOWN   = 24;
constexpr uint8_t BUT_TYPE_ROUNDBOX   = 25;
constexpr uint8_t BUT_TYPE_SEARCHMENU = 34;
constexpr uint8_t BUT_TYPE_SEPR       = 44;
constexpr uint8_t BUT_TYPE_SEPR_LINE  = 45;
constexpr uint8_t BUT_TYPE_SEPR_SPACER = 46;
constexpr uint8_t BUT_TYPE_GRIP       = 47;
constexpr uint8_t BUT_TYPE_DECORATOR  = 48;
constexpr uint8_t BUT_TYPE_VIEW_ITEM  = 49;

thread_local bool        t_inWidgetDraw = false;
thread_local std::string t_currentWidgetText;
thread_local std::string t_pendingSearchPrefix;

struct NavButtonEntry {
    uintptr_t   butPtr = 0;
    uintptr_t   regionPtr = 0;
    int         winX = 0;
    int         winY = 0;
    uint8_t     butType = 0;
    std::string text;
    std::string tooltip;
    ULONGLONG   lastSeenTick = 0;
};

// 4 Main Zones switched by F6:
// 0 = 3D-сцена (SPACE_VIEW3D)
// 1 = Список объектов сцены (SPACE_OUTLINER)
// 2 = Настройки и свойства (SPACE_PROPERTIES)
// 3 = Верхнее меню (SPACE_TOPBAR + заголовки меню)
std::atomic<int>            g_currentZone{0};

std::mutex                  g_navMutex;
std::vector<NavButtonEntry> g_propTabs;
int                         g_propTabIdx = 0;
std::vector<NavButtonEntry> g_propButtons;
int                         g_propButtonIdx = 0;

std::vector<NavButtonEntry> g_outlinerButtons;
int                         g_outlinerIdx = 0;

std::vector<NavButtonEntry> g_topMenuButtons;
int                         g_topMenuIdx = 0;

std::vector<NavButtonEntry> g_popupButtons;
int                         g_popupIdx = 0;
uintptr_t                   g_activePopupRegion = 0;

std::atomic<int>            g_view3dCenterX{600};
std::atomic<int>            g_view3dCenterY{500};

std::atomic<bool>           g_nativeMenuOpen{false};
std::atomic<ULONGLONG>      g_lastMenuDrawTick{0};
std::atomic<bool>           g_dialogPopupOpen{false};
std::atomic<ULONGLONG>      g_lastDialogDrawTick{0};
std::atomic<bool>           g_searchMenuOpen{false};
std::atomic<ULONGLONG>      g_lastSearchDrawTick{0};
std::atomic<bool>           g_isEditingText{false};
std::atomic<ULONGLONG>      g_lastEditDrawTick{0};
std::atomic<ULONGLONG>      g_lastModalSpaceDrawTick{0};
std::atomic<bool>           g_modalSpaceWasActive{false};
std::atomic<uint8_t>        g_lastModalSpaceType{0};
std::atomic<bool>           g_transformActive{false};

std::atomic<const void*>    g_lastActivatedButton{nullptr};
std::atomic<bool>           g_hooksInstalled{false};
std::atomic<bool>           g_initialMouseCentered{false};
HHOOK                       g_keyboardHook = nullptr;
DWORD                       g_mainThreadId = 0;

bool IsEditingTextNow() {
    if (!g_isEditingText.load()) return false;
    if (GetTickCount64() - g_lastEditDrawTick.load() > 900ULL) {
        g_isEditingText.store(false);
        return false;
    }
    return true;
}

bool IsModalSpaceOpen() {
    ULONGLONG last = g_lastModalSpaceDrawTick.load();
    if (last == 0) return false;
    bool active = (GetTickCount64() - last) < 900ULL;
    if (!active && g_modalSpaceWasActive.exchange(false)) {
        std::lock_guard<std::mutex> lock(g_navMutex);
        g_propTabs.clear();
        g_propButtons.clear();
        g_propTabIdx = 0;
        g_propButtonIdx = 0;
    }
    return active;
}

bool GetActiveBlenderHwnd(HWND& outHwnd) {
    HWND hwnd = GetForegroundWindow();
    if (!hwnd) return false;
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid != GetCurrentProcessId()) return false;
    outHwnd = hwnd;
    return true;
}

void MoveCursorToWindowPos(int winX, int winY) {
    HWND hwnd = nullptr;
    if (!GetActiveBlenderHwnd(hwnd)) return;
    RECT clientRect{};
    if (!GetClientRect(hwnd, &clientRect)) return;

    int clientH = clientRect.bottom - clientRect.top;
    POINT pt{};
    pt.x = winX;
    pt.y = clientH - winY;
    if (pt.x >= 0 && pt.x < clientRect.right && pt.y >= 0 && pt.y < clientH) {
        POINT screenPt = pt;
        if (ClientToScreen(hwnd, &screenPt)) {
            SetCursorPos(screenPt.x, screenPt.y);
        }
        PostMessageW(hwnd, WM_MOUSEMOVE, 0, MAKELPARAM(pt.x, pt.y));
    }
}

void ClickWindowPos(int winX, int winY) {
    HWND hwnd = nullptr;
    if (!GetActiveBlenderHwnd(hwnd)) return;
    RECT clientRect{};
    if (!GetClientRect(hwnd, &clientRect)) return;
    int clientH = clientRect.bottom - clientRect.top;
    int x = winX;
    int y = clientH - winY;
    LPARAM lParam = MAKELPARAM(x, y);
    POINT screenPt{x, y};
    if (ClientToScreen(hwnd, &screenPt)) {
        SetCursorPos(screenPt.x, screenPt.y);
    }
    PostMessageW(hwnd, WM_MOUSEMOVE, 0, lParam);
    PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lParam);
    PostMessageW(hwnd, WM_LBUTTONUP, 0, lParam);
}

// Extract native button label, value, and tooltip directly from Blender's Button & RNA APIs
void QueryNativeButtonInfo(
    const void* C,
    void* but,
    const std::string& rawDrawnText,
    std::string& outSpokenText,
    std::string& outTooltipText)
{
    const auto* butBytes = reinterpret_cast<const uint8_t*>(but);
    const int butFlag = *reinterpret_cast<const int*>(butBytes + 0x10);
    const uint8_t butType = *reinterpret_cast<const uint8_t*>(butBytes + 0x1A);

    // Read Button::str (+0x40) and Button::drawstr (+0x60) in-place without allocation
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

    // PointerRNA is at +0x208, PropertyRNA* rnaprop is at +0x260, int rnaindex is at +0x268
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
        if (g_fn_RNA_property_ui_description) {
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

    // Check Enum item (used by Properties Editor tabs, dropdowns, and enum rows)
    std::string enumName;
    std::string enumDesc;
    if (C != nullptr && g_fn_button_rna_enum_item_get != nullptr) {
        BlenderOptionalEnumItem optItem{};
        g_fn_button_rna_enum_item_get(&optItem, C, but);
        if (optItem.has_value) {
            if (optItem.name && optItem.name[0] != '\0') {
                enumName = optItem.name;
            }
            if (optItem.description && optItem.description[0] != '\0') {
                enumDesc = optItem.description;
            }
        }
    }

    // Check quick tooltip label for icon-only buttons/tools if we still have no label
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

    // Build tooltip from native description
    if (!enumDesc.empty() && !rnaDesc.empty() && enumDesc != rnaDesc) {
        outTooltipText = rnaDesc + ". " + enumDesc;
    } else if (!enumDesc.empty()) {
        outTooltipText = enumDesc;
    } else {
        outTooltipText = rnaDesc;
    }
}

void UpsertButtonInList(std::vector<NavButtonEntry>& list, const NavButtonEntry& entry, bool sortVertical) {
    ULONGLONG now = entry.lastSeenTick;
    // Remove stale buttons from the same region not drawn in the last 800 ms
    list.erase(
        std::remove_if(list.begin(), list.end(),
            [now, &entry](const NavButtonEntry& b) {
                if (entry.regionPtr != 0 && b.regionPtr != 0 && b.regionPtr != entry.regionPtr) {
                    return false;
                }
                return (now > b.lastSeenTick) && ((now - b.lastSeenTick) > 800ULL);
            }),
        list.end());

    for (auto& b : list) {
        if (b.butPtr == entry.butPtr || (std::abs(b.winX - entry.winX) < 5 && std::abs(b.winY - entry.winY) < 5)) {
            b = entry;
            return;
        }
    }
    list.push_back(entry);

    if (sortVertical) {
        // Sort top-to-bottom (winY descending), then left-to-right (winX ascending)
        std::sort(list.begin(), list.end(), [](const NavButtonEntry& a, const NavButtonEntry& b) {
            if (std::abs(a.winY - b.winY) > 8) {
                return a.winY > b.winY;
            }
            return a.winX < b.winX;
        });
    } else {
        // Sort left-to-right (winX ascending), then top-to-bottom (winY descending)
        std::sort(list.begin(), list.end(), [](const NavButtonEntry& a, const NavButtonEntry& b) {
            if (std::abs(a.winX - b.winX) > 12) {
                return a.winX < b.winX;
            }
            return a.winY > b.winY;
        });
    }
}

bool StepButtonVector(std::vector<NavButtonEntry>& list, int& idx, int step, bool clickOnStep) {
    NavButtonEntry target{};
    {
        std::lock_guard<std::mutex> lock(g_navMutex);
        if (list.empty()) return false;
        int count = static_cast<int>(list.size());
        idx = (idx + step + count) % count;
        target = list[idx];
    }

    if (clickOnStep) {
        ClickWindowPos(target.winX, target.winY);
    } else {
        MoveCursorToWindowPos(target.winX, target.winY);
    }

    if (!target.tooltip.empty()) {
        NvdaSpeechEngine::Instance().SetCurrentButtonTooltip(target.tooltip);
    }
    NvdaSpeechEngine::Instance().SpeakFocusedItem(target.butPtr, target.text, true);
    return true;
}

bool ActivateCurrentZoneButton() {
    int zone = g_currentZone.load();
    NavButtonEntry target{};
    bool found = false;
    {
        std::lock_guard<std::mutex> lock(g_navMutex);
        ULONGLONG now = GetTickCount64();
        if (g_dialogPopupOpen.load() && (now - g_lastDialogDrawTick.load() < 1200ULL) && !g_popupButtons.empty()) {
            if (g_popupIdx < 0 || g_popupIdx >= static_cast<int>(g_popupButtons.size())) g_popupIdx = 0;
            target = g_popupButtons[g_popupIdx];
            found = true;
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
    ClickWindowPos(target.winX, target.winY);
    return true;
}

void CycleMainZone(int step) {
    int nextZone = (g_currentZone.load() + step + 4) % 4;
    g_currentZone.store(nextZone);

    g_nativeMenuOpen.store(false);
    g_dialogPopupOpen.store(false);
    g_searchMenuOpen.store(false);
    g_isEditingText.store(false);

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
            MoveCursorToWindowPos(first.winX, first.winY);
            NvdaSpeechEngine::Instance().SpeakDirect("Список объектов сцены: " + first.text, true);
        } else {
            MoveCursorToWindowPos(g_view3dCenterX.load(), g_view3dCenterY.load());
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
            MoveCursorToWindowPos(first.winX, first.winY);
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
            MoveCursorToWindowPos(first.winX, first.winY);
            msg += ": " + first.text;
        }
        NvdaSpeechEngine::Instance().SpeakDirect(msg, true);
    }
}

void AppendCapturedString(const char* str, size_t str_len) {
    if (!str || str_len == 0 || str[0] == '\0') return;
    size_t actualLen = 0;
    while (actualLen < str_len && str[actualLen] != '\0') {
        ++actualLen;
    }
    if (actualLen == 0) return;
    if (actualLen == 1 && str[0] == '_') return;

    std::string piece(str, actualLen);
    if (t_inWidgetDraw) {
        if (!t_currentWidgetText.empty()) {
            t_currentWidgetText.push_back(' ');
        }
        t_currentWidgetText += piece;
    } else {
        if (g_transformActive.load()) {
            NvdaSpeechEngine::Instance().SpeakScreenTextFiltered(piece, false);
        } else {
            NvdaSpeechEngine::Instance().AppendTooltipFragment(piece);
        }
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
    if (but != nullptr) {
        g_lastActivatedButton.store(but);
    }
    if (g_orig_button_activate_over) {
        g_orig_button_activate_over(C, region, but);
    }
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
    } else {
        NvdaSpeechEngine::Instance().RegisterBackgroundText(captured);
    }
}

std::string CleanPanelText(const std::string& s) {
    std::string out;
    out.reserve(s.size());
    bool prevSpace = true;
    for (size_t i = 0; i < s.size(); ++i) {
        unsigned char c = static_cast<unsigned char>(s[i]);
        if (c == 0) break;
        if (c == '\r' || c == '\n' || c == '\t' || c == '|') {
            if (!prevSpace) {
                out.push_back(' ');
                prevSpace = true;
            }
        } else if (c < 0x20) {
            continue;
        } else if (c == ' ') {
            if (!prevSpace) {
                out.push_back(' ');
                prevSpace = true;
            }
        } else {
            out.push_back(static_cast<char>(c));
            prevSpace = false;
        }
    }
    while (!out.empty() && out.back() == ' ') out.pop_back();
    return out;
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
        if (regionType == RGN_TYPE_WINDOW || regionType == RGN_TYPE_UI || regionType == RGN_TYPE_TOOLS) {
            int winX = winrct->xmin + (rect->xmin + rect->xmax) / 2;
            int winY = winrct->ymin + rect->ymax + 12;

            NavButtonEntry entry{};
            entry.butPtr = reinterpret_cast<uintptr_t>(block) ^ 0x504E4C00ULL;
            entry.regionPtr = reinterpret_cast<uintptr_t>(region);
            entry.winX = winX;
            entry.winY = winY;
            entry.butType = BUT_TYPE_TAB;
            entry.text = "Панель: " + panelTitle;
            entry.lastSeenTick = GetTickCount64();

            std::lock_guard<std::mutex> lock(g_navMutex);
            UpsertButtonInList(g_propButtons, entry, true);
        }
    }
}

void Hook_file_draw_list(const void* C, void* region) {
    g_lastModalSpaceDrawTick.store(GetTickCount64());
    g_lastModalSpaceType.store(static_cast<uint8_t>(SPACE_FILE));
    if (g_orig_file_draw_list) {
        g_orig_file_draw_list(C, region);
    }
}

void Hook_draw_button(const void* C, void* region, void* style, void* but, const BlenderRcti* rect) {
    if (!but) {
        if (g_orig_draw_button) g_orig_draw_button(C, region, style, but, rect);
        return;
    }

    const auto* butBytes = reinterpret_cast<const uint8_t*>(but);
    const int butFlag = *reinterpret_cast<const int*>(butBytes + 0x10);
    const uint8_t butType = *reinterpret_cast<const uint8_t*>(butBytes + 0x1A);
    const void* butActive = *reinterpret_cast<const void* const*>(butBytes + 0x2A8);
    const char* butEditStr = *reinterpret_cast<const char* const*>(butBytes + 0x2C0);
    const void* butBlock = *reinterpret_cast<const void* const*>(butBytes + 0x2E8);

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

    // Ignore purely decorative separators/scrollbars/frames, but preserve ViewItem (49)
    if (butType == BUT_TYPE_SCROLL || butType == BUT_TYPE_ROUNDBOX ||
        (butType >= BUT_TYPE_SEPR && butType <= BUT_TYPE_DECORATOR)) {
        return;
    }

    std::string spokenText;
    std::string tooltipText;
    QueryNativeButtonInfo(C, but, rawDrawn, spokenText, tooltipText);

    if (spokenText.empty()) return;

    ULONGLONG now = GetTickCount64();

    if (region != nullptr && rect != nullptr) {
        const auto* winrct = reinterpret_cast<const BlenderRcti*>(reinterpret_cast<const uint8_t*>(region) + 0xA8);
        const short regionType = *reinterpret_cast<const short*>(reinterpret_cast<const uint8_t*>(region) + 0xC0);
        BlenderRcti localRect = *rect;
        if (g_fn_button_to_pixelrect != nullptr && butBlock != nullptr) {
            g_fn_button_to_pixelrect(&localRect, region, butBlock, but);
        }
        int winX = winrct->xmin + (localRect.xmin + localRect.xmax) / 2;
        int winY = winrct->ymin + (localRect.ymin + localRect.ymax) / 2;

        bool isPopup = (regionType == RGN_TYPE_TEMPORARY);
        if (!isPopup && C != nullptr && g_fn_CTX_wm_region_popup != nullptr) {
            if (g_fn_CTX_wm_region_popup(C) != nullptr) {
                isPopup = true;
            }
        }
        if (!isPopup && butBlock != nullptr && g_fn_block_is_popup_any != nullptr) {
            if (g_fn_block_is_popup_any(butBlock)) {
                isPopup = true;
            }
        }

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
                entry.regionPtr = reinterpret_cast<uintptr_t>(region);
                entry.winX = winX;
                entry.winY = winY;
                entry.butType = butType;
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
                const auto* areaRect = reinterpret_cast<const BlenderRcti*>(areaBytes + 0x38);
                const char spacetype = *reinterpret_cast<const char*>(areaBytes + 0x48);

                NavButtonEntry entry{};
                entry.butPtr = reinterpret_cast<uintptr_t>(but);
                entry.regionPtr = reinterpret_cast<uintptr_t>(region);
                entry.winX = winX;
                entry.winY = winY;
                entry.butType = butType;
                entry.text = spokenText;
                entry.tooltip = tooltipText;
                entry.lastSeenTick = now;

                std::lock_guard<std::mutex> lock(g_navMutex);
                bool modalActiveNow = (g_lastModalSpaceDrawTick.load() != 0) && ((now - g_lastModalSpaceDrawTick.load()) < 900ULL);
                if (spacetype == SPACE_USERPREF || spacetype == SPACE_FILE) {
                    g_lastModalSpaceDrawTick.store(now);
                    g_lastModalSpaceType.store(static_cast<uint8_t>(spacetype));
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
                } else if (!modalActiveNow) {
                    if (spacetype == SPACE_VIEW3D) {
                        int cx = (areaRect->xmin + areaRect->xmax) / 2;
                        int cy = (areaRect->ymin + areaRect->ymax) / 2;
                        if (cx > 0 && cy > 0) {
                            g_view3dCenterX.store(cx);
                            g_view3dCenterY.store(cy);
                            if (!g_initialMouseCentered.exchange(true)) {
                                if (!g_dialogPopupOpen.load() && !g_nativeMenuOpen.load() && !g_searchMenuOpen.load()) {
                                    MoveCursorToWindowPos(cx, cy);
                                }
                            }
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

    HWND activeHwnd = nullptr;
    if (isHoveredOrActive && GetActiveBlenderHwnd(activeHwnd)) {
        if (tooltipText.empty() && C != nullptr && g_fn_button_string_get_tooltip != nullptr) {
            MsvcString tipMsvc{};
            g_fn_button_string_get_tooltip(&tipMsvc, C, but);
            tooltipText = tipMsvc.ToStdString();
        }
        if (!tooltipText.empty()) {
            NvdaSpeechEngine::Instance().SetCurrentButtonTooltip(tooltipText);
        }
        NvdaSpeechEngine::Instance().SpeakFocusedItem(reinterpret_cast<uintptr_t>(but), spokenText, false);
    } else {
        NvdaSpeechEngine::Instance().RegisterBackgroundText(spokenText);
    }
}

LRESULT CALLBACK BlenderKeyboardProc(int code, WPARAM wParam, LPARAM lParam) {
    if (code == HC_ACTION) {
        bool isKeyDown = ((lParam & (1LL << 31)) == 0);
        if (isKeyDown) {
            bool shiftDown = (GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0;
            bool ctrlDown  = (GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0;
            bool altDown   = ((GetAsyncKeyState(VK_MENU) & 0x8000) != 0) || ((lParam & (1LL << 29)) != 0);

            // Never intercept Alt+Tab or any Alt shortcut so window switching never hangs
            if (altDown) {
                return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
            }

            ULONGLONG now  = GetTickCount64();

            bool inSearchMenu  = g_searchMenuOpen.load() && ((now - g_lastSearchDrawTick.load()) < 900ULL);
            bool inNativeMenu  = g_nativeMenuOpen.load() && ((now - g_lastMenuDrawTick.load()) < 900ULL);
            bool inDialogPopup = g_dialogPopupOpen.load() && ((now - g_lastDialogDrawTick.load()) < 900ULL);

            // F1 or F5: Speak detailed native tooltip of the current button on demand
            if ((wParam == VK_F1 || wParam == VK_F5) && !ctrlDown) {
                NvdaSpeechEngine::Instance().SpeakCurrentTooltip();
                return 1;
            }

            // F6: Switch between the 4 main Blender zones
            if (wParam == VK_F6 && !ctrlDown) {
                CycleMainZone(shiftDown ? -1 : 1);
                return 1;
            }

            if (wParam == VK_F3) {
                g_searchMenuOpen.store(true);
                g_lastSearchDrawTick.store(now);
                NvdaSpeechEngine::Instance().CancelSpeechAndResetFocus();
                return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
            }

            if (wParam == VK_ESCAPE) {
                bool wasPopupOpen = (inSearchMenu || inNativeMenu || inDialogPopup);
                bool inModalSpaceEsc = IsModalSpaceOpen();
                int prevZone = g_currentZone.exchange(0);
                {
                    std::lock_guard<std::mutex> lock(g_navMutex);
                    g_popupButtons.clear();
                    g_activePopupRegion = 0;
                }
                g_nativeMenuOpen.store(false);
                g_dialogPopupOpen.store(false);
                g_searchMenuOpen.store(false);
                g_isEditingText.store(false);
                g_lastEditDrawTick.store(0);
                g_transformActive.store(false);
                NvdaSpeechEngine::Instance().CancelSpeechAndResetFocus();
                if (!inModalSpaceEsc) {
                    MoveCursorToWindowPos(g_view3dCenterX.load(), g_view3dCenterY.load());
                }
                if (wasPopupOpen) {
                    NvdaSpeechEngine::Instance().SpeakDirect("Окно закрыто. 3D-сцена", true);
                } else if (prevZone != 0 && !inModalSpaceEsc) {
                    NvdaSpeechEngine::Instance().SpeakDirect("Возврат в 3D-сцену", true);
                }
                return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
            }

            // 1. If a Native Menu (e.g. Shift+A, Файл) or F3 Search is open:
            // Let Blender handle Up/Down/Left/Right/Enter natively without moving the mouse!
            if (inSearchMenu || inNativeMenu) {
                if (wParam == VK_UP || wParam == VK_DOWN || wParam == VK_LEFT || wParam == VK_RIGHT ||
                    wParam == VK_PRIOR || wParam == VK_NEXT)
                {
                    NvdaSpeechEngine::Instance().CancelSpeechAndResetFocus();
                } else if (wParam == VK_RETURN) {
                    g_nativeMenuOpen.store(false);
                    g_searchMenuOpen.store(false);
                    NvdaSpeechEngine::Instance().CancelSpeechAndResetFocus();
                }
                return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
            }

            // 2. If a Dialog Popup (e.g. N "Координаты От и До" or F9 Operator props) is open:
            if (inDialogPopup) {
                if (wParam == VK_RETURN) {
                    NvdaSpeechEngine::Instance().CancelSpeechAndResetFocus();
                    if (IsEditingTextNow()) {
                        // Commit typed value inside the active number/text box
                        g_isEditingText.store(false);
                        return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
                    } else {
                        ActivateCurrentZoneButton();
                        return 1;
                    }
                }
                if (!IsEditingTextNow() && !ctrlDown) {
                    if (wParam == VK_DOWN || wParam == VK_UP || wParam == VK_TAB) {
                        int dir = (wParam == VK_UP || (wParam == VK_TAB && shiftDown)) ? -1 : 1;
                        if (StepButtonVector(g_popupButtons, g_popupIdx, dir, false)) {
                            return 1;
                        }
                    }
                }
                return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
            }

            // 3. When no menu/popup is open, route by active Zone (0..3), or active modal Space (Preferences / File Browser):
            int zone = g_currentZone.load();
            bool inModalSpace = IsModalSpaceOpen();

            if (zone == 0 && !inModalSpace) {
                // Zone 0: 3D-сцена — pass all keys directly to Blender's native 3D View keymap!
                if (!IsEditingTextNow() && !ctrlDown && !altDown) {
                    if (wParam == 'G' || wParam == 'R' || wParam == 'S') {
                        g_transformActive.store(true);
                    }
                }
                return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
            }

            // In File Browser (Ctrl+S / Ctrl+O): let arrow keys, PageUp/Down, Home/End, Enter, and Backspace
            // pass directly to Blender's native file list instead of snapping cursor to header buttons;
            // Tab / Shift+Tab still walks between File Browser controls.
            if (inModalSpace && g_lastModalSpaceType.load() == static_cast<uint8_t>(SPACE_FILE)) {
                if (wParam == VK_UP || wParam == VK_DOWN || wParam == VK_LEFT || wParam == VK_RIGHT ||
                    wParam == VK_PRIOR || wParam == VK_NEXT || wParam == VK_HOME || wParam == VK_END ||
                    wParam == VK_RETURN || wParam == VK_BACK) {
                    NvdaSpeechEngine::Instance().CancelSpeechAndResetFocus();
                    return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
                }
            }

            // Zones 1, 2, 3 (Outliner, Properties, Top Menu) or Modal Space (Preferences, File Browser):
            if (wParam == VK_RETURN) {
                NvdaSpeechEngine::Instance().CancelSpeechAndResetFocus();
                if (IsEditingTextNow()) {
                    g_isEditingText.store(false);
                    return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
                }
                if (ActivateCurrentZoneButton()) {
                    return 1;
                }
                return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
            }

            if (!IsEditingTextNow() && !ctrlDown && !altDown) {
                if (inModalSpace || zone == 2) {
                    // Zone 2 / Modal Space (Preferences, File Browser, Shading/Material panels):
                    // Left / Right switches Tabs if >= 2 tabs exist; otherwise steps controls without leaking to 3D View!
                    if (wParam == VK_LEFT || wParam == VK_RIGHT) {
                        int dir = (wParam == VK_RIGHT) ? 1 : -1;
                        bool hasTabs = false;
                        {
                            std::lock_guard<std::mutex> lock(g_navMutex);
                            hasTabs = (g_propTabs.size() >= 2);
                            if (hasTabs) {
                                g_propButtons.clear();
                                g_propButtonIdx = 0;
                            }
                        }
                        if (hasTabs) {
                            StepButtonVector(g_propTabs, g_propTabIdx, dir, true);
                        } else if (!StepButtonVector(g_propButtons, g_propButtonIdx, dir, false)) {
                            NvdaSpeechEngine::Instance().SpeakDirect("В этом разделе одна вкладка", true);
                        }
                        return 1;
                    }
                    if (wParam == VK_DOWN || wParam == VK_UP || wParam == VK_TAB) {
                        int dir = (wParam == VK_UP || (wParam == VK_TAB && shiftDown)) ? -1 : 1;
                        if (!StepButtonVector(g_propButtons, g_propButtonIdx, dir, false)) {
                            NvdaSpeechEngine::Instance().SpeakDirect("Нет доступных элементов, нажмите F6 для смены зоны", true);
                        }
                        return 1;
                    }
                } else if (zone == 3) {
                    // Zone 3: Верхнее меню
                    if (wParam == VK_LEFT || wParam == VK_RIGHT || wParam == VK_DOWN || wParam == VK_UP) {
                        int dir = (wParam == VK_RIGHT || wParam == VK_DOWN) ? 1 : -1;
                        StepButtonVector(g_topMenuButtons, g_topMenuIdx, dir, false);
                        return 1;
                    }
                } else if (zone == 1) {
                    // Zone 1: Список объектов сцены (Outliner)
                    if (wParam == VK_DOWN || wParam == VK_UP) {
                        int dir = (wParam == VK_DOWN) ? 1 : -1;
                        StepButtonVector(g_outlinerButtons, g_outlinerIdx, dir, false);
                        return 1;
                    }
                }
            }
        }
    }
    return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
}

std::wstring GetModuleFolder(HMODULE hMod) {
    wchar_t buf[MAX_PATH * 2] = {0};
    DWORD len = GetModuleFileNameW(hMod, buf, MAX_PATH * 2);
    if (len == 0) return L"";
    std::wstring full(buf, len);
    size_t pos = full.find_last_of(L"\\/");
    return (pos != std::wstring::npos) ? full.substr(0, pos) : L"";
}

std::atomic<int> g_hookFlags{0};

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
    ULONGLONG now = GetTickCount64();
    bool inSearchMenu  = g_searchMenuOpen.load() && ((now - g_lastSearchDrawTick.load()) < 900ULL);
    bool inNativeMenu  = g_nativeMenuOpen.load() && ((now - g_lastMenuDrawTick.load()) < 900ULL);
    bool inDialogPopup = g_dialogPopupOpen.load() && ((now - g_lastDialogDrawTick.load()) < 900ULL);
    return (inSearchMenu || inNativeMenu || inDialogPopup) ? 1 : 0;
}

extern "C" __declspec(dllexport) void CenterMouseInView3D() {
    MoveCursorToWindowPos(g_view3dCenterX.load(), g_view3dCenterY.load());
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
