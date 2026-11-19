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
};

class BlenderSymbolResolver {
public:
    static bool ResolveFromPdb(HMODULE hExeModule, const std::wstring& pdbPath, ResolvedBlenderSymbols& outSyms) {
        if (!hExeModule) return false;
        uintptr_t baseAddr = reinterpret_cast<uintptr_t>(hExeModule);

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

        // Open blender.pdb via memory-mapped view for fast scanning
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
        outSyms.fn_BLF_draw = FindPubSymAddress(pdbBytes, pdbLen, "?BLF_draw@blender@@", sectionRvas, baseAddr);
        outSyms.fn_BLF_draw_mono = FindPubSymAddress(pdbBytes, pdbLen, "?BLF_draw_mono@blender@@", sectionRvas, baseAddr);
        outSyms.fn_draw_button = FindPubSymAddress(pdbBytes, pdbLen, "?draw_button@ui@blender@@", sectionRvas, baseAddr);
        outSyms.fn_draw_menu_item = FindPubSymAddress(pdbBytes, pdbLen, "?draw_menu_item@ui@blender@@", sectionRvas, baseAddr);
        outSyms.fn_button_activate_over = FindPubSymAddress(pdbBytes, pdbLen, "?button_activate_over@ui@blender@@", sectionRvas, baseAddr);

        outSyms.fn_button_string_get_label = FindPubSymAddress(pdbBytes, pdbLen, "?button_string_get_label@ui@blender@@", sectionRvas, baseAddr);
        outSyms.fn_button_string_get_rna_label = FindPubSymAddress(pdbBytes, pdbLen, "?button_string_get_rna_label@ui@blender@@", sectionRvas, baseAddr);
        outSyms.fn_button_string_get_tooltip_label = FindPubSymAddress(pdbBytes, pdbLen, "?button_string_get_tooltip_label@ui@blender@@", sectionRvas, baseAddr);
        outSyms.fn_button_string_get_tooltip = FindPubSymAddress(pdbBytes, pdbLen, "?button_string_get_tooltip@ui@blender@@", sectionRvas, baseAddr);
        outSyms.fn_button_rna_enum_item_get = FindPubSymAddress(pdbBytes, pdbLen, "?button_rna_enum_item_get@ui@blender@@", sectionRvas, baseAddr);
        outSyms.fn_RNA_property_ui_name = FindPubSymAddress(pdbBytes, pdbLen, "?RNA_property_ui_name@blender@@", sectionRvas, baseAddr);
        outSyms.fn_RNA_property_ui_description = FindPubSymAddress(pdbBytes, pdbLen, "?RNA_property_ui_description@blender@@", sectionRvas, baseAddr);
        outSyms.fn_RNA_property_array_check = FindPubSymAddress(pdbBytes, pdbLen, "?RNA_property_array_check@blender@@", sectionRvas, baseAddr);
        outSyms.fn_RNA_property_array_item_char = FindPubSymAddress(pdbBytes, pdbLen, "?RNA_property_array_item_char@blender@@", sectionRvas, baseAddr);
        outSyms.fn_block_is_popup_any = FindPubSymAddress(pdbBytes, pdbLen, "?block_is_popup_any@ui@blender@@", sectionRvas, baseAddr);
        outSyms.fn_block_is_menu = FindPubSymAddress(pdbBytes, pdbLen, "?block_is_menu@ui@blender@@", sectionRvas, baseAddr);
        outSyms.fn_CTX_wm_region_popup = FindPubSymAddress(pdbBytes, pdbLen, "?CTX_wm_region_popup@blender@@", sectionRvas, baseAddr);
        outSyms.fn_CTX_wm_area = FindPubSymAddress(pdbBytes, pdbLen, "?CTX_wm_area@blender@@", sectionRvas, baseAddr);

        UnmapViewOfFile(pdbBytes);
        CloseHandle(hMap);
        CloseHandle(hFile);

        return (outSyms.fn_BLF_draw != 0 && outSyms.fn_draw_button != 0);
    }

private:
#pragma pack(push, 1)
    struct PubSym32Prefix {
        uint16_t rectype;
        uint32_t pubsymflags;
        uint32_t offset;
        uint16_t segment;
    };
#pragma pack(pop)

    static uintptr_t FindPubSymAddress(
        const uint8_t* data,
        size_t dataLen,
        const char* symbolPrefix,
        const std::vector<uint32_t>& sectionRvas,
        uintptr_t moduleBase)
    {
        size_t prefixLen = std::strlen(symbolPrefix);
        if (prefixLen == 0 || dataLen < prefixLen + sizeof(PubSym32Prefix)) return 0;

        const uint8_t firstByte = static_cast<uint8_t>(symbolPrefix[0]);
        size_t limit = dataLen - prefixLen;

        for (size_t pos = sizeof(PubSym32Prefix); pos < limit; ) {
            const void* found = std::memchr(data + pos, firstByte, limit - pos);
            if (!found) break;
            pos = static_cast<size_t>(reinterpret_cast<const uint8_t*>(found) - data);
            if (std::memcmp(data + pos, symbolPrefix, prefixLen) == 0) {
                const auto* hdr = reinterpret_cast<const PubSym32Prefix*>(data + pos - sizeof(PubSym32Prefix));
                if (hdr->rectype == 0x110e && hdr->segment >= 1 && hdr->segment < sectionRvas.size()) {
                    uint32_t rva = sectionRvas[hdr->segment] + hdr->offset;
                    return moduleBase + rva;
                }
            }
            ++pos;
        }
        return 0;
    }
};
