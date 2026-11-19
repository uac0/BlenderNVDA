# BlenderNVDA — Native Accessibility Bridge for Blender 5.2 + NVDA

[English](#english) | [Русский](#русский)

> Full step-by-step manuals / Подробнейшие руководства:
> - **[Подробная инструкция на русском (`docs/GUIDE_RU.md`)](docs/GUIDE_RU.md)**
> - **[Complete English Guide (`docs/GUIDE_EN.md`)](docs/GUIDE_EN.md)**

---

<a id="русский"></a>
## Русский

### Зачем нужен этот проект

Стандартный интерфейс **Blender** рисуется напрямую через графический конвейер (OpenGL / Vulkan) без стандартных элементов ОС Windows (UIA / MSAA), поэтому программы экранного доступа вроде **NVDA** видят окно Blender как «пустой экран».

**BlenderNVDA** решает эту проблему на нативном уровне — без OCR, без распознавания картинок и без «угадывания пикселей мышкой»:
- **Прямой C++ перехват интерфейса (`blender_nvda_accessibility.dll`)** читает названия, значения, состояния чекбоксов, заголовки сворачиваемых панелей, списки и всплывающие подсказки напрямую из структур `ui::Button`, `ui::Panel` и RNA-свойств Blender 5.2.
- **Прямая «магистраль» управления без курсора мыши:** нажатия кнопок, переключение галочек, вкладок Свойств, текстовых полей, списков и сворачиваемых панелей выполняются напрямую через внутренние функции Blender (`ui::button_execute`, `ui::button_activate_event`, `ui::textbutton_activate_but`, `ED_region_tag_redraw`) на главном потоке окна (`GHOST_SystemWin32::s_wndProc`), без эмуляции кликов `SendInput` и прыжков курсора.
- **Асинхронная озвучка через NVDA (`nvdaControllerClient64.dll`):** вызовы речи вынесены в отдельный рабочий поток Win32, чтобы интерфейс Blender никогда не зависал (`Не отвечает`).
- **Полноценное незрячее 3D-моделирование (`nvda_modules/`):** пошаговая 3D-навигация стрелками, захват и стыковка деталей, точный ввод границ «От и До», математический **RAM-сканер 3D-формы** (читает геометрию напрямую из оперативной памяти для мешей, кривых, NURBS-поверхностей, метасфер, текста, света и камер — с анализом рельефа, выступов, впадин, ярусов опор и пользовательских меток частей), анализ попадания в кадр камеры и теней от источников света.

### Требования

- **ОС:** Windows 10 / 11 (x64)
- **Blender:** `5.2.x LTS` (установленный вместе со штатным `blender.pdb` рядом с `blender.exe`)
- **Скринридер:** [NVDA](https://www.nvaccess.org/) + библиотека `nvdaControllerClient64.dll` из официального NVDA Controller Client SDK

### Быстрая установка (из ветки `compiled`)

Если не хотите компилировать проект вручную, в репозитории есть отдельная ветка **[`compiled`](https://github.com/uac0/BlenderNVDA/tree/compiled)** с готовыми бинарными файлами:
1. Переключитесь на ветку **`compiled`** (или скачайте её ZIP-архив на GitHub).
2. Распакуйте папку и убедитесь, что рядом лежат:
   - `BlenderNVDAInstaller.exe`
   - `blender_nvda_accessibility.dll`
   - `nvdaControllerClient64.dll`
   - `blender_nvda_autoload.py`
   - папка `nvda_modules/`
3. Закройте открытые окна Blender и запустите `BlenderNVDAInstaller.exe`.
   - Установщик автоматически найдёт Blender 5.2, скопирует файлы в `%APPDATA%\Blender Foundation\Blender\5.2\scripts\startup`, очистит старый `__pycache__` и заранее соберёт кэш символов `blender_nvda_symbols.cache` (для мгновенного старта).
   - Поддерживаемые ключи установщика:
     - `BlenderNVDAInstaller.exe --rescan` — пересобрать кэш символов (например, после обновления минорной версии Blender 5.2.x).
     - `BlenderNVDAInstaller.exe --uninstall` — полностью удалить адаптацию из профиля Blender.
4. Запустите Blender с включённым NVDA.

### Сборка из исходников (ветка `main`, MinGW-w64 / GCC)

```powershell
# 1. Сборка статической DLL-библиотеки (зависит только от системных DLL Windows)
g++ -O2 -s -shared -std=c++17 -Wall -Wextra -static -static-libgcc -static-libstdc++ `
    blender_nvda_accessibility.cpp -o blender_nvda_accessibility.dll -luser32 -lkernel32

# 2. Сборка установщика
g++ -O2 -s -std=c++17 -municode -Wall -Wextra -static -static-libgcc -static-libstdc++ `
    BlenderNVDAInstaller.cpp -o BlenderNVDAInstaller.exe -lshell32 -luser32 -lkernel32
```

Поместите `nvdaControllerClient64.dll` (из NVDA Controller Client SDK) в папку со сборкой и запустите `.\BlenderNVDAInstaller.exe`.

### Краткая шпаргалка по клавишам

| Клавиши | Назначение |
| :--- | :--- |
| **`F6` / `Shift+F6`** | Переключение между 4 основными зонами: `0` — 3D-сцена, `1` — Список объектов (Outliner), `2` — Свойства и настройки, `3` — Верхнее меню |
| **`Стрелки`, `PageUp` / `PageDown`** | В 3D-сцене: шаг вперёд/назад/влево/вправо/вверх/вниз (`+Shift` — точный шаг в 10 раз меньше). В Зонах `1–3` и диалогах: переход по элементам и панелям |
| **`Влево` / `Вправо` (Зона `2`)** | Переключение вкладок Свойств (Рендер, Сцена, Объект, Модификаторы, Физика, Материал и др.) и Настроек |
| **`Enter` / `Пробел` (Зоны `1–3`, диалоги)** | Прямое нажатие кнопки, переключение галочки, раскрытие/сворачивание панели, вход в ввод числа/текста или открытие списка |
| **`[` / `-` и `]` / `=`** | Уменьшить / увеличить шаг перемещения в 3D-сцене |
| **`Alt + Стрелки`** | Поворот взгляда, детали в руках, камеры или света (`Alt+Shift+Стрелки` — масштаб детали / угол камеры / мощность света) |
| **`E`** | Захватить ближайший/активный объект в руки или поставить (с проверкой стыковки и пересечений) |
| **`C`** | Озвучить координаты 3D-курсора, направление взгляда, шаг, габариты и границы активного объекта |
| **`F` / `Shift+F`** | Осмотреться (что впереди и вокруг) / открыть меню быстрого прыжка к объекту |
| **`V` / `Shift+V`** | RAM-скан формы объекта (профиль, полости, рельеф, выступы/впадины, опоры, метки) / точные границы, топология и модификаторы |
| **`L`** | Назначить пользовательскую метку объекту (в Object Mode) или выделенной части через `Vertex Group` (в Edit Mode) |
| **`N`** | Окно точного ввода границ «От и До» (`X/Y/Z`), размера шага и угла поворота |
| **`J` / `Shift+J`** | Сводка попадания в кадр камеры и освещения/теней для выбранного объекта / всей сцены |
| **`F10` / `Shift+F10`** | Сделать снимок камерой (`Shift+F10` — сначала выровнять камеру по текущему взгляду) |
| **`Shift+P` / `P`** | Меню рабочих пространств (Workspaces) и вкладок Свойств |
| **`Shift+A` / `F3`** | Штатное меню добавления объектов / глобальный поиск Blender с озвучкой |
| **`Tab` / `Delete` / `,` `.`** | Режим объекта ↔ редактирования / удалить активный объект / шаг по кадрам анимации (`+Shift` по 10 кадров) |
| **`F1` / `F5`** | Озвучить подробную родную подсказку Blender для текущей кнопки |
| **`Escape`** | Закрыть окно/меню или вернуться в `3D-сцену` |

👉 Подробное описание каждого режима и сценария работы см. в **[`docs/GUIDE_RU.md`](docs/GUIDE_RU.md)**.

### Структура репозитория (ветки и теги)

- Ветка **`main`** — чистые исходники (C++ заголовки, Python-пакет `nvda_modules/`, документация, `.gitignore`, `LICENSE`).
- Ветка **`compiled`** — готовые скомпилированные бинарники для Windows x64 (`BlenderNVDAInstaller.exe`, `blender_nvda_accessibility.dll`, `nvdaControllerClient64.dll` и скрипты для установки в один клик).
- **Теги истории разработки (бэкапы по этапам):**
  - `v0.1-backup1` — первый стабильный прототип перехвата Blender 5.2 и 3D-навигации;
  - `v0.2-backup2` — добавлены RAM-сканер форм, отчёт камеры/света и предсобранный кэш символов;
  - `v0.3-backup3` — модульная архитектура C++ и пакет `nvda_modules/`, анализ рельефа/ярусов и пользовательские метки;
  - `v0.4-direct-ui` — прямая «магистраль» UI без курсора мыши (`button_execute` / `button_activate_event` / `Hook_s_wndProc`), исправление вкладок Свойств, отказ от `900 мс` таймаута меню и ускорение старта.

---

<a id="english"></a>
## English

### Why This Project Exists

**Blender** renders its entire interface directly through OpenGL/Vulkan without exposing native Windows accessibility trees (UIA/MSAA). As a result, screen readers such as **NVDA** see the Blender viewport and panels as a blank window.

**BlenderNVDA** bridges Blender 5.2 and NVDA directly at the native level — without OCR, screenshots, or fragile pixel-guessing:
- **Native C++ UI hook (`blender_nvda_accessibility.dll`):** reads button labels, RNA values, checkbox states, collapsible panel headers, menus, and tooltips directly from Blender 5.2's internal `ui::Button`, `ui::Panel`, and RNA APIs.
- **Mouse-free Direct UI Execution Highway:** activating buttons, toggling checkboxes, switching Properties tabs, opening dropdowns/popovers, editing text/number inputs, and folding/unfolding panels all execute directly on Blender's main UI thread (`GHOST_SystemWin32::s_wndProc`) via `ui::button_execute`, `ui::button_activate_event`, `ui::textbutton_activate_but`, and `ED_region_tag_redraw` — zero `SendInput` mouse clicks and zero cursor warping.
- **Asynchronous NVDA Speech Engine (`nvdaControllerClient64.dll`):** all speech calls run on a dedicated Win32 background worker thread so Blender's UI thread never stalls.
- **Blind-first 3D Modeling Suite (`nvda_modules/`):** step-by-step 3D cursor navigation, object grab/placement with contact & intersection feedback, exact "From/To" bounds input, a fast **in-RAM 3D Shape Scanner** (reads evaluated geometry directly from memory across Meshes, Curves, NURBS Surfaces, Metaballs, Text, Lights, Cameras, Armatures, and Lattices — reporting profiles, hollowness, relief/protrusions/cavities, support tiers, and user Vertex Group part labels), plus camera framing and lighting/shadow ray reports.

### Requirements

- **OS:** Windows 10 / 11 (64-bit)
- **Blender:** `5.2.x LTS` (with the matching `blender.pdb` next to `blender.exe`)
- **Screen Reader:** [NVDA](https://www.nvaccess.org/) + `nvdaControllerClient64.dll` from the official NVDA Controller Client SDK

### Quick Install (from the `compiled` branch)

Prebuilt Windows x64 binaries are available on the dedicated **[`compiled`](https://github.com/uac0/BlenderNVDA/tree/compiled)** branch:
1. Switch to the **`compiled`** branch (or download it as a ZIP archive from GitHub).
2. Extract the archive so all files remain in the same folder:
   - `BlenderNVDAInstaller.exe`
   - `blender_nvda_accessibility.dll`
   - `nvdaControllerClient64.dll`
   - `blender_nvda_autoload.py`
   - `nvda_modules/`
3. Close any running Blender windows and run `BlenderNVDAInstaller.exe`.
   - The installer detects Blender 5.2, deploys the DLL and Python modules to `%APPDATA%\Blender Foundation\Blender\5.2\scripts\startup`, clears stale `__pycache__`, and prebuilds `blender_nvda_symbols.cache` for instant startup.
   - Optional installer flags:
     - `BlenderNVDAInstaller.exe --rescan` — rebuild the symbol cache after a Blender 5.2.x minor update.
     - `BlenderNVDAInstaller.exe --uninstall` — cleanly remove BlenderNVDA from the Blender startup profile.
4. Launch Blender with NVDA running.

### Building from Source (`main` branch, MinGW-w64 / GCC)

```powershell
# 1. Build the static accessibility DLL (system Windows DLL dependencies only)
g++ -O2 -s -shared -std=c++17 -Wall -Wextra -static -static-libgcc -static-libstdc++ `
    blender_nvda_accessibility.cpp -o blender_nvda_accessibility.dll -luser32 -lkernel32

# 2. Build the installer executable
g++ -O2 -s -std=c++17 -municode -Wall -Wextra -static -static-libgcc -static-libstdc++ `
    BlenderNVDAInstaller.cpp -o BlenderNVDAInstaller.exe -lshell32 -luser32 -lkernel32
```

Place `nvdaControllerClient64.dll` (from the NVDA Controller Client SDK) next to the compiled executables and run `.\BlenderNVDAInstaller.exe`.

### Quick Shortcut Overview

| Shortcut | Action |
| :--- | :--- |
| **`F6` / `Shift+F6`** | Cycle the 4 main zones: `0` — 3D Scene, `1` — Outliner, `2` — Properties & Settings, `3` — Top Menu & Headers |
| **`Arrows`, `PageUp` / `PageDown`** | In 3D Scene: step forward/back/left/right/up/down (`+Shift` for 10x finer step). In Zones `1–3` & dialogs: navigate controls and panels |
| **`Left` / `Right` (Zone `2`)** | Switch Properties tabs (Render, Scene, Object, Modifiers, Physics, Material, etc.) and Preferences categories |
| **`Enter` / `Space` (Zones `1–3`, dialogs)** | Directly click buttons, toggle checkboxes, expand/collapse panels, open menus, or edit text/numeric fields without moving the mouse |
| **`[` / `-` and `]` / `=`** | Decrease / increase 3D movement step preset |
| **`Alt + Arrows`** | Turn view gaze or rotate grabbed object / camera / light (`Alt+Shift+Arrows` scales object or adjusts camera FOV / light energy) |
| **`E`** | Grab nearest/active object or release it (announces contact / alignment / intersection) |
| **`C`** | Announce 3D cursor coordinates, gaze angles, step size, and active object extents/dimensions |
| **`F` / `Shift+F`** | Radar scan (what is ahead and nearby) / open Jump-to-Object menu |
| **`V` / `Shift+V`** | In-RAM 3D shape scan (profile, hollowness, relief, protrusions/cavities, support tiers, part labels) / exact extents, topology & modifiers |
| **`L`** | Assign a custom label to an object (Object Mode) or selected vertices via `Vertex Group` (Edit Mode) |
| **`N`** | Exact "From / To" bounds (`X/Y/Z`), movement step, and rotation step dialog |
| **`J` / `Shift+J`** | Camera framing & lighting/shadow summary for the target object / entire scene |
| **`F10` / `Shift+F10`** | Render camera frame (`Shift+F10` aligns camera to current gaze first) |
| **`Shift+P` / `P`** | Workspaces & Properties tabs menu |
| **`Shift+A` / `F3`** | Native Blender Add menu / Global Search with live NVDA readout |
| **`Tab` / `Delete` / `,` `.`** | Toggle Object ↔ Edit Mode / delete active object / step animation frames (`+Shift` for ±10 frames) |
| **`F1` / `F5`** | Speak Blender's native tooltip for the focused control |
| **`Escape`** | Close popup/menu or return cleanly to the `3D Scene` |

👉 For complete documentation, workflows, and architecture details, read **[`docs/GUIDE_EN.md`](docs/GUIDE_EN.md)**.

### Repository Structure (Branches & Tags)

- **`main` branch:** clean source code (C++ headers, `nvda_modules/` Python package, docs, `.gitignore`, `LICENSE`).
- **`compiled` branch:** ready-to-run Windows x64 binaries (`BlenderNVDAInstaller.exe`, `blender_nvda_accessibility.dll`, `nvdaControllerClient64.dll`, and scripts).
- **Milestone tags (project history backups):**
  - `v0.1-backup1` — initial native Blender 5.2 hook & 3D navigation;
  - `v0.2-backup2` — in-RAM shape scanner, camera/lighting reports, prebuilt symbol cache;
  - `v0.3-backup3` — modular C++ headers & `nvda_modules/` Python architecture, relief/tier/part-label scanning;
  - `v0.4-direct-ui` — mouse-free direct UI execution highway (`button_execute` / `button_activate_event` / `Hook_s_wndProc`), fixed Properties tabs & live popup detection, startup optimization.

---

## License / Лицензия

This project is licensed under the **GNU General Public License v3.0 (GPLv3)** — see [`LICENSE`](LICENSE).
Проект распространяется под лицензией **GNU GPL v3.0** — см. файл [`LICENSE`](LICENSE).
