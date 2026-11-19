#include <windows.h>
#include <shlobj.h>
#include <string>
#include <vector>
#include <cstdio>
#include "pdb_resolver.hpp"

static std::wstring GetExeDir() {
    wchar_t buf[MAX_PATH * 2] = {0};
    DWORD len = GetModuleFileNameW(nullptr, buf, MAX_PATH * 2);
    if (len == 0) return L".";
    std::wstring full(buf, len);
    size_t pos = full.find_last_of(L"\\/");
    return (pos != std::wstring::npos) ? full.substr(0, pos) : L".";
}

static bool FileExistsW(const std::wstring& path) {
    DWORD attr = GetFileAttributesW(path.c_str());
    return (attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY));
}

static bool DirExistsW(const std::wstring& path) {
    DWORD attr = GetFileAttributesW(path.c_str());
    return (attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY));
}

static void EnsureDirRecursive(const std::wstring& path) {
    size_t pos = 0;
    while ((pos = path.find_first_of(L"\\/", pos + 1)) != std::wstring::npos) {
        std::wstring sub = path.substr(0, pos);
        if (!sub.empty() && sub.back() != L':') {
            CreateDirectoryW(sub.c_str(), nullptr);
        }
    }
    CreateDirectoryW(path.c_str(), nullptr);
}

static void RemovePycacheDir(const std::wstring& parentDir) {
    std::wstring cacheDir = parentDir + L"\\__pycache__";
    if (!DirExistsW(cacheDir)) return;
    WIN32_FIND_DATAW fd{};
    std::wstring pattern = cacheDir + L"\\*";
    HANDLE hFind = FindFirstFileW(pattern.c_str(), &fd);
    if (hFind != INVALID_HANDLE_VALUE) {
        do {
            if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
                DeleteFileW((cacheDir + L"\\" + fd.cFileName).c_str());
            }
        } while (FindNextFileW(hFind, &fd));
        FindClose(hFind);
    }
    RemoveDirectoryW(cacheDir.c_str());
}

static std::vector<std::wstring> FindInstalledBlenders() {
    std::vector<std::wstring> results;
    const wchar_t* roots[] = {
        L"C:\\Program Files\\Blender Foundation",
        L"D:\\Program Files\\Blender Foundation",
        L"E:\\Program Files\\Blender Foundation"
    };

    for (const wchar_t* root : roots) {
        if (!DirExistsW(root)) continue;
        std::wstring searchPattern = std::wstring(root) + L"\\Blender*";
        WIN32_FIND_DATAW fd{};
        HANDLE hFind = FindFirstFileW(searchPattern.c_str(), &fd);
        if (hFind != INVALID_HANDLE_VALUE) {
            do {
                if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
                    std::wstring dir = std::wstring(root) + L"\\" + fd.cFileName;
                    std::wstring exe = dir + L"\\blender.exe";
                    if (FileExistsW(exe)) {
                        results.push_back(dir);
                    }
                }
            } while (FindNextFileW(hFind, &fd));
            FindClose(hFind);
        }
    }
    return results;
}

static std::vector<std::wstring> FindBlenderVersionSubdirs(const std::wstring& blenderDir) {
    std::vector<std::wstring> versions;
    std::wstring pattern = blenderDir + L"\\*";
    WIN32_FIND_DATAW fd{};
    HANDLE hFind = FindFirstFileW(pattern.c_str(), &fd);
    if (hFind != INVALID_HANDLE_VALUE) {
        do {
            if ((fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && fd.cFileName[0] >= L'0' && fd.cFileName[0] <= L'9') {
                std::wstring sub = blenderDir + L"\\" + fd.cFileName + L"\\scripts\\startup";
                if (DirExistsW(sub)) {
                    versions.push_back(fd.cFileName);
                }
            }
        } while (FindNextFileW(hFind, &fd));
        FindClose(hFind);
    }
    return versions;
}

static std::string WideToUtf8(const std::wstring& w) {
    if (w.empty()) return "";
    int len = WideCharToMultiByte(CP_UTF8, 0, w.data(), static_cast<int>(w.size()), nullptr, 0, nullptr, nullptr);
    std::string out(len, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.data(), static_cast<int>(w.size()), &out[0], len, nullptr, nullptr);
    return out;
}

static bool ReplaceDllSafe(const std::wstring& srcPath, const std::wstring& dstPath) {
    std::wstring dir;
    size_t slash = dstPath.find_last_of(L"\\/");
    if (slash != std::wstring::npos) {
        dir = dstPath.substr(0, slash + 1);
    }
    WIN32_FIND_DATAW fd{};
    std::wstring pattern = dstPath + L".old*";
    HANDLE hFind = FindFirstFileW(pattern.c_str(), &fd);
    if (hFind != INVALID_HANDLE_VALUE) {
        do {
            if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
                DeleteFileW((dir + fd.cFileName).c_str());
            }
        } while (FindNextFileW(hFind, &fd));
        FindClose(hFind);
    }

    if (FileExistsW(dstPath)) {
        if (!DeleteFileW(dstPath.c_str())) {
            static unsigned long s_oldSeq = 0;
            std::wstring oldPath = dstPath + L".old." + std::to_wstring(GetTickCount64()) + L"." + std::to_wstring(++s_oldSeq);
            MoveFileExW(dstPath.c_str(), oldPath.c_str(), MOVEFILE_REPLACE_EXISTING);
        }
    }
    return CopyFileW(srcPath.c_str(), dstPath.c_str(), FALSE) != FALSE;
}

static const wchar_t* kPythonModules[] = {
    L"__init__.py",
    L"bridge.py",
    L"camera_light.py",
    L"nav_3d.py",
    L"shape_scanner.py",
    L"workspaces_ui.py",
};

int wmain(int argc, wchar_t* argv[]) {
    SetConsoleOutputCP(CP_UTF8);
    bool uninstallMode = (argc > 1 && std::wstring(argv[1]) == L"--uninstall");
    bool rescanMode = (argc > 1 && std::wstring(argv[1]) == L"--rescan");

    std::wstring installerDir = GetExeDir();
    std::wstring srcBridgeDll = installerDir + L"\\blender_nvda_accessibility.dll";
    std::wstring srcNvdaDll = installerDir + L"\\nvdaControllerClient64.dll";
    if (!FileExistsW(srcNvdaDll)) {
        std::printf("nvdaControllerClient64.dll не найден рядом с установщиком.\n");
        return 3;
    }
    std::wstring srcAutoloadPy = installerDir + L"\\blender_nvda_autoload.py";
    std::wstring srcModulesDir = installerDir + L"\\nvda_modules";

    auto blenders = FindInstalledBlenders();
    if (blenders.empty()) {
        std::printf("Blender не найден в стандартных папках.\n");
        return 1;
    }

    wchar_t appDataPath[MAX_PATH] = {0};
    SHGetFolderPathW(nullptr, CSIDL_APPDATA, nullptr, 0, appDataPath);
    std::wstring appDataRoot = std::wstring(appDataPath) + L"\\Blender Foundation\\Blender";

    for (const auto& blenderDir : blenders) {
        std::printf("Найден Blender: %s\n", WideToUtf8(blenderDir).c_str());
        auto verSubdirs = FindBlenderVersionSubdirs(blenderDir);
        for (const auto& ver : verSubdirs) {
            std::wstring userStartupDir = appDataRoot + L"\\" + ver + L"\\scripts\\startup";
            EnsureDirRecursive(userStartupDir);

            std::wstring dstBridgeDll = userStartupDir + L"\\blender_nvda_accessibility.dll";
            std::wstring dstNvdaDll = userStartupDir + L"\\nvdaControllerClient64.dll";
            std::wstring dstAutoloadPy = userStartupDir + L"\\blender_nvda_autoload.py";
            std::wstring dstModulesDir = userStartupDir + L"\\nvda_modules";
            std::wstring dstCache = userStartupDir + L"\\blender_nvda_symbols.cache";
            std::wstring exeBridgeDll = blenderDir + L"\\blender_nvda_accessibility.dll";
            std::wstring exeNvdaDll = blenderDir + L"\\nvdaControllerClient64.dll";
            std::wstring exeCache = blenderDir + L"\\blender_nvda_symbols.cache";

            if (uninstallMode) {
                RemovePycacheDir(userStartupDir);
                RemovePycacheDir(dstModulesDir);
                DeleteFileW(dstAutoloadPy.c_str());
                for (const wchar_t* modFile : kPythonModules) {
                    DeleteFileW((dstModulesDir + L"\\" + modFile).c_str());
                }
                RemoveDirectoryW(dstModulesDir.c_str());
                DeleteFileW(dstBridgeDll.c_str());
                DeleteFileW(dstNvdaDll.c_str());
                DeleteFileW(dstCache.c_str());
                DeleteFileW(exeCache.c_str());
                std::printf("Адаптация удалена из профиля Blender %s\n", WideToUtf8(ver).c_str());
                continue;
            }
            if (rescanMode || FileExistsW(dstCache)) {
                DeleteFileW(dstCache.c_str());
                DeleteFileW(exeCache.c_str());
            }

            if (!ReplaceDllSafe(srcBridgeDll, dstBridgeDll)) {
                std::printf("Ошибка копирования blender_nvda_accessibility.dll (код %lu)\n", GetLastError());
                return 2;
            }
            if (!ReplaceDllSafe(srcNvdaDll, dstNvdaDll)) {
                std::printf("Ошибка копирования nvdaControllerClient64.dll (код %lu)\n", GetLastError());
                return 3;
            }

            ReplaceDllSafe(srcBridgeDll, exeBridgeDll);
            ReplaceDllSafe(srcNvdaDll, exeNvdaDll);

            RemovePycacheDir(userStartupDir);
            if (!CopyFileW(srcAutoloadPy.c_str(), dstAutoloadPy.c_str(), FALSE)) {
                std::printf("Ошибка копирования blender_nvda_autoload.py (код %lu)\n", GetLastError());
                return 4;
            }
            EnsureDirRecursive(dstModulesDir);
            RemovePycacheDir(dstModulesDir);
            for (const wchar_t* modFile : kPythonModules) {
                std::wstring srcMod = srcModulesDir + L"\\" + modFile;
                std::wstring dstMod = dstModulesDir + L"\\" + modFile;
                if (!CopyFileW(srcMod.c_str(), dstMod.c_str(), FALSE)) {
                    std::printf("Ошибка копирования модуля nvda_modules\\%s (код %lu)\n", WideToUtf8(modFile).c_str(), GetLastError());
                    return 5;
                }
            }

            std::wstring blenderExePath = blenderDir + L"\\blender.exe";
            std::wstring blenderPdbPath = blenderDir + L"\\blender.pdb";
            if (FileExistsW(blenderExePath) && FileExistsW(blenderPdbPath)) {
                if (BlenderSymbolResolver::PrebuildCacheFromFiles(blenderExePath, blenderPdbPath, dstCache)) {
                    CopyFileW(dstCache.c_str(), exeCache.c_str(), FALSE);
                    std::printf("  -> Кэш символов собран заранее: %s\n", WideToUtf8(dstCache).c_str());
                } else {
                    std::printf("  -> Предупреждение: не удалось заранее собрать кэш символов\n");
                }
            }

            std::printf("Успешно установлено для Blender %s:\n  -> %s\n",
                        WideToUtf8(ver).c_str(),
                        WideToUtf8(userStartupDir).c_str());
        }
    }

    HMODULE hNvda = LoadLibraryW(srcNvdaDll.c_str());
    if (hNvda) {
        typedef unsigned long (__stdcall *pfn_speak)(const wchar_t*);
        auto speak = reinterpret_cast<pfn_speak>(GetProcAddress(hNvda, "nvdaController_speakText"));
        if (speak) {
            speak(uninstallMode
                ? L"Адаптация Blender для NVDA удалена."
                : L"Обновлённая адаптация Blender для NVDA установлена.");
        }
        FreeLibrary(hNvda);
    }

    return 0;
}
