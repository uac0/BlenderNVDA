#pragma once

#include <windows.h>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>
#include "nvda_speech.hpp"

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
typedef LRESULT (CALLBACK *pfn_s_wndProc)(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam);
typedef void (*pfn_button_execute)(const void* C, void* region, void* but);
typedef void (*pfn_button_activate_event)(void* C, void* region, void* but);
typedef bool (*pfn_textbutton_activate_but)(const void* C, void* but);
typedef void (*pfn_CTX_wm_area_set)(void* C, void* area);
typedef void (*pfn_CTX_wm_region_set)(void* C, void* region);
typedef void* (*pfn_CTX_wm_region)(const void* C);
typedef void* (*pfn_CTX_wm_screen)(const void* C);
typedef void (*pfn_ED_region_tag_redraw)(void* region);
typedef void (*pfn_CTX_wm_window_set)(void* C, void* win);

inline pfn_BLF_draw                        g_orig_BLF_draw = nullptr;
inline pfn_BLF_draw_mono                   g_orig_BLF_draw_mono = nullptr;
inline pfn_draw_button                     g_orig_draw_button = nullptr;
inline pfn_draw_menu_item                  g_orig_draw_menu_item = nullptr;
inline pfn_button_activate_over            g_orig_button_activate_over = nullptr;
inline pfn_draw_aligned_panel              g_orig_draw_aligned_panel = nullptr;
inline pfn_file_draw_list                  g_orig_file_draw_list = nullptr;
inline pfn_s_wndProc                       g_orig_s_wndProc = nullptr;

inline pfn_button_string_get_label         g_fn_button_string_get_label = nullptr;
inline pfn_button_string_get_rna_label     g_fn_button_string_get_rna_label = nullptr;
inline pfn_button_string_get_tooltip_label g_fn_button_string_get_tooltip_label = nullptr;
inline pfn_button_string_get_tooltip       g_fn_button_string_get_tooltip = nullptr;
inline pfn_button_rna_enum_item_get        g_fn_button_rna_enum_item_get = nullptr;
inline pfn_RNA_property_ui_name            g_fn_RNA_property_ui_name = nullptr;
inline pfn_RNA_property_ui_description     g_fn_RNA_property_ui_description = nullptr;
inline pfn_RNA_property_array_check        g_fn_RNA_property_array_check = nullptr;
inline pfn_RNA_property_array_item_char    g_fn_RNA_property_array_item_char = nullptr;
inline pfn_block_is_popup_any              g_fn_block_is_popup_any = nullptr;
inline pfn_block_is_menu                   g_fn_block_is_menu = nullptr;
inline pfn_CTX_wm_region_popup             g_fn_CTX_wm_region_popup = nullptr;
inline pfn_CTX_wm_area                     g_fn_CTX_wm_area = nullptr;
inline pfn_CTX_wm_window                   g_fn_CTX_wm_window = nullptr;
inline pfn_button_to_pixelrect             g_fn_button_to_pixelrect = nullptr;
inline pfn_button_string_get               g_fn_button_string_get = nullptr;
inline pfn_button_execute                  g_fn_button_execute = nullptr;
inline pfn_button_activate_event           g_fn_button_activate_event = nullptr;
inline pfn_textbutton_activate_but         g_fn_textbutton_activate_but = nullptr;
inline pfn_CTX_wm_area_set                 g_fn_CTX_wm_area_set = nullptr;
inline pfn_CTX_wm_region_set               g_fn_CTX_wm_region_set = nullptr;
inline pfn_CTX_wm_region                   g_fn_CTX_wm_region = nullptr;
inline pfn_CTX_wm_screen                   g_fn_CTX_wm_screen = nullptr;
inline pfn_ED_region_tag_redraw            g_fn_ED_region_tag_redraw = nullptr;
inline pfn_CTX_wm_window_set               g_fn_CTX_wm_window_set = nullptr;

constexpr UINT WM_APP_NVDA_ACTIVATE        = WM_APP + 0x77;

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

constexpr uint8_t BUT_TYPE_BUT        = 1;
constexpr uint8_t BUT_TYPE_ROW        = 2;
constexpr uint8_t BUT_TYPE_TEXT       = 3;
constexpr uint8_t BUT_TYPE_TEXTBOX    = 4;
constexpr uint8_t BUT_TYPE_MENU       = 5;
constexpr uint8_t BUT_TYPE_BUTMENU    = 6;
constexpr uint8_t BUT_TYPE_NUM        = 7;
constexpr uint8_t BUT_TYPE_NUMSLIDER  = 8;
constexpr uint8_t BUT_TYPE_TOG        = 9;
constexpr uint8_t BUT_TYPE_TOGN       = 10;
constexpr uint8_t BUT_TYPE_TOG3       = 11;
constexpr uint8_t BUT_TYPE_ICONTOG    = 12;
constexpr uint8_t BUT_TYPE_ICONTOGN   = 13;
constexpr uint8_t BUT_TYPE_CHECKBOX   = 14;
constexpr uint8_t BUT_TYPE_CHECKBOXN  = 15;
constexpr uint8_t BUT_TYPE_OPTION     = 16;
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

inline thread_local bool        t_inWidgetDraw = false;
inline thread_local std::string t_currentWidgetText;
inline thread_local std::string t_pendingSearchPrefix;

struct NavButtonEntry {
    uintptr_t   butPtr = 0;
    uintptr_t   panelPtr = 0;
    uintptr_t   regionPtr = 0;
    uintptr_t   areaPtr = 0;
    int         winX = 0;
    int         winY = 0;
    uint8_t     butType = 0;
    bool        isPopupEntry = false;
    std::string text;
    std::string tooltip;
    ULONGLONG   lastSeenTick = 0;
};

struct PendingUiAction {
    uintptr_t   butPtr = 0;
    uintptr_t   panelPtr = 0;
    uintptr_t   regionPtr = 0;
    uintptr_t   areaPtr = 0;
    uint8_t     butType = 0;
    bool        isPopupEntry = false;
    std::string text;
    bool        valid = false;
};

// 4 Main Zones switched by F6:
// 0 = 3D-сцена (SPACE_VIEW3D)
// 1 = Список объектов сцены (SPACE_OUTLINER)
// 2 = Настройки и свойства (SPACE_PROPERTIES)
// 3 = Верхнее меню (SPACE_TOPBAR + заголовки меню)
inline std::atomic<int>            g_currentZone{0};

inline std::mutex                  g_navMutex;
inline std::vector<NavButtonEntry> g_propTabs;
inline int                         g_propTabIdx = 0;
inline std::vector<NavButtonEntry> g_propButtons;
inline int                         g_propButtonIdx = 0;

inline std::vector<NavButtonEntry> g_outlinerButtons;
inline int                         g_outlinerIdx = 0;

inline std::vector<NavButtonEntry> g_topMenuButtons;
inline int                         g_topMenuIdx = 0;

inline std::vector<NavButtonEntry> g_popupButtons;
inline int                         g_popupIdx = 0;
inline uintptr_t                   g_activePopupRegion = 0;

inline std::atomic<int>            g_view3dCenterX{600};
inline std::atomic<int>            g_view3dCenterY{500};

inline std::atomic<bool>           g_nativeMenuOpen{false};
inline std::atomic<ULONGLONG>      g_lastMenuDrawTick{0};
inline std::atomic<bool>           g_dialogPopupOpen{false};
inline std::atomic<ULONGLONG>      g_lastDialogDrawTick{0};
inline std::atomic<bool>           g_searchMenuOpen{false};
inline std::atomic<ULONGLONG>      g_lastSearchDrawTick{0};
inline std::atomic<bool>           g_isEditingText{false};
inline std::atomic<ULONGLONG>      g_lastEditDrawTick{0};
inline std::atomic<ULONGLONG>      g_lastModalSpaceDrawTick{0};
inline std::atomic<bool>           g_modalSpaceWasActive{false};
inline std::atomic<uint8_t>        g_lastModalSpaceType{0};
inline std::atomic<HWND>           g_modalSpaceHwnd{nullptr};
inline std::atomic<bool>           g_transformActive{false};

inline std::atomic<const void*>    g_lastActivatedButton{nullptr};
inline std::atomic<void*>          g_lastBlenderContext{nullptr};
inline std::atomic<uintptr_t>      g_lastActiveSidebarRegion{0};
inline std::string                 g_lastActivePropTabText;
inline bool                        g_debugNavUi = false;
inline std::mutex                  g_pendingUiMutex;
inline PendingUiAction             g_pendingUiAction{};
inline NavButtonEntry              g_lastFocusedButton{};
inline std::atomic<bool>           g_hasLastFocusedButton{false};
inline std::atomic<bool>           g_hooksInstalled{false};
inline std::atomic<bool>           g_initialMouseCentered{false};
inline HHOOK                       g_keyboardHook = nullptr;
inline DWORD                       g_mainThreadId = 0;
inline std::atomic<int>            g_hookFlags{0};

inline bool IsEditingTextNow() {
    if (!g_isEditingText.load()) return false;
    if (GetTickCount64() - g_lastEditDrawTick.load() > 900ULL) {
        g_isEditingText.store(false);
        return false;
    }
    return true;
}

inline void* GetActiveWindowScreenSafe(void* win) {
    if (!win) return nullptr;
    void* hook = *reinterpret_cast<void* const*>(reinterpret_cast<const uint8_t*>(win) + 0x70);
    if (!hook) return nullptr;
    void* layout = *reinterpret_cast<void* const*>(reinterpret_cast<const uint8_t*>(hook) + 0x08);
    return layout ? *reinterpret_cast<void* const*>(reinterpret_cast<const uint8_t*>(layout) + 0x10) : nullptr;
}

template <typename Fn>
inline bool ForEachLiveScreen(void* C, Fn&& fn) {
    if (!C) return false;
    if (g_fn_CTX_wm_window && g_fn_CTX_wm_screen && g_fn_CTX_wm_window(C)) {
        void* scr = g_fn_CTX_wm_screen(C);
        if (scr && fn(nullptr, scr)) return true;
    }
    void* wm = *reinterpret_cast<void* const*>(reinterpret_cast<const uint8_t*>(C) + 0x08);
    if (!wm) return false;
    void* win = *reinterpret_cast<void* const*>(reinterpret_cast<const uint8_t*>(wm) + 0x198);
    int wCount = 0;
    while (win && wCount < 32) {
        void* scr = GetActiveWindowScreenSafe(win);
        if (scr && fn(win, scr)) return true;
        win = *reinterpret_cast<void* const*>(win);
        ++wCount;
    }
    return false;
}

inline bool IsModalSpaceOpen() {
    ULONGLONG last = g_lastModalSpaceDrawTick.load();
    if (last == 0) return false;

    bool active = false;
    HWND fg = GetForegroundWindow();
    HWND modalHwnd = g_modalSpaceHwnd.load();
    if (modalHwnd != nullptr && fg == modalHwnd) {
        void* C = g_lastBlenderContext.load();
        uint8_t targetSpace = g_lastModalSpaceType.load();
        ForEachLiveScreen(C, [targetSpace, &active](void*, void* scr) -> bool {
            void* area = *reinterpret_cast<void* const*>(reinterpret_cast<const uint8_t*>(scr) + 0x1b8);
            int aCount = 0;
            while (area && aCount < 64) {
                uint8_t st = static_cast<uint8_t>(*reinterpret_cast<const char*>(reinterpret_cast<const uint8_t*>(area) + 0x48));
                if (st == targetSpace) {
                    active = true;
                    return true;
                }
                area = *reinterpret_cast<void* const*>(area);
                ++aCount;
            }
            return false;
        });
    }
    if (!active) {
        active = (GetTickCount64() - last) < 900ULL && (modalHwnd == nullptr || fg == modalHwnd);
    }

    if (!active && g_modalSpaceWasActive.exchange(false)) {
        g_lastModalSpaceDrawTick.store(0);
        g_modalSpaceHwnd.store(nullptr);
        std::lock_guard<std::mutex> lock(g_navMutex);
        g_propTabs.clear();
        g_propButtons.clear();
        g_propTabIdx = 0;
        g_propButtonIdx = 0;
    }
    return active;
}

inline bool GetActiveBlenderHwnd(HWND& outHwnd) {
    HWND hwnd = GetForegroundWindow();
    if (!hwnd) return false;
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid != GetCurrentProcessId()) return false;
    outHwnd = hwnd;
    return true;
}

inline bool HasLivePopupRegionOnScreen(bool* outIsMenu = nullptr) {
    if (outIsMenu) *outIsMenu = false;
    void* C = g_lastBlenderContext.load();
    if (!C) return false;
    bool foundPopup = false;
    ForEachLiveScreen(C, [outIsMenu, &foundPopup](void*, void* scr) -> bool {
        void* region = *reinterpret_cast<void* const*>(reinterpret_cast<const uint8_t*>(scr) + 0x1c8);
        int rCount = 0;
        while (region && rCount < 64) {
            const auto* rBytes = reinterpret_cast<const uint8_t*>(region);
            short rType = *reinterpret_cast<const short*>(rBytes + 0xC0);
            if (rType == RGN_TYPE_TEMPORARY) {
                const void* runtime = *reinterpret_cast<const void* const*>(rBytes + 0x138);
                if (runtime) {
                    const void* blk = *reinterpret_cast<const void* const*>(reinterpret_cast<const uint8_t*>(runtime) + 0x1f8);
                    int bCount = 0;
                    while (blk && bCount < 64) {
                        bool isBlkMenu = (g_fn_block_is_menu != nullptr) && g_fn_block_is_menu(blk);
                        bool isBlkPopup = isBlkMenu || ((g_fn_block_is_popup_any != nullptr) && g_fn_block_is_popup_any(blk));
                        if (isBlkPopup) {
                            if (outIsMenu) *outIsMenu = isBlkMenu;
                            foundPopup = true;
                            return true;
                        }
                        blk = *reinterpret_cast<const void* const*>(blk);
                        ++bCount;
                    }
                }
            }
            region = *reinterpret_cast<void* const*>(region);
            ++rCount;
        }
        return false;
    });
    return foundPopup;
}

inline bool QueryLivePopupState(bool& outInSearchMenu, bool& outInNativeMenu, bool& outInDialogPopup) {
    outInSearchMenu = false;
    outInNativeMenu = false;
    outInDialogPopup = false;

    ULONGLONG now = GetTickCount64();
    bool liveIsMenu = false;
    bool liveOpen = HasLivePopupRegionOnScreen(&liveIsMenu);

    if (liveOpen) {
        if (g_searchMenuOpen.load()) {
            outInSearchMenu = true;
            g_lastSearchDrawTick.store(now);
        } else if (liveIsMenu || g_nativeMenuOpen.load()) {
            outInNativeMenu = true;
            g_lastMenuDrawTick.store(now);
        } else {
            outInDialogPopup = true;
            g_lastDialogDrawTick.store(now);
        }
        return true;
    }

    // Brief startup grace window only for F3 search before its first popup region paints.
    if (g_searchMenuOpen.load() && ((now - g_lastSearchDrawTick.load()) < 450ULL)) {
        outInSearchMenu = true;
        return true;
    }

    g_nativeMenuOpen.store(false);
    g_dialogPopupOpen.store(false);
    g_searchMenuOpen.store(false);
    return false;
}

inline void MoveCursorToWindowPos(int winX, int winY) {
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

inline void BlockToWindowXY(const void* region, const void* block, float bx, float by, int& outWinX, int& outWinY) {
    const auto* winrct = reinterpret_cast<const BlenderRcti*>(reinterpret_cast<const uint8_t*>(region) + 0xA8);
    const auto* blockBytes = reinterpret_cast<const uint8_t*>(block);
    const void* panel = *reinterpret_cast<const void* const*>(blockBytes + 0x50);
    if (panel != nullptr) {
        const auto* panelBytes = reinterpret_cast<const uint8_t*>(panel);
        bx += static_cast<float>(*reinterpret_cast<const int*>(panelBytes + 0x68));
        by += static_cast<float>(*reinterpret_cast<const int*>(panelBytes + 0x6c));
    }
    const float* winmat = reinterpret_cast<const float*>(blockBytes + 0x248);
    float gx = winmat[0] * bx + winmat[4] * by + winmat[12];
    float gy = winmat[1] * bx + winmat[5] * by + winmat[13];
    int sizex = (winrct->xmax - winrct->xmin) + 1;
    int sizey = (winrct->ymax - winrct->ymin) + 1;
    outWinX = winrct->xmin + static_cast<int>(std::lround((0.5f * gx + 0.5f) * static_cast<float>(sizex)));
    outWinY = winrct->ymin + static_cast<int>(std::lround((0.5f * gy + 0.5f) * static_cast<float>(sizey)));
}

inline bool FindMainThreadBlenderHwnd(HWND& outHwnd) {
    if (GetActiveBlenderHwnd(outHwnd)) return true;
    struct FinderCtx {
        HWND found = nullptr;
    } ctx{};
    EnumThreadWindows(g_mainThreadId ? g_mainThreadId : GetCurrentThreadId(),
        [](HWND hwnd, LPARAM lp) -> BOOL {
            if (IsWindowVisible(hwnd) && GetWindow(hwnd, GW_OWNER) == nullptr) {
                reinterpret_cast<FinderCtx*>(lp)->found = hwnd;
                return FALSE;
            }
            return TRUE;
        },
        reinterpret_cast<LPARAM>(&ctx));
    outHwnd = ctx.found;
    return outHwnd != nullptr;
}

inline bool PostPendingUiActivation(const NavButtonEntry& entry) {
    HWND hwnd = nullptr;
    if (!FindMainThreadBlenderHwnd(hwnd)) return false;
    {
        std::lock_guard<std::mutex> lock(g_pendingUiMutex);
        g_pendingUiAction.butPtr = entry.butPtr;
        g_pendingUiAction.panelPtr = entry.panelPtr;
        g_pendingUiAction.regionPtr = entry.regionPtr;
        g_pendingUiAction.areaPtr = entry.areaPtr;
        g_pendingUiAction.butType = entry.butType;
        g_pendingUiAction.isPopupEntry = entry.isPopupEntry;
        g_pendingUiAction.text = entry.text;
        g_pendingUiAction.valid = true;
    }
    return PostMessageW(hwnd, WM_APP_NVDA_ACTIVATE, 0, 0) != FALSE;
}

inline bool ValidateTargetInRegion(
    void* region,
    uintptr_t targetPanel,
    uintptr_t targetBut,
    void*& outPanel,
    void*& outBut)
{
    outPanel = nullptr;
    outBut = nullptr;
    if (!region) return false;
    const void* runtime = *reinterpret_cast<const void* const*>(reinterpret_cast<const uint8_t*>(region) + 0x138);
    if (!runtime) return false;
    const void* blk = *reinterpret_cast<const void* const*>(reinterpret_cast<const uint8_t*>(runtime) + 0x1f8);
    int bCount = 0;
    while (blk && bCount < 128) {
        const auto* blkBytes = reinterpret_cast<const uint8_t*>(blk);
        if (targetPanel != 0) {
            void* pnl = *reinterpret_cast<void* const*>(blkBytes + 0x50);
            if (reinterpret_cast<uintptr_t>(pnl) == targetPanel) {
                outPanel = pnl;
                return true;
            }
        } else if (targetBut != 0) {
            void* const* beginPtr = *reinterpret_cast<void* const* const*>(blkBytes + 0x10);
            void* const* endPtr = *reinterpret_cast<void* const* const*>(blkBytes + 0x18);
            if (beginPtr && endPtr && endPtr >= beginPtr && (endPtr - beginPtr) <= 8192) {
                for (void* const* it = beginPtr; it < endPtr; ++it) {
                    if (reinterpret_cast<uintptr_t>(*it) == targetBut) {
                        outBut = *it;
                        return true;
                    }
                }
            }
        }
        blk = *reinterpret_cast<const void* const*>(blk);
        ++bCount;
    }
    return false;
}

inline bool ShouldExecuteButtonDirectly(uint8_t butType) {
    switch (butType) {
        case BUT_TYPE_BUT:
        case BUT_TYPE_ROW:
        case BUT_TYPE_BUTMENU:
        case BUT_TYPE_TOG:
        case BUT_TYPE_TOGN:
        case BUT_TYPE_TOG3:
        case BUT_TYPE_ICONTOG:
        case BUT_TYPE_ICONTOGN:
        case BUT_TYPE_CHECKBOX:
        case BUT_TYPE_CHECKBOXN:
        case BUT_TYPE_OPTION:
        case BUT_TYPE_TAB:
            return true;
        default:
            return false;
    }
}

inline std::atomic<int>             g_lastUiExecStatus{0};

inline int ExecutePendingUiAction() {
    PendingUiAction action{};
    {
        std::lock_guard<std::mutex> lock(g_pendingUiMutex);
        if (!g_pendingUiAction.valid) { g_lastUiExecStatus.store(-1); return -1; }
        action = std::move(g_pendingUiAction);
        g_pendingUiAction = PendingUiAction{};
    }

    void* C = g_lastBlenderContext.load();
    if (!C || !g_fn_CTX_wm_screen) { g_lastUiExecStatus.store(-2); return -2; }

    void* prevWin = g_fn_CTX_wm_window ? g_fn_CTX_wm_window(C) : nullptr;
    void* targetWin = prevWin;
    void* liveArea = nullptr;
    void* liveRegion = nullptr;
    void* livePanel = nullptr;
    void* liveBut = nullptr;

    auto searchScreen = [&](void* scr) -> bool {
        if (!scr) return false;
        if (action.isPopupEntry) {
            void* r = *reinterpret_cast<void* const*>(reinterpret_cast<const uint8_t*>(scr) + 0x1c8);
            int rCount = 0;
            while (r && rCount < 64) {
                if ((action.regionPtr == 0 || reinterpret_cast<uintptr_t>(r) == action.regionPtr) &&
                    ValidateTargetInRegion(r, action.panelPtr, action.butPtr, livePanel, liveBut))
                {
                    liveRegion = r;
                    return true;
                }
                r = *reinterpret_cast<void* const*>(r);
                ++rCount;
            }
        }
        void* area = *reinterpret_cast<void* const*>(reinterpret_cast<const uint8_t*>(scr) + 0x1b8);
        int aCount = 0;
        while (area && aCount < 64) {
            if (action.areaPtr == 0 || reinterpret_cast<uintptr_t>(area) == action.areaPtr) {
                void* r = *reinterpret_cast<void* const*>(reinterpret_cast<const uint8_t*>(area) + 0x80);
                int rCount = 0;
                while (r && rCount < 64) {
                    if ((action.regionPtr == 0 || reinterpret_cast<uintptr_t>(r) == action.regionPtr) &&
                        ValidateTargetInRegion(r, action.panelPtr, action.butPtr, livePanel, liveBut))
                    {
                        liveArea = area;
                        liveRegion = r;
                        return true;
                    }
                    r = *reinterpret_cast<void* const*>(r);
                    ++rCount;
                }
            }
            area = *reinterpret_cast<void* const*>(area);
            ++aCount;
        }
        return false;
    };

    if (prevWin) {
        searchScreen(g_fn_CTX_wm_screen(C));
    }
    if (!liveRegion) {
        void* wm = *reinterpret_cast<void* const*>(reinterpret_cast<const uint8_t*>(C) + 0x08);
        if (wm) {
            void* win = *reinterpret_cast<void* const*>(reinterpret_cast<const uint8_t*>(wm) + 0x198);
            int wCount = 0;
            while (win && wCount < 32) {
                void* scr = GetActiveWindowScreenSafe(win);
                if (searchScreen(scr)) {
                    targetWin = win;
                    break;
                }
                win = *reinterpret_cast<void* const*>(win);
                ++wCount;
            }
        }
    }

    if (!targetWin) { g_lastUiExecStatus.store(-3); return -3; }
    if (!liveRegion || (!livePanel && !liveBut)) {
        g_lastUiExecStatus.store(-5);
        return -5;
    }

    bool switchedWin = (targetWin != prevWin);
    if (switchedWin && g_fn_CTX_wm_window_set) {
        g_fn_CTX_wm_window_set(C, targetWin);
    }

    void* prevArea = g_fn_CTX_wm_area ? g_fn_CTX_wm_area(C) : nullptr;
    void* prevRegion = g_fn_CTX_wm_region ? g_fn_CTX_wm_region(C) : nullptr;

    if (liveArea && g_fn_CTX_wm_area_set) {
        g_fn_CTX_wm_area_set(C, liveArea);
    }
    if (g_fn_CTX_wm_region_set) {
        g_fn_CTX_wm_region_set(C, liveRegion);
    }

    int status = 0;
    if (livePanel) {
        uint8_t* flagPtr = reinterpret_cast<uint8_t*>(livePanel) + 0x82;
        *flagPtr ^= 0x04;
        bool nowClosed = ((*flagPtr & 0x04) != 0);
        if (g_fn_ED_region_tag_redraw) {
            g_fn_ED_region_tag_redraw(liveRegion);
        }
        std::string updatedText = action.text;
        const std::string closedTag = " (свёрнута)";
        const std::string openTag = " (открыта)";
        size_t posClosed = updatedText.rfind(closedTag);
        size_t posOpen = updatedText.rfind(openTag);
        if (posClosed != std::string::npos) {
            updatedText.replace(posClosed, closedTag.size(), nowClosed ? closedTag : openTag);
        } else if (posOpen != std::string::npos) {
            updatedText.replace(posOpen, openTag.size(), nowClosed ? closedTag : openTag);
        }
        {
            std::lock_guard<std::mutex> lock(g_navMutex);
            if (g_hasLastFocusedButton.load() && g_lastFocusedButton.panelPtr == action.panelPtr) {
                g_lastFocusedButton.text = updatedText;
            }
            for (auto& b : g_propButtons) {
                if (b.panelPtr == action.panelPtr) {
                    b.text = updatedText;
                }
            }
        }
        NvdaSpeechEngine::Instance().SpeakDirect(updatedText, true);
        status = 100;
    } else if (liveBut) {
        uint8_t realType = *reinterpret_cast<const uint8_t*>(reinterpret_cast<const uint8_t*>(liveBut) + 0x1A);
        g_lastActivatedButton.store(liveBut);
        if (realType == BUT_TYPE_TEXT && g_fn_textbutton_activate_but) {
            if (!g_fn_textbutton_activate_but(C, liveBut) && g_fn_button_activate_event) {
                g_fn_button_activate_event(C, liveRegion, liveBut);
                status = 200 + realType;
            } else {
                status = 100 + realType;
            }
        } else if (ShouldExecuteButtonDirectly(realType) && g_fn_button_execute) {
            g_fn_button_execute(C, liveRegion, liveBut);
            status = 300 + realType;
        } else if (g_fn_button_activate_event) {
            g_fn_button_activate_event(C, liveRegion, liveBut);
            status = 400 + realType;
        }
        if (g_fn_ED_region_tag_redraw) {
            g_fn_ED_region_tag_redraw(liveRegion);
        }
    }

    if (switchedWin && g_fn_CTX_wm_window_set) {
        g_fn_CTX_wm_window_set(C, prevWin);
    } else {
        if (g_fn_CTX_wm_area_set && prevArea) {
            g_fn_CTX_wm_area_set(C, prevArea);
        }
        if (g_fn_CTX_wm_region_set && prevRegion) {
            g_fn_CTX_wm_region_set(C, prevRegion);
        }
    }
    g_lastUiExecStatus.store(status);
    return status;
}

inline std::string CleanPanelText(const std::string& s) {
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
