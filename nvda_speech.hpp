#pragma once
#include <windows.h>
#include <string>
#include <unordered_map>
#include <mutex>
#include <chrono>
#include <cmath>
#include <cstdio>

typedef unsigned long (__stdcall *pfn_nvdaController_speakText)(const wchar_t *text);
typedef unsigned long (__stdcall *pfn_nvdaController_cancelSpeech)(void);
typedef unsigned long (__stdcall *pfn_nvdaController_testIfRunning)(void);

class NvdaSpeechEngine {
public:
    static NvdaSpeechEngine& Instance() {
        static NvdaSpeechEngine inst;
        return inst;
    }

    bool Initialize(const std::wstring& dllDir) {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_hNvda) return true;

        std::wstring fullPath = dllDir + L"\\nvdaControllerClient64.dll";
        m_hNvda = LoadLibraryW(fullPath.c_str());
        if (!m_hNvda) {
            m_hNvda = LoadLibraryW(L"nvdaControllerClient64.dll");
        }
        if (!m_hNvda) return false;

        m_speakText = reinterpret_cast<pfn_nvdaController_speakText>(
            GetProcAddress(m_hNvda, "nvdaController_speakText"));
        m_cancelSpeech = reinterpret_cast<pfn_nvdaController_cancelSpeech>(
            GetProcAddress(m_hNvda, "nvdaController_cancelSpeech"));
        m_testIfRunning = reinterpret_cast<pfn_nvdaController_testIfRunning>(
            GetProcAddress(m_hNvda, "nvdaController_testIfRunning"));

        m_startupTime = GetTickCount64();
        return (m_speakText != nullptr && m_cancelSpeech != nullptr);
    }

    void CancelSpeechAndResetFocus() {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_cancelSpeech) {
            m_cancelSpeech();
        }
        m_lastFocusedText.clear();
        m_lastFocusedWidgetId = 0;
    }

    void ClearTooltipBuffer() {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_tooltipLines.clear();
    }

    void SetCurrentButtonTooltip(const std::string& utf8Tip) {
        std::string cleaned = CleanText(utf8Tip);
        if (cleaned.empty()) return;
        std::lock_guard<std::mutex> lock(m_mutex);
        m_tooltipLines = cleaned;
    }

    void AppendTooltipFragment(const std::string& utf8Text) {
        std::string cleaned = CleanText(utf8Text);
        if (cleaned.empty() || IsIgnorableFragment(cleaned)) return;

        std::lock_guard<std::mutex> lock(m_mutex);
        if (cleaned == m_lastFocusedText) return;
        if (m_tooltipLines.find(cleaned) != std::string::npos) return;
        if (!m_tooltipLines.empty()) {
            m_tooltipLines += ". ";
        }
        m_tooltipLines += cleaned;
    }

    void SpeakCurrentTooltip() {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_speakText) return;
        if (m_cancelSpeech) {
            m_cancelSpeech();
        }
        std::string toSpeak;
        if (!m_lastFocusedText.empty() && !m_tooltipLines.empty()) {
            if (m_tooltipLines.find(m_lastFocusedText) == 0) {
                toSpeak = m_tooltipLines;
            } else {
                toSpeak = m_lastFocusedText + ". " + m_tooltipLines;
            }
        } else if (!m_tooltipLines.empty()) {
            toSpeak = m_tooltipLines;
        } else {
            toSpeak = m_lastFocusedText;
        }
        if (toSpeak.empty()) return;
        std::wstring wide = Utf8ToWide(toSpeak);
        if (!wide.empty()) {
            m_speakText(wide.c_str());
        }
    }

    void SpeakDirect(const std::string& utf8Text, bool interrupt = true) {
        std::string cleaned = CleanText(utf8Text);
        if (cleaned.empty()) return;
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_speakText) return;
        if (interrupt && m_cancelSpeech) {
            m_cancelSpeech();
        }
        m_spokenCache[cleaned] = GetTickCount64();
        std::wstring wide = Utf8ToWide(cleaned);
        if (!wide.empty()) {
            m_speakText(wide.c_str());
        }
    }

    // Speak focused/active widget immediately, interrupting previous speech if focus changed
    void SpeakFocusedItem(uintptr_t widgetId, const std::string& utf8Text, bool forceInterrupt = false) {
        if (utf8Text.empty()) return;
        std::string cleaned = CleanText(utf8Text);
        if (cleaned.empty()) return;

        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_speakText) return;

        ULONGLONG now = GetTickCount64();
        if (!forceInterrupt && widgetId == m_lastFocusedWidgetId && cleaned == m_lastFocusedText) {
            if (now - m_lastFocusedTime < 120000ULL) {
                return;
            }
        }

        if (widgetId != m_lastFocusedWidgetId) {
            m_tooltipLines.clear();
        }

        m_lastFocusedWidgetId = widgetId;
        m_lastFocusedText = cleaned;
        m_lastFocusedTime = now;
        m_spokenCache[cleaned] = now;

        if (m_cancelSpeech) {
            m_cancelSpeech();
        }
        std::wstring wide = Utf8ToWide(cleaned);
        if (!wide.empty()) {
            m_speakText(wide.c_str());
        }
    }

    // Register static background text so initial screen redraw doesn't spam NVDA
    void RegisterBackgroundText(const std::string& utf8Text) {
        std::string cleaned = CleanText(utf8Text);
        if (cleaned.empty()) return;
        std::lock_guard<std::mutex> lock(m_mutex);
        m_spokenCache[cleaned] = GetTickCount64();
    }

    // Speak dynamic screen text with 120-second deduplication cache
    void SpeakScreenTextFiltered(const std::string& utf8Text, bool interrupt = false) {
        if (utf8Text.empty()) return;
        std::string cleaned = CleanText(utf8Text);
        if (cleaned.empty() || IsIgnorableFragment(cleaned)) return;

        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_speakText) return;

        ULONGLONG now = GetTickCount64();
        PruneExpiredLocked(now);

        if (now - m_startupTime < 1500ULL) {
            m_spokenCache[cleaned] = now;
            return;
        }

        auto it = m_spokenCache.find(cleaned);
        if (it != m_spokenCache.end()) {
            if (now - it->second < 120000ULL) {
                return;
            }
        }

        m_spokenCache[cleaned] = now;
        if (interrupt && m_cancelSpeech) {
            m_cancelSpeech();
        }
        std::wstring wide = Utf8ToWide(cleaned);
        if (!wide.empty()) {
            m_speakText(wide.c_str());
        }
    }

private:
    NvdaSpeechEngine() = default;

    void PruneExpiredLocked(ULONGLONG now) {
        if (now - m_lastPruneTime < 10000ULL) return;
        m_lastPruneTime = now;
        for (auto it = m_spokenCache.begin(); it != m_spokenCache.end(); ) {
            if (now - it->second >= 120000ULL) {
                it = m_spokenCache.erase(it);
            } else {
                ++it;
            }
        }
    }

    static std::string CleanText(const std::string& s) {
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

    static bool IsIgnorableFragment(const std::string& s) {
        if (s.size() == 1) {
            char c = s[0];
            if (c == ':' || c == '.' || c == ',' || c == '-' || c == '+' || c == '/' || c == '>' || c == '_')
                return true;
        }
        return false;
    }

    static std::wstring Utf8ToWide(const std::string& utf8) {
        if (utf8.empty()) return std::wstring();
        int len = MultiByteToWideChar(CP_UTF8, 0, utf8.data(), static_cast<int>(utf8.size()), nullptr, 0);
        if (len <= 0) return std::wstring();
        std::wstring wide(len, L'\0');
        MultiByteToWideChar(CP_UTF8, 0, utf8.data(), static_cast<int>(utf8.size()), &wide[0], len);
        return wide;
    }

    std::mutex m_mutex;
    HMODULE m_hNvda = nullptr;
    pfn_nvdaController_speakText m_speakText = nullptr;
    pfn_nvdaController_cancelSpeech m_cancelSpeech = nullptr;
    pfn_nvdaController_testIfRunning m_testIfRunning = nullptr;

    ULONGLONG m_startupTime = 0;
    ULONGLONG m_lastPruneTime = 0;
    uintptr_t m_lastFocusedWidgetId = 0;
    std::string m_lastFocusedText;
    std::string m_tooltipLines;
    ULONGLONG m_lastFocusedTime = 0;
    std::unordered_map<std::string, ULONGLONG> m_spokenCache;
};
