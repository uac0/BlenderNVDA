#pragma once

#include "blender_ui_types.hpp"
#include "ui_button_query.hpp"
#include "nvda_speech.hpp"

inline LRESULT CALLBACK BlenderKeyboardProc(int code, WPARAM wParam, LPARAM lParam) {
    if (code == HC_ACTION) {
        bool isKeyDown = ((lParam & (1LL << 31)) == 0);
        if (isKeyDown) {
            bool shiftDown = (GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0;
            bool ctrlDown  = (GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0;
            bool altDown   = ((GetAsyncKeyState(VK_MENU) & 0x8000) != 0) || ((lParam & (1LL << 29)) != 0);

            // Never intercept Alt+Tab or any Alt shortcut so window switching never hangs.
            if (altDown) {
                return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
            }

            ULONGLONG now = GetTickCount64();

            bool inSearchMenu = false;
            bool inNativeMenu = false;
            bool inDialogPopup = false;
            QueryLivePopupState(inSearchMenu, inNativeMenu, inDialogPopup);

            // F1 or F5: Speak detailed native tooltip of the current button on demand.
            if ((wParam == VK_F1 || wParam == VK_F5) && !ctrlDown) {
                NvdaSpeechEngine::Instance().SpeakCurrentTooltip();
                return 1;
            }

            // F6: Switch between the 4 main Blender zones.
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
                g_hasLastFocusedButton.store(false);
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
            // Let Blender handle navigation natively while keeping the live menu alive without dropping back to 3D View!
            if (inSearchMenu || inNativeMenu) {
                if (wParam == VK_UP || wParam == VK_DOWN || wParam == VK_LEFT || wParam == VK_RIGHT ||
                    wParam == VK_PRIOR || wParam == VK_NEXT)
                {
                    if (inSearchMenu) g_lastSearchDrawTick.store(now);
                    if (inNativeMenu) g_lastMenuDrawTick.store(now);
                    NvdaSpeechEngine::Instance().CancelSpeechAndResetFocus();
                } else if (wParam == VK_RETURN) {
                    NvdaSpeechEngine::Instance().CancelSpeechAndResetFocus();
                }
                return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
            }

            // 2. If a Dialog Popup (e.g. N "Координаты От и До" or F9 Operator props) is open:
            if (inDialogPopup) {
                if (wParam == VK_RETURN || (wParam == VK_SPACE && !IsEditingTextNow() && !ctrlDown)) {
                    NvdaSpeechEngine::Instance().CancelSpeechAndResetFocus();
                    if (wParam == VK_RETURN && IsEditingTextNow()) {
                        // Commit typed value inside the active number/text box.
                        g_isEditingText.store(false);
                        return CallNextHookEx(g_keyboardHook, code, wParam, lParam);
                    } else {
                        ActivateCurrentZoneButton();
                        return 1;
                    }
                }
                if (!IsEditingTextNow() && !ctrlDown) {
                    if (wParam == VK_DOWN || wParam == VK_UP || wParam == VK_TAB) {
                        g_lastDialogDrawTick.store(now);
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
            if (wParam == VK_RETURN || (wParam == VK_SPACE && !IsEditingTextNow() && !ctrlDown)) {
                NvdaSpeechEngine::Instance().CancelSpeechAndResetFocus();
                if (wParam == VK_RETURN && IsEditingTextNow()) {
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
                                g_hasLastFocusedButton.store(false);
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
