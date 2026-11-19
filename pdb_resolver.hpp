#pragma once
#include <windows.h>
#include <string>
#include <vector>
#include <cstring>
#include <cstdint>

struct ResolvedBlenderSymbols {
    uintptr_t fn_BLF_draw = 0;
    uintptr_t fn_BLF_draw_mono = 0;
    uintptr_t fn_draw_button = 0;
    uintptr_t fn_draw_menu_item = 0;
    uintptr_t fn_button_activate_over = 0;
    uintptr_t fn_button_string_get_label = 0;
    uintptr_t fn_button_string_get_rna_label = 0;
    uintptr_t fn_button_string_get_tooltip_label = 0;
    uintptr_t fn_button_string_get_tooltip = 0;
    uintptr_t fn_button_rna_enum_item_get = 0;
    uintptr_t fn_RNA_property_ui_name = 0;
    uintptr_t fn_RNA_property_ui_description = 0;
    uintptr_t fn_RNA_property_array_check = 0;
    uintptr_t fn_RNA_property_array_item_char = 0;
    uintptr_t fn_block_is_popup_any = 0;
    uintptr_t fn_block_is_menu = 0;
    uintptr_t fn_CTX_wm_region_popup = 0;
    uintptr_t fn_CTX_wm_area = 0;
    uintptr_t fn_CTX_wm_window = 0;
    uintptr_t fn_draw_aligned_panel = 0;
    uintptr_t fn_file_draw_list = 0;
    uintptr_t fn_button_to_pixelrect = 0;
    uintptr_t fn_button_string_get = 0;
};

class BlenderSymbolResolver {
public:
    static bool ResolveFromPdb(
        HMODULE hExeModule,
        const std::wstring& pdbPath,
        ResolvedBlenderSymbols& outSyms,
        const std::wstring& cachePath = L"")
    {
        if (!hExeModule) return false;
        uintptr_t baseAddr = reinterpret_cast<uintptr_t>(hExeModule);

        // Read blender.exe file metadata for cache validation
        uint64_t exeSize = 0;
        uint64_t exeWriteTime = 0;
        wchar_t exePathBuf[MAX_PATH * 2] = {0};
        if (GetModuleFileNameW(hExeModule, exePathBuf, MAX_PATH * 2) > 0) {
            WIN32_FILE_ATTRIBUTE_DATA fad{};
            if (GetFileAttributesExW(exePathBuf, GetFileExInfoStandard, &fad)) {
                exeSize = (static_cast<uint64_t>(fad.nFileSizeHigh) << 32) | fad.nFileSizeLow;
                exeWriteTime = (static_cast<uint64_t>(fad.ftLastWriteTime.dwHighDateTime) << 32) |
                               fad.ftLastWriteTime.dwLowDateTime;
            }
        }

        if (!cachePath.empty() && LoadCache(cachePath, exeSize, exeWriteTime, baseAddr, outSyms)) {
            return true;
        }

        // Read PE section RVAs from the loaded blender.exe image
        auto* dosHdr = reinterpret_cast<const IMAGE_DOS_HEADER*>(baseAddr);
        if (dosHdr->e_magic != IMAGE_DOS_SIGNATURE) return false;
        auto* ntHdr = reinterpret_cast<const IMAGE_NT_HEADERS64*>(baseAddr + dosHdr->e_lfanew);
        if (ntHdr->Signature != IMAGE_NT_SIGNATURE) return false;

        WORD numSections = ntHdr->FileHeader.NumberOfSections;
        const IMAGE_SECTION_HEADER* secHdr = IMAGE_FIRST_SECTION(ntHdr);
        std::vector<uint32_t> sectionRvas(numSections + 1, 0);
        for (WORD i = 0; i < numSections; ++i) {
            sectionRvas[i + 1] = secHdr[i].VirtualAddress;
        }

        // Open blender.pdb via memory-mapped view for fast single-pass scanning
        HANDLE hFile = CreateFileW(pdbPath.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (hFile == INVALID_HANDLE_VALUE) return false;

        LARGE_INTEGER fileSize{};
        if (!GetFileSizeEx(hFile, &fileSize) || fileSize.QuadPart < 1024) {
            CloseHandle(hFile);
            return false;
        }

        HANDLE hMap = CreateFileMappingW(hFile, nullptr, PAGE_READONLY, 0, 0, nullptr);
        if (!hMap) {
            CloseHandle(hFile);
            return false;
        }

        const uint8_t* pdbBytes = reinterpret_cast<const uint8_t*>(MapViewOfFile(hMap, FILE_MAP_READ, 0, 0, 0));
        if (!pdbBytes) {
            CloseHandle(hMap);
            CloseHandle(hFile);
            return false;
        }

        size_t pdbLen = static_cast<size_t>(fileSize.QuadPart);

        struct SymTarget {
            const char* prefix;
            size_t prefixLen;
            uintptr_t ResolvedBlenderSymbols::* member;
            bool found;
        };

        SymTarget targets[] = {
            {"?BLF_draw@blender@@", 0, &ResolvedBlenderSymbols::fn_BLF_draw, false},
            {"?BLF_draw_mono@blender@@", 0, &ResolvedBlenderSymbols::fn_BLF_draw_mono, false},
            {"?draw_button@ui@blender@@", 0, &ResolvedBlenderSymbols::fn_draw_button, false},
            {"?draw_menu_item@ui@blender@@", 0, &ResolvedBlenderSymbols::fn_draw_menu_item, false},
            {"?button_activate_over@ui@blender@@", 0, &ResolvedBlenderSymbols::fn_button_activate_over, false},
            {"?button_string_get_label@ui@blender@@", 0, &ResolvedBlenderSymbols::fn_button_string_get_label, false},
            {"?button_string_get_rna_label@ui@blender@@", 0, &ResolvedBlenderSymbols::fn_button_string_get_rna_label, false},
            {"?button_string_get_tooltip_label@ui@blender@@", 0, &ResolvedBlenderSymbols::fn_button_string_get_tooltip_label, false},
            {"?button_string_get_tooltip@ui@blender@@", 0, &ResolvedBlenderSymbols::fn_button_string_get_tooltip, false},
            {"?button_rna_enum_item_get@ui@blender@@", 0, &ResolvedBlenderSymbols::fn_button_rna_enum_item_get, false},
            {"?RNA_property_ui_name@blender@@", 0, &ResolvedBlenderSymbols::fn_RNA_property_ui_name, false},
            {"?RNA_property_ui_description@blender@@", 0, &ResolvedBlenderSymbols::fn_RNA_property_ui_description, false},
            {"?RNA_property_array_check@blender@@", 0, &ResolvedBlenderSymbols::fn_RNA_property_array_check, false},
            {"?RNA_property_array_item_char@blender@@", 0, &ResolvedBlenderSymbols::fn_RNA_property_array_item_char, false},
            {"?block_is_popup_any@ui@blender@@", 0, &ResolvedBlenderSymbols::fn_block_is_popup_any, false},
            {"?block_is_menu@ui@blender@@", 0, &ResolvedBlenderSymbols::fn_block_is_menu, false},
            {"?CTX_wm_region_popup@blender@@", 0, &ResolvedBlenderSymbols::fn_CTX_wm_region_popup, false},
            {"?CTX_wm_area@blender@@", 0, &ResolvedBlenderSymbols::fn_CTX_wm_area, false},
            {"?CTX_wm_window@blender@@", 0, &ResolvedBlenderSymbols::fn_CTX_wm_window, false},
            {"?draw_aligned_panel@ui@blender@@", 0, &ResolvedBlenderSymbols::fn_draw_aligned_panel, false},
            {"?file_draw_list@blender@@", 0, &ResolvedBlenderSymbols::fn_file_draw_list, false},
            {"?button_to_pixelrect@ui@blender@@", 0, &ResolvedBlenderSymbols::fn_button_to_pixelrect, false},
            {"?button_string_get@ui@blender@@YAXPEAUButton", 0, &ResolvedBlenderSymbols::fn_button_string_get, false},
        };

        constexpr size_t kNumTargets = sizeof(targets) / sizeof(targets[0]);
        for (size_t i = 0; i < kNumTargets; ++i) {
            targets[i].prefixLen = std::strlen(targets[i].prefix);
        }

        size_t remaining = kNumTargets;
        if (pdbLen > sizeof(PubSym32Prefix) + 48) {
            size_t limit = pdbLen - 48;
            for (size_t pos = sizeof(PubSym32Prefix); pos < limit && remaining > 0; ) {
                const void* found = std::memchr(pdbBytes + pos, '?', limit - pos);
                if (!found) break;
                pos = static_cast<size_t>(reinterpret_cast<const uint8_t*>(found) - pdbBytes);
                const auto* hdr = reinterpret_cast<const PubSym32Prefix*>(pdbBytes + pos - sizeof(PubSym32Prefix));
                if (hdr->rectype == 0x110e && hdr->segment >= 1 && hdr->segment < sectionRvas.size()) {
                    for (size_t i = 0; i < kNumTargets; ++i) {
                        if (!targets[i].found && (pos + targets[i].prefixLen <= pdbLen) &&
                            std::memcmp(pdbBytes + pos, targets[i].prefix, targets[i].prefixLen) == 0) {
                            uint32_t rva = sectionRvas[hdr->segment] + hdr->offset;
                            outSyms.*(targets[i].member) = baseAddr + rva;
                            targets[i].found = true;
                            --remaining;
                            break;
                        }
                    }
                }
                ++pos;
            }
        }

        UnmapViewOfFile(pdbBytes);
        CloseHandle(hMap);
        CloseHandle(hFile);

        bool ok = (outSyms.fn_BLF_draw != 0 && outSyms.fn_draw_button != 0);
        if (ok && !cachePath.empty()) {
            SaveCache(cachePath, exeSize, exeWriteTime, baseAddr, outSyms);
        }
        return ok;
    }

private:
#pragma pack(push, 1)
    struct PubSym32Prefix {
        uint16_t rectype;
        uint32_t pubsymflags;
        uint32_t offset;
        uint16_t segment;
    };

    struct CachedSymbolRvas {
        uint32_t magic;
        uint32_t version;
        uint64_t exeSize;
        uint64_t exeWriteTime;
        uint64_t rvas[23];
    };
#pragma pack(pop)

    static constexpr uint32_t kCacheMagic = 0x424E5632; // 'BNV2'
    static constexpr uint32_t kCacheVersion = 1;

    static void PackRvas(uintptr_t baseAddr, const ResolvedBlenderSymbols& s, uint64_t (&out)[23]) {
        const uintptr_t ptrs[23] = {
            s.fn_BLF_draw, s.fn_BLF_draw_mono, s.fn_draw_button, s.fn_draw_menu_item, s.fn_button_activate_over,
            s.fn_button_string_get_label, s.fn_button_string_get_rna_label, s.fn_button_string_get_tooltip_label,
            s.fn_button_string_get_tooltip, s.fn_button_rna_enum_item_get, s.fn_RNA_property_ui_name,
            s.fn_RNA_property_ui_description, s.fn_RNA_property_array_check, s.fn_RNA_property_array_item_char,
            s.fn_block_is_popup_any, s.fn_block_is_menu, s.fn_CTX_wm_region_popup, s.fn_CTX_wm_area,
            s.fn_CTX_wm_window, s.fn_draw_aligned_panel, s.fn_file_draw_list, s.fn_button_to_pixelrect,
            s.fn_button_string_get
        };
        for (int i = 0; i < 23; ++i) {
            out[i] = (ptrs[i] >= baseAddr && ptrs[i] != 0) ? static_cast<uint64_t>(ptrs[i] - baseAddr) : 0ULL;
        }
    }

    static void UnpackRvas(uintptr_t baseAddr, const uint64_t (&in)[23], ResolvedBlenderSymbols& s) {
        auto toAddr = [baseAddr](uint64_t rva) -> uintptr_t { return rva ? (baseAddr + static_cast<uintptr_t>(rva)) : 0; };
        s.fn_BLF_draw = toAddr(in[0]);
        s.fn_BLF_draw_mono = toAddr(in[1]);
        s.fn_draw_button = toAddr(in[2]);
        s.fn_draw_menu_item = toAddr(in[3]);
        s.fn_button_activate_over = toAddr(in[4]);
        s.fn_button_string_get_label = toAddr(in[5]);
        s.fn_button_string_get_rna_label = toAddr(in[6]);
        s.fn_button_string_get_tooltip_label = toAddr(in[7]);
        s.fn_button_string_get_tooltip = toAddr(in[8]);
        s.fn_button_rna_enum_item_get = toAddr(in[9]);
        s.fn_RNA_property_ui_name = toAddr(in[10]);
        s.fn_RNA_property_ui_description = toAddr(in[11]);
        s.fn_RNA_property_array_check = toAddr(in[12]);
        s.fn_RNA_property_array_item_char = toAddr(in[13]);
        s.fn_block_is_popup_any = toAddr(in[14]);
        s.fn_block_is_menu = toAddr(in[15]);
        s.fn_CTX_wm_region_popup = toAddr(in[16]);
        s.fn_CTX_wm_area = toAddr(in[17]);
        s.fn_CTX_wm_window = toAddr(in[18]);
        s.fn_draw_aligned_panel = toAddr(in[19]);
        s.fn_file_draw_list = toAddr(in[20]);
        s.fn_button_to_pixelrect = toAddr(in[21]);
        s.fn_button_string_get = toAddr(in[22]);
    }

    static bool LoadCache(const std::wstring& cachePath, uint64_t exeSize, uint64_t exeWriteTime, uintptr_t baseAddr, ResolvedBlenderSymbols& outSyms) {
        HANDLE hFile = CreateFileW(cachePath.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (hFile == INVALID_HANDLE_VALUE) return false;
        CachedSymbolRvas data{};
        DWORD bytesRead = 0;
        BOOL ok = ReadFile(hFile, &data, sizeof(data), &bytesRead, nullptr);
        CloseHandle(hFile);
        if (!ok || bytesRead != sizeof(data)) return false;
        if (data.magic != kCacheMagic || data.version != kCacheVersion) return false;
        if (exeSize != 0 && (data.exeSize != exeSize || data.exeWriteTime != exeWriteTime)) return false;
        if (data.rvas[0] == 0 || data.rvas[2] == 0) return false;
        UnpackRvas(baseAddr, data.rvas, outSyms);
        return true;
    }

    static void SaveCache(const std::wstring& cachePath, uint64_t exeSize, uint64_t exeWriteTime, uintptr_t baseAddr, const ResolvedBlenderSymbols& syms) {
        CachedSymbolRvas data{};
        data.magic = kCacheMagic;
        data.version = kCacheVersion;
        data.exeSize = exeSize;
        data.exeWriteTime = exeWriteTime;
        PackRvas(baseAddr, syms, data.rvas);
        HANDLE hFile = CreateFileW(cachePath.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (hFile != INVALID_HANDLE_VALUE) {
            DWORD written = 0;
            WriteFile(hFile, &data, sizeof(data), &written, nullptr);
            CloseHandle(hFile);
        }
    }
};
