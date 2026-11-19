# BlenderNVDA Complete User & Developer Guide (English)

## 1. Why BlenderNVDA Exists

Blender draws its entire UI directly through OpenGL/Vulkan without standard Windows accessibility controls (Win32 / UI Automation). Consequently, screen readers such as NVDA cannot read Blender's panels, buttons, menus, or 3D scene geometry.

**BlenderNVDA** is a native accessibility bridge for **Blender 5.2 LTS (Windows x64) + NVDA** built in two layers:
1. **Native C++ Library (`blender_nvda_accessibility.dll`):**
   - Loads a prebuilt symbol offset cache (`blender_nvda_symbols.cache`, version `3`, `33` resolved symbols from `blender.pdb`) for instant startup.
   - Installs lightweight detours on text drawing (`BLF_draw`, `BLF_draw_mono`), widget drawing (`ui::draw_button`), search items (`ui::draw_menu_item`), collapsible panels (`ui::draw_aligned_panel`), file list drawing (`file_draw_list`), button activation (`ui::button_activate_over`), and the window procedure (`GHOST_SystemWin32::s_wndProc`).
   - Sends all speech requests to `nvdaControllerClient64.dll` on a dedicated Win32 background worker thread (`NvdaSpeechEngine`) so Blender's main UI thread never freezes.
   - Executes UI actions **directly through Blender's internal pointers** on the main thread (`WM_APP_NVDA_ACTIVATE` → `Hook_s_wndProc` → `ExecutePendingUiAction()`) without OS cursor warping or `SendInput` mouse emulation.
2. **Modular Python Package (`blender_nvda_autoload.py` + `nvda_modules/`):**
   - `bridge.py` — DLL loading, speech wrappers, 3D navigation state, world bounding boxes, and contact checks.
   - `nav_3d.py` — step-by-step 3D cursor walking, object grabbing/placement, view/object rotation, object radar, exact "From/To" bounds dialog, and custom labels (`Vertex Groups` in Edit Mode).
   - `shape_scanner.py` — template-free in-RAM 3D geometric scanner reading evaluated geometry directly from memory.
   - `camera_light.py` — camera frustum/framing checks, light ray direction & shadow projection reports, and quick camera rendering.
   - `workspaces_ui.py` — quick Workspaces and Properties tabs switcher (`Shift+P` / `P`).

---

## 2. Installation, Updates, and Removal

### Option A: Prebuilt Package (`compiled` branch)
1. Download the **`compiled`** branch of `BlenderNVDA` and extract all files into one folder.
2. Close any open **Blender** windows so no DLL is locked by a running process.
3. Run **`BlenderNVDAInstaller.exe`**.
   - It automatically locates Blender 5.2 under `Program Files\Blender Foundation`, installs `blender_nvda_accessibility.dll`, `nvdaControllerClient64.dll`, `blender_nvda_autoload.py`, and `nvda_modules/` into `%APPDATA%\Blender Foundation\Blender\5.2\scripts\startup`, clears stale `__pycache__`, and prebuilds `blender_nvda_symbols.cache`.
4. Launch Blender with NVDA running.

### Option B: Build from Source (`main` branch)
Requires **MinGW-w64 (`g++` with C++17)** and `nvdaControllerClient64.dll` from the official NVDA Controller Client SDK:
```powershell
g++ -O2 -s -shared -std=c++17 -Wall -Wextra -static -static-libgcc -static-libstdc++ `
    blender_nvda_accessibility.cpp -o blender_nvda_accessibility.dll -luser32 -lkernel32

g++ -O2 -s -std=c++17 -municode -Wall -Wextra -static -static-libgcc -static-libstdc++ `
    BlenderNVDAInstaller.cpp -o BlenderNVDAInstaller.exe -lshell32 -luser32 -lkernel32
```
Place `nvdaControllerClient64.dll` next to the built files and run `.\BlenderNVDAInstaller.exe`.

### Installer Command-Line Flags
- *(no arguments)* — install or update the bridge and prebuild the symbol cache.
- `--rescan` — force rebuilding `blender_nvda_symbols.cache` (recommended after upgrading to a newer Blender 5.2.x patch release).
- `--uninstall` — cleanly remove all BlenderNVDA files from the Blender user startup folder.

---

## 3. Navigating the 4 Main UI Zones (`F6`)

Use **`F6`** (next) and **`Shift+F6`** (previous) to move between Blender's 4 logical UI zones:

1. **Zone 0 — `3D Scene` (`SPACE_VIEW3D`):**
   - Primary workspace for 3D walking, building, inspecting shapes, camera framing, and lighting.
   - Background redraws from toolbars and side panels stay silent so they never interrupt 3D navigation.
2. **Zone 1 — `Outliner / Scene Objects` (`SPACE_OUTLINER`):**
   - `Up` / `Down` arrows — step through Outliner items / scene objects.
   - `Enter` / `Space` — activate the selected entry directly.
3. **Zone 2 — `Properties & Settings` (`SPACE_PROPERTIES`, plus `Preferences`, `Shader/Node Editor`, etc.):**
   - **`Left` / `Right` arrows** — directly switch Properties tabs (Tool, Render, Output, View Layer, Scene, World, Collection, Object, Modifiers, Particles, Physics, Constraints, Data, Material, etc.). Switching tabs automatically clears stale items from the previous tab.
   - **`Up` / `Down` / `Tab` / `Shift+Tab`** — step through all controls in the active tab, including **collapsible panel headers** (`Панель: ...`) and controls scrolled below the visible viewport.
   - **`Enter` / `Space`** — execute directly without moving the mouse cursor:
     - on a panel header — toggles expand/collapse and speaks the updated state;
     - on a checkbox — immediately flips its boolean state;
     - on an action button — executes the operator;
     - on a dropdown or popover — opens the native menu;
     - on a numeric or text field — activates inline keyboard editing (`Enter` commits, `Escape` cancels).
4. **Zone 3 — `Top Menu & Headers` (`SPACE_TOPBAR` & editor headers):**
   - `Arrows` — walk File, Edit, Render, Window, Help, workspace tabs, and header controls.
   - `Enter` / `Space` — open the menu or activate the control.

### Native Menus, Dialogs, and Modal Spaces
- **`Shift+A` (Add menu), `Shift+P` (Workspaces & Tabs), `F3` (Search), dropdown menus:**
  - Popup lifetime is tracked directly from Blender's live `RGN_TYPE_TEMPORARY` regions — menus never time out while pausing or scrolling quickly.
  - Use arrow keys to browse, `Enter` to confirm, `Escape` to close.
- **Dialog Popups (`N` "From/To" bounds, `L` custom label, `F9` Adjust Last Operation):**
  - `Up` / `Down` or `Tab` / `Shift+Tab` navigates fields and buttons; `Enter` / `Space` activates or submits; while editing text, `Enter` commits the typed value.
- **File Browser (`Ctrl+S`, `Ctrl+O` — `SPACE_FILE`):**
  - Arrows, `PageUp`/`PageDown`, `Home`/`End`, `Enter`, and `Backspace` go straight to Blender's native file list; `Tab` / `Shift+Tab` navigates surrounding controls.
- **Preferences (`SPACE_USERPREF`):**
  - Automatically enters Zone 2 navigation (`Left`/`Right` switches categories, `Up`/`Down` walks settings, `Enter`/`Space` activates).
- **Tooltips (`F1` / `F5`):**
  - Speaks Blender's full native tooltip for the currently focused UI control.
- **`Escape`:**
  - Closes any open menu/dialog, exits text editing, and returns cleanly to the `3D Scene` (`Zone 0`).

---

## 4. Complete 3D Scene Shortcuts (Zone 0)

### Movement & Step Control
- **`Up` / `Down` / `Left` / `Right` arrows** — move forward, backward, left, or right relative to your current horizontal gaze direction. When holding an object (`E`), it moves together with the 3D cursor and reports contacts, flush alignment, or intersections.
- **`PageUp` / `PageDown`** — move up / down along the `Z` axis.
- **`Shift + Arrows` / `Shift + PageUp` / `Shift + PageDown`** — fine step (`0.1×` current step size).
- **`[` or `-`** — decrease step preset.
- **`]` or `=`** — increase step preset.

### Inspection, Grabbing & Exact Placement
- **`C`** — announce 3D cursor coordinates (`X, Y, Z`), gaze yaw/pitch, step size, and active/grabbed object bounds & dimensions.
- **`E`** — grab the nearest/active object into hand; pressing `E` again places it down with world bounds and contact/overlap feedback.
- **`F`** — radar scan announcing objects ahead and around you with distances and directions.
- **`Shift+F`** — open a menu listing all scene objects to jump straight to any object.
- **`Alt + Arrows`** — rotate your gaze direction, or rotate the grabbed object / active camera / light with updated facing direction readout.
- **`Alt + Shift + Arrows`** — scale a grabbed object; if a camera is targeted, adjust field of view (focal length); if a light is targeted, adjust power/energy.
- **`N`** — open the exact **"From / To"** dialog (`From X..To X`, `From Y..To Y`, `From Z..To Z`, movement step, rotation step) to size and position the active object to exact coordinates.
- **`Delete`** — delete the active object (Object Mode).
- **`Tab`** — toggle `Object Mode` ↔ `Edit Mode`.
- **`,` / `.`** (`Shift+,` / `Shift+.`) — step animation timeline backward/forward by `1` or `10` frames.

### Custom Object & Part Labels (`L`)
- **In Object Mode (`L`):** assigns a custom human-readable label to the active object (stored in the `.blend` file).
- **In Edit Mode (`L`, with vertices selected):** saves the selected geometry as a standard Blender `Vertex Group` with your label (e.g., "Handle", "Ledge", "Lid"). Subsequent `V` / `Shift+V` shape scans automatically read these groups from RAM and report their position and dimensions.

### In-RAM Mathematical 3D Shape Scanner (`V` & `Shift+V`)
Reads evaluated object geometry directly from Blender's memory (with modifiers applied):
- **`V` (semantic geometric summary):**
  - Supports `MESH`, `CURVE`, `SURFACE`, `META`, `FONT`, `LIGHT`, `CAMERA`, `ARMATURE`, `LATTICE`, `EMPTY`, and `SPEAKER`.
  - Recognizes overall shape profile (box/cube, sphere, cylinder/column, cone/pyramid, barrel, torus with through-hole, hollow cup/vessel with interior depth & wall thickness, curved open sheet/surface, open/closed curves, text objects).
  - Computes **6-sided surface relief, protrusions, and cavities** (Principle A), **horizontal tier island/support analysis** at `10% / 50% / 90%` height (Principle B), and reads **user-labeled Vertex Group parts**.
- **`Shift+V` (technical dimensions & topology):**
  - Exact extents along all 6 sides (`+Z`, `-Z`, `+X`, `-X`, `+Y`, `-Y`), vertex/edge/face/open-edge/loop counts, modifier list, and labeled parts.

### Camera, Lighting & Render (`J`, `Shift+J`, `F10`, `Shift+F10`)
- **`J`** — camera framing and lighting/shadow summary for the grabbed or active object (frame coverage %, distance, which lights hit which faces/intervals, and ground shadow projection at `Z = 0`).
- **`Shift+J`** — detailed scene-wide camera & lights report (including accurate Sun ray direction relative to horizon and wireframe curve visibility).
- **`F10`** — render the active camera view and announce frame composition.
- **`Shift+F10`** — align the active camera to your current 3D gaze first, then render and announce the frame.

### Workspaces & Property Tabs (`Shift+P` / `P`)
- Opens a unified menu to switch Blender Workspaces (`Layout`, `Modeling`, `Sculpting`, `Shading`, `Animation`, etc.) or jump straight to any Properties tab.

---

## 5. Source Architecture

| File | Responsibility |
| :--- | :--- |
| `blender_nvda_accessibility.cpp` | DLL entry point, native detours (`BLF_draw`, `draw_button`, `draw_menu_item`, `draw_aligned_panel`, `file_draw_list`, `button_activate_over`, `s_wndProc`), Python C exports |
| `blender_ui_types.hpp` | Blender 5.2 UI structs/flags, live popup detection (`HasLivePopupRegionOnScreen`), and direct execution queue (`PostPendingUiActivation` / `ExecutePendingUiAction`) |
| `ui_button_query.hpp` | Native button label/value/enum/tooltip extraction and zone navigation (`StepButtonVector`, `ActivateCurrentZoneButton`, `CycleMainZone`) |
| `keyboard_hook.hpp` | Thread-scoped `WH_KEYBOARD` router for Zones `0–3`, dialogs, native menus, `Preferences`, and `File Browser` |
| `nvda_speech.hpp` | Asynchronous Win32 speech worker thread (`nvdaControllerClient64.dll`), text cleanup, and deduplication |
| `pdb_resolver.hpp` | Fast single-pass `blender.pdb` scanner and binary offset cache (`blender_nvda_symbols.cache`, v3, `33` symbols) |
| `trampoline.hpp` | x64 prologue trampoline injector |
| `BlenderNVDAInstaller.cpp` | Windows installer: Blender discovery, safe DLL replacement, module deployment, `__pycache__` cleanup, cache prebuild, `--rescan` / `--uninstall` |
| `blender_nvda_autoload.py` | Blender startup entrypoint and `3D View` / `Object Mode` keymap registration |
| `nvda_modules/*.py` | Modular Python operators (`nav_3d.py`, `shape_scanner.py`, `camera_light.py`, `workspaces_ui.py`, `bridge.py`) |

---

## 6. Troubleshooting

- **No speech when launching Blender:** confirm NVDA is running, `blender.pdb` exists next to `blender.exe`, and `%APPDATA%\Blender Foundation\Blender\5.2\scripts\startup` contains `blender_nvda_accessibility.dll`, `nvdaControllerClient64.dll`, `blender_nvda_autoload.py`, and `nvda_modules/`.
- **Hooks stop working after updating Blender 5.2.x:** close Blender and run `BlenderNVDAInstaller.exe --rescan` to rebuild `blender_nvda_symbols.cache` for the new binary.
- **Leftover `.old` DLL files:** close all running Blender processes and run `BlenderNVDAInstaller.exe` again to automatically clean them up.
