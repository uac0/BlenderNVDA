import os
import sys
import bpy

_startup_dir = os.path.dirname(os.path.abspath(__file__))
if _startup_dir not in sys.path:
    sys.path.insert(0, _startup_dir)

from nvda_modules.bridge import (
    _dir,
    _nvda,
    _dll_path,
    _bridge,
    _speak_3d,
    _get_zone,
    _set_zone,
    _is_popup_open,
    _STEP_PRESETS,
    _state,
    _TYPE_NAMES_RU,
    _fmt_num,
    _format_step_human,
    _world_bbox,
    _obj_display_name,
    _is_view3d_context,
    _sync_viewport,
    _get_grabbed_obj,
    _check_contacts,
    _view_forward_right,
)
from nvda_modules.camera_light import (
    _dir_vec_ru,
    _ray_dir_ru,
    _frame_pos_ru,
    _face_side_ru,
    _select_camera,
    _camera_cone_report,
    _is_obj_visible_in_camera_cone,
    _span_interval_ru,
    _raycast_light_forward,
    _lights_shadow_report,
    _collect_light_rays,
    _object_light_camera_report,
    _object_under_cursor_or_active,
    ACCESS_OT_camera_light_summary,
    ACCESS_OT_render_frame,
)
from nvda_modules.nav_3d import (
    ACCESS_OT_step_3d,
    ACCESS_OT_change_step,
    ACCESS_OT_coords_info,
    ACCESS_OT_toggle_grab,
    ACCESS_OT_rotate_or_look,
    ACCESS_OT_radar_scan,
    ACCESS_OT_jump_to_object,
    ACCESS_OT_bounds_from_to,
    ACCESS_OT_delete_active,
    ACCESS_OT_frame_step,
    ACCESS_OT_toggle_edit_mode,
    ACCESS_OT_escape_scene,
    ACCESS_OT_set_label,
)
from nvda_modules.shape_scanner import (
    _euler_genus_components,
    _count_boundary_loops,
    _analyze_special_object,
    _analyze_wire_bmesh,
    _analyze_mesh_object,
    ACCESS_OT_scan_shape,
)
from nvda_modules.workspaces_ui import (
    _PROP_TAB_NAMES_RU,
    _find_properties_space,
    ACCESS_OT_switch_workspace,
    ACCESS_OT_switch_prop_tab,
    ACCESS_OT_workspace_menu,
)
import nvda_modules

_CLASSES = (
    ACCESS_OT_step_3d,
    ACCESS_OT_change_step,
    ACCESS_OT_coords_info,
    ACCESS_OT_toggle_grab,
    ACCESS_OT_rotate_or_look,
    ACCESS_OT_radar_scan,
    ACCESS_OT_jump_to_object,
    ACCESS_OT_bounds_from_to,
    ACCESS_OT_delete_active,
    ACCESS_OT_frame_step,
    ACCESS_OT_toggle_edit_mode,
    ACCESS_OT_escape_scene,
    ACCESS_OT_set_label,
    ACCESS_OT_camera_light_summary,
    ACCESS_OT_render_frame,
    ACCESS_OT_scan_shape,
    ACCESS_OT_switch_workspace,
    ACCESS_OT_switch_prop_tab,
    ACCESS_OT_workspace_menu,
)

_addon_keymaps = []

def _bind_access_keys_to_keymap(km):
    def add_step(key, direction, shift=False):
        kmi = km.keymap_items.new(ACCESS_OT_step_3d.bl_idname, key, 'PRESS', shift=shift)
        kmi.properties.direction = direction
        kmi.properties.fine = shift
        _addon_keymaps.append((km, kmi))

    for sh in (False, True):
        add_step('UP_ARROW', 'FORWARD', sh)
        add_step('DOWN_ARROW', 'BACK', sh)
        add_step('LEFT_ARROW', 'LEFT', sh)
        add_step('RIGHT_ARROW', 'RIGHT', sh)
        add_step('PAGE_UP', 'UP', sh)
        add_step('PAGE_DOWN', 'DOWN', sh)

    for key_dec in ('LEFT_BRACKET', 'MINUS'):
        kmi = km.keymap_items.new(ACCESS_OT_change_step.bl_idname, key_dec, 'PRESS')
        kmi.properties.increase = False
        _addon_keymaps.append((km, kmi))
    for key_inc in ('RIGHT_BRACKET', 'EQUAL'):
        kmi = km.keymap_items.new(ACCESS_OT_change_step.bl_idname, key_inc, 'PRESS')
        kmi.properties.increase = True
        _addon_keymaps.append((km, kmi))

    kmi_c = km.keymap_items.new(ACCESS_OT_coords_info.bl_idname, 'C', 'PRESS')
    _addon_keymaps.append((km, kmi_c))

    kmi_e = km.keymap_items.new(ACCESS_OT_toggle_grab.bl_idname, 'E', 'PRESS')
    _addon_keymaps.append((km, kmi_e))

    kmi_f1 = km.keymap_items.new(ACCESS_OT_radar_scan.bl_idname, 'F', 'PRESS', shift=False)
    kmi_f1.properties.open_list = False
    kmi_f2 = km.keymap_items.new(ACCESS_OT_radar_scan.bl_idname, 'F', 'PRESS', shift=True)
    kmi_f2.properties.open_list = True
    _addon_keymaps.extend([(km, kmi_f1), (km, kmi_f2)])

    for sh in (False, True):
        for k, act in (('LEFT_ARROW', 'YAW_LEFT'), ('RIGHT_ARROW', 'YAW_RIGHT'), ('UP_ARROW', 'PITCH_UP'), ('DOWN_ARROW', 'PITCH_DOWN')):
            kmi = km.keymap_items.new(ACCESS_OT_rotate_or_look.bl_idname, k, 'PRESS', alt=True, shift=sh)
            kmi.properties.action = act
            kmi.properties.scale_mode = sh
            _addon_keymaps.append((km, kmi))

    kmi_l = km.keymap_items.new(ACCESS_OT_set_label.bl_idname, 'L', 'PRESS')
    _addon_keymaps.append((km, kmi_l))

    for sh in (False, True):
        kmi_j = km.keymap_items.new(ACCESS_OT_camera_light_summary.bl_idname, 'J', 'PRESS', shift=sh)
        kmi_j.properties.detailed = sh
        _addon_keymaps.append((km, kmi_j))

        kmi_f10 = km.keymap_items.new(ACCESS_OT_render_frame.bl_idname, 'F10', 'PRESS', shift=sh)
        kmi_f10.properties.align_to_view = sh
        _addon_keymaps.append((km, kmi_f10))

        kmi_p = km.keymap_items.new(ACCESS_OT_workspace_menu.bl_idname, 'P', 'PRESS', shift=sh)
        kmi_p.properties.from_shift = sh
        _addon_keymaps.append((km, kmi_p))

        kmi_v = km.keymap_items.new(ACCESS_OT_scan_shape.bl_idname, 'V', 'PRESS', shift=sh)
        kmi_v.properties.globe_mode = sh
        _addon_keymaps.append((km, kmi_v))

    kmi_n = km.keymap_items.new(ACCESS_OT_bounds_from_to.bl_idname, 'N', 'PRESS')
    _addon_keymaps.append((km, kmi_n))

    kmi_del = km.keymap_items.new(ACCESS_OT_delete_active.bl_idname, 'DEL', 'PRESS')
    _addon_keymaps.append((km, kmi_del))

    for sh, step_f in ((False, 1), (True, 10)):
        kmi_prev = km.keymap_items.new(ACCESS_OT_frame_step.bl_idname, 'COMMA', 'PRESS', shift=sh)
        kmi_prev.properties.delta = -step_f
        kmi_next = km.keymap_items.new(ACCESS_OT_frame_step.bl_idname, 'PERIOD', 'PRESS', shift=sh)
        kmi_next.properties.delta = step_f
        _addon_keymaps.extend([(km, kmi_prev), (km, kmi_next)])

    kmi_tab = km.keymap_items.new(ACCESS_OT_toggle_edit_mode.bl_idname, 'TAB', 'PRESS')
    _addon_keymaps.append((km, kmi_tab))

    kmi_esc = km.keymap_items.new(ACCESS_OT_escape_scene.bl_idname, 'ESC', 'PRESS')
    _addon_keymaps.append((km, kmi_esc))

def _disable_conflicting_frame_arrows():
    try:
        wm = bpy.context.window_manager
        if not wm:
            return None
        if not _addon_keymaps:
            kc_addon = wm.keyconfigs.addon
            if kc_addon:
                km_3d = kc_addon.keymaps.get('3D View') or kc_addon.keymaps.new(name='3D View', space_type='VIEW_3D')
                _bind_access_keys_to_keymap(km_3d)
                km_obj = kc_addon.keymaps.get('Object Mode') or kc_addon.keymaps.new(name='Object Mode', space_type='EMPTY')
                _bind_access_keys_to_keymap(km_obj)
        for kc in (wm.keyconfigs.default, wm.keyconfigs.user, wm.keyconfigs.active):
            if not kc:
                continue
            frames_km = kc.keymaps.get('Frames')
            if frames_km:
                for kmi in frames_km.keymap_items:
                    if kmi.type in ('LEFT_ARROW', 'RIGHT_ARROW', 'UP_ARROW', 'DOWN_ARROW'):
                        kmi.active = False
        if _bridge is not None:
            _bridge.CenterMouseInView3D()
    except Exception:
        pass
    return None

def register():
    try:
        for cls in _CLASSES:
            bpy.utils.register_class(cls)
        wm = bpy.context.window_manager
        kc = wm.keyconfigs.addon if wm else None
        if kc:
            km_3d = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
            _bind_access_keys_to_keymap(km_3d)
            km_obj = kc.keymaps.new(name='Object Mode', space_type='EMPTY')
            _bind_access_keys_to_keymap(km_obj)
        bpy.app.timers.register(_disable_conflicting_frame_arrows, first_interval=0.3)
    except Exception:
        pass

def unregister():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps.clear()
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
