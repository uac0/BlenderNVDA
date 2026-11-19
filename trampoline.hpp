#pragma once
#include <windows.h>
#include <cstdint>
#include <cstring>

class FunctionInterceptor {
public:
    static uint8_t* AllocateNearAddress(uintptr_t targetAddr) {
        SYSTEM_INFO sysInfo{};
        GetSystemInfo(&sysInfo);
        uintptr_t gran = sysInfo.dwAllocationGranularity ? sysInfo.dwAllocationGranularity : 0x10000;
        uintptr_t minAddr = (targetAddr > 0x70000000ULL) ? (targetAddr - 0x70000000ULL) : 0x10000ULL;
        uintptr_t maxAddr = targetAddr + 0x70000000ULL;

        for (uintptr_t addr = (targetAddr & ~(gran - 1)); addr >= minAddr; addr -= gran) {
            MEMORY_BASIC_INFORMATION mbi{};
            if (VirtualQuery(reinterpret_cast<LPCVOID>(addr), &mbi, sizeof(mbi)) == 0) break;
            if (mbi.State == MEM_FREE && mbi.RegionSize >= 4096) {
                uintptr_t candidate = (reinterpret_cast<uintptr_t>(mbi.BaseAddress) + gran - 1) & ~(gran - 1);
                void* mem = VirtualAlloc(reinterpret_cast<LPVOID>(candidate), 4096, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
                if (mem) return reinterpret_cast<uint8_t*>(mem);
            }
        }
        for (uintptr_t addr = (targetAddr & ~(gran - 1)) + gran; addr < maxAddr; addr += gran) {
            MEMORY_BASIC_INFORMATION mbi{};
            if (VirtualQuery(reinterpret_cast<LPCVOID>(addr), &mbi, sizeof(mbi)) == 0) break;
            if (mbi.State == MEM_FREE && mbi.RegionSize >= 4096) {
                uintptr_t candidate = (reinterpret_cast<uintptr_t>(mbi.BaseAddress) + gran - 1) & ~(gran - 1);
                void* mem = VirtualAlloc(reinterpret_cast<LPVOID>(candidate), 4096, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
                if (mem) return reinterpret_cast<uint8_t*>(mem);
            }
        }
        return nullptr;
    }

    // Calculate length of initial prologue instructions (>= 5 bytes)
    static size_t GetPrologueInstructionBoundary(const uint8_t* code, size_t minBytes = 5) {
        size_t offset = 0;
        while (offset < minBytes) {
            size_t len = DecodeSinglePrologueInst(code + offset);
            if (len == 0) return 0;
            offset += len;
        }
        return offset;
    }

    static bool InstallDetour(
        uintptr_t targetFunc,
        uintptr_t detourFunc,
        uint8_t*& arenaCursor,
        void** outOriginalTrampoline)
    {
        if (!targetFunc || !detourFunc || !arenaCursor || !outOriginalTrampoline) return false;

        const uint8_t* src = reinterpret_cast<const uint8_t*>(targetFunc);
        size_t stolenLen = GetPrologueInstructionBoundary(src, 5);
        if (stolenLen < 5 || stolenLen > 16) return false;

        // Layout in nearby executable arena:
        // [0 .. stolenLen-1]: copied prologue instructions
        // [stolenLen .. stolenLen+13]: 64-bit jump back to (targetFunc + stolenLen)
        // [stolenLen+16 .. stolenLen+29]: 64-bit relay jump to detourFunc
        uint8_t* trampoline = arenaCursor;
        uint8_t* relayStub = arenaCursor + 32;

        // Verify relative distance from targetFunc to relayStub fits in signed 32-bit int
        intptr_t relToRelay = reinterpret_cast<intptr_t>(relayStub) - static_cast<intptr_t>(targetFunc + 5);
        if (relToRelay < INT32_MIN || relToRelay > INT32_MAX) return false;

        // 1. Copy prologue bytes to trampoline
        std::memcpy(trampoline, src, stolenLen);

        // 2. Write jump from trampoline back to targetFunc + stolenLen
        uint8_t* jmpBack = trampoline + stolenLen;
        jmpBack[0] = 0xFF;
        jmpBack[1] = 0x25;
        *reinterpret_cast<uint32_t*>(jmpBack + 2) = 0;
        *reinterpret_cast<uint64_t*>(jmpBack + 6) = static_cast<uint64_t>(targetFunc + stolenLen);

        // 3. Write relay stub jumping to detourFunc
        relayStub[0] = 0xFF;
        relayStub[1] = 0x25;
        *reinterpret_cast<uint32_t*>(relayStub + 2) = 0;
        *reinterpret_cast<uint64_t*>(relayStub + 6) = static_cast<uint64_t>(detourFunc);

        // 4. Patch targetFunc entry with 5-byte relative jump to relayStub
        DWORD oldProtect = 0;
        if (!VirtualProtect(reinterpret_cast<LPVOID>(targetFunc), stolenLen, PAGE_EXECUTE_READWRITE, &oldProtect)) {
            return false;
        }

        uint8_t patch[16];
        patch[0] = 0xE9;
        *reinterpret_cast<int32_t*>(patch + 1) = static_cast<int32_t>(relToRelay);
        for (size_t i = 5; i < stolenLen; ++i) {
            patch[i] = 0x90; // NOP padding
        }
        std::memcpy(reinterpret_cast<void*>(targetFunc), patch, stolenLen);

        DWORD dummy = 0;
        VirtualProtect(reinterpret_cast<LPVOID>(targetFunc), stolenLen, oldProtect, &dummy);
        FlushInstructionCache(GetCurrentProcess(), reinterpret_cast<LPCVOID>(targetFunc), stolenLen);

        *outOriginalTrampoline = reinterpret_cast<void*>(trampoline);
        arenaCursor += 64;
        return true;
    }

private:
    static size_t DecodeSinglePrologueInst(const uint8_t* p) {
        size_t i = 0;
        // REX prefix (0x40 - 0x4F)
        if (p[i] >= 0x40 && p[i] <= 0x4F) {
            ++i;
        }
        uint8_t op = p[i++];
        // PUSH r64 / POP r64 (0x50 - 0x5F)
        if (op >= 0x50 && op <= 0x5F) {
            return i;
        }
        // SUB/ADD/CMP r/m64, imm8 (0x83 /modrm imm8)
        if (op == 0x83) {
            uint8_t modrm = p[i++];
            uint8_t mod = (modrm >> 6) & 3;
            uint8_t rm = modrm & 7;
            if (mod != 3 && rm == 4) ++i; // SIB byte
            if (mod == 1) i += 1;
            else if (mod == 2) i += 4;
            return i + 1; // + imm8
        }
        // SUB/ADD r/m64, imm32 (0x81 /modrm imm32)
        if (op == 0x81) {
            uint8_t modrm = p[i++];
            uint8_t mod = (modrm >> 6) & 3;
            uint8_t rm = modrm & 7;
            if (mod != 3 && rm == 4) ++i;
            if (mod == 1) i += 1;
            else if (mod == 2) i += 4;
            return i + 4; // + imm32
        }
        // MOV r/m64, r64 or r64, r/m64 or TEST r/m64, r64 or XOR (0x89, 0x8B, 0x85, 0x31, 0x33)
        if (op == 0x89 || op == 0x8B || op == 0x85 || op == 0x31 || op == 0x33) {
            uint8_t modrm = p[i++];
            uint8_t mod = (modrm >> 6) & 3;
            uint8_t rm = modrm & 7;
            if (mod != 3 && rm == 4) ++i; // SIB
            if (mod == 1) i += 1;
            else if (mod == 2) i += 4;
            else if (mod == 0 && rm == 5) return 0; // RIP-relative not supported in simple prologue
            return i;
        }
        return 0;
    }
};
