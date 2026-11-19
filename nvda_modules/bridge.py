import os
import math
import ctypes
import bpy
import mathutils

_module_dir = os.path.dirname(os.path.abspath(__file__))
_dir = os.path.dirname(_module_dir)
_nvda = os.path.join(_dir, 'nvdaControllerClient64.dll')
if not os.path.exists(_nvda):
    _nvda = os.path.join(_module_dir, 'nvdaControllerClient64.dll')
_dll_path = os.path.join(_dir, 'blender_nvda_accessibility.dll')
if not os.path.exists(_dll_path):
    _dll_path = os.path.join(_module_dir, 'blender_nvda_accessibility.dll')
_bridge = None

if os.path.exists(_nvda):
    ctypes.WinDLL(_nvda)
if os.path.exists(_dll_path):
    _bridge = ctypes.WinDLL(_dll_path)
    _bridge.SpeakBlenderText.argtypes = [ctypes.c_char_p, ctypes.c_int]
    _bridge.GetActiveBlenderZone.restype = ctypes.c_int
    _bridge.SetActiveBlenderZone.argtypes = [ctypes.c_int]
    _bridge.IsBlenderPopupOpen.restype = ctypes.c_int
    _bridge.CenterMouseInView3D.restype = None
    _bridge.InitBlenderAccessibility()

def _speak_3d(text, interrupt=1):
    if _bridge is not None and text:
        _bridge.SpeakBlenderText(text.encode('utf-8'), interrupt)

def _get_zone():
    if _bridge is not None:
        try:
            return int(_bridge.GetActiveBlenderZone())
        except Exception:
            return 0
    return 0

def _set_zone(zone):
    if _bridge is not None:
        try:
            _bridge.SetActiveBlenderZone(int(zone))
        except Exception:
            pass

def _is_popup_open():
    if _bridge is not None:
        try:
            return int(_bridge.IsBlenderPopupOpen()) != 0
        except Exception:
            return False
    return False

_STEP_PRESETS = [0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]

_state = {
    "step_size": 0.5,
    "rot_step_deg": 15.0,
    "yaw_deg": 0.0,
    "pitch_deg": 0.0,
    "grabbed_name": "",
}

_TYPE_NAMES_RU = {
    'MESH': 'Меш',
    'CURVE': 'Кривая',
    'SURFACE': 'Поверхность',
    'META': 'Метасфера',
    'FONT': 'Текст',
    'ARMATURE': 'Скелет',
    'LATTICE': 'Решётка',
    'EMPTY': 'Пустышка',
    'LIGHT': 'Свет',
    'CAMERA': 'Камера',
    'SPEAKER': 'Динамик',
}

def _fmt_num(val, step=None):
    s = step if step is not None else _state["step_size"]
    if s < 0.001:
        return f"{val:.4f}".rstrip('0').rstrip('.') if abs(val) > 1e-7 else "0"
    elif s < 0.01:
        return f"{val:.3f}".rstrip('0').rstrip('.') if abs(val) > 1e-6 else "0"
    elif s < 0.1:
        return f"{val:.2f}".rstrip('0').rstrip('.') if abs(val) > 1e-5 else "0"
    else:
        return f"{val:.2f}".rstrip('0').rstrip('.') if abs(val) > 1e-4 else "0"

def _format_step_human(step):
    if step < 0.01:
        mm = step * 1000.0
        mm_s = f"{mm:.2f}".rstrip('0').rstrip('.')
        return f"{mm_s} мм ({_fmt_num(step, step)} м)"
    elif step < 1.0:
        cm = step * 100.0
        cm_s = f"{cm:.1f}".rstrip('0').rstrip('.')
        return f"{cm_s} см ({_fmt_num(step, step)} м)"
    else:
        m_s = f"{step:.2f}".rstrip('0').rstrip('.')
        return f"{m_s} м"

def _world_bbox(obj):
    if obj is None or not hasattr(obj, "bound_box") or not obj.bound_box:
        loc = obj.location if obj else mathutils.Vector((0.0, 0.0, 0.0))
        return (loc.copy(), loc.copy())
    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    xs = [p.x for p in corners]
    ys = [p.y for p in corners]
    zs = [p.z for p in corners]
    return (mathutils.Vector((min(xs), min(ys), min(zs))),
            mathutils.Vector((max(xs), max(ys), max(zs))))

def _obj_display_name(obj):
    if obj is None:
        return ""
    try:
        lbl = str(obj.get("access_label", "")).strip()
    except Exception:
        lbl = ""
    if lbl:
        return f"{lbl} ({obj.name})"
    return obj.name

def _is_view3d_context(context):
    if not context or not context.scene:
        return False
    sd = getattr(context, "space_data", None)
    if sd is not None:
        return sd.type == 'VIEW_3D'
    return bool(bpy.app.background)

def _sync_viewport(context):
    try:
        sd = getattr(context, "space_data", None)
        if sd is None or sd.type != 'VIEW_3D':
            return
        rv3d = getattr(sd, "region_3d", None)
        if rv3d is None or not context.scene:
            return
        fwd, right = _view_forward_right()
        up = right.cross(fwd)
        if up.length < 1e-6:
            up = mathutils.Vector((0.0, 0.0, 1.0))
        else:
            up.normalize()
        rot_mat = mathutils.Matrix((right.normalized(), up, -fwd.normalized())).transposed()
        rv3d.view_location = context.scene.cursor.location.copy()
        rv3d.view_rotation = rot_mat.to_quaternion()
    except Exception:
        pass

def _get_grabbed_obj(context):
    name = _state["grabbed_name"]
    if not name or not context.scene:
        return None
    obj = context.scene.objects.get(name)
    if obj is None:
        _state["grabbed_name"] = ""
    return obj

def _check_contacts(context, moving_obj, cursor_loc):
    if not context.scene:
        return ""
    tol = max(_state["step_size"] * 0.25, 0.0005)
    notes = []
    if moving_obj is not None:
        bmin1, bmax1 = _world_bbox(moving_obj)
        for other in context.scene.objects:
            if other == moving_obj or other.type in ('CAMERA', 'LIGHT'):
                continue
            other_disp = _obj_display_name(other)
            bmin2, bmax2 = _world_bbox(other)
            dx = max(0.0, max(bmin1.x - bmax2.x, bmin2.x - bmax1.x))
            dy = max(0.0, max(bmin1.y - bmax2.y, bmin2.y - bmax1.y))
            dz = max(0.0, max(bmin1.z - bmax2.z, bmin2.z - bmax1.z))
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            overlap_x = (bmin1.x < bmax2.x - tol) and (bmax1.x > bmin2.x + tol)
            overlap_y = (bmin1.y < bmax2.y - tol) and (bmax1.y > bmin2.y + tol)
            overlap_z = (bmin1.z < bmax2.z - tol) and (bmax1.z > bmin2.z + tol)
            if overlap_x and overlap_y and overlap_z:
                notes.append(f"Пересечение с {other_disp}")
            elif dist <= tol:
                notes.append(f"Стыковка вплотную к {other_disp}")
    else:
        for other in context.scene.objects:
            other_disp = _obj_display_name(other)
            bmin2, bmax2 = _world_bbox(other)
            dx = max(0.0, max(bmin2.x - cursor_loc.x, cursor_loc.x - bmax2.x))
            dy = max(0.0, max(bmin2.y - cursor_loc.y, cursor_loc.y - bmax2.y))
            dz = max(0.0, max(bmin2.z - cursor_loc.z, cursor_loc.z - bmax2.z))
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if dist == 0.0:
                notes.append(f"Внутри {other_disp}")
            elif dist <= tol:
                notes.append(f"Касание {other_disp}")
    return ". ".join(notes[:2])

def _view_forward_right():
    yaw_rad = math.radians(_state["yaw_deg"])
    pitch_rad = math.radians(_state["pitch_deg"])
    # At yaw=0, forward is +Y, right is +X
    fx = math.sin(yaw_rad) * math.cos(pitch_rad)
    fy = math.cos(yaw_rad) * math.cos(pitch_rad)
    fz = math.sin(pitch_rad)
    rx = math.cos(yaw_rad)
    ry = -math.sin(yaw_rad)
    return mathutils.Vector((fx, fy, fz)), mathutils.Vector((rx, ry, 0.0))
