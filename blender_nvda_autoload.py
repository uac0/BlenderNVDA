import os
import math
import ctypes
import tempfile
import numpy as np
import bpy
import bmesh
import mathutils
import bpy_extras.object_utils

_dir = os.path.dirname(os.path.abspath(__file__))
_nvda = os.path.join(_dir, 'nvdaControllerClient64.dll')
_dll_path = os.path.join(_dir, 'blender_nvda_accessibility.dll')
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

class ACCESS_OT_step_3d(bpy.types.Operator):
    bl_idname = "view3d.access_step_3d"
    bl_label = "Шаг в 3D-сцене"
    bl_options = {'REGISTER', 'UNDO'}

    direction: bpy.props.StringProperty(default="FORWARD")
    fine: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        if _is_popup_open() or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        zone = _get_zone()
        if zone == 1:
            # In Zone 1 (Outliner / Object list), Up/Down cycles scene objects natively
            objs = list(context.scene.objects)
            if not objs:
                _speak_3d("Сцена пуста", 1)
                return {'FINISHED'}
            active = context.view_layer.objects.active
            idx = objs.index(active) if active in objs else 0
            step_idx = 1 if self.direction in ("BACK", "DOWN") else -1
            idx = (idx + step_idx) % len(objs)
            target = objs[idx]
            for o in objs:
                o.select_set(False)
            target.select_set(True)
            context.view_layer.objects.active = target
            context.scene.cursor.location = target.location.copy()
            _sync_viewport(context)
            t_ru = _TYPE_NAMES_RU.get(target.type, target.type)
            bmin, bmax = _world_bbox(target)
            dim = target.dimensions
            _speak_3d(
                f"{idx+1} из {len(objs)}: {_obj_display_name(target)} ({t_ru}). "
                f"Центр X {_fmt_num(target.location.x)}, Y {_fmt_num(target.location.y)}, Z {_fmt_num(target.location.z)}. "
                f"Размер {_fmt_num(dim.x)} на {_fmt_num(dim.y)} на {_fmt_num(dim.z)} м",
                1
            )
            return {'FINISHED'}
        if zone != 0:
            return {'PASS_THROUGH'}

        step = _state["step_size"] * (0.1 if self.fine else 1.0)
        fwd, right = _view_forward_right()
        # Horizontal forward for walking on XY plane
        yaw_rad = math.radians(_state["yaw_deg"])
        horiz_fwd = mathutils.Vector((math.sin(yaw_rad), math.cos(yaw_rad), 0.0))

        delta = mathutils.Vector((0.0, 0.0, 0.0))
        dir_label = ""
        if self.direction == "FORWARD":
            delta = horiz_fwd * step
            dir_label = "Вперёд"
        elif self.direction == "BACK":
            delta = -horiz_fwd * step
            dir_label = "Назад"
        elif self.direction == "RIGHT":
            delta = right * step
            dir_label = "Вправо"
        elif self.direction == "LEFT":
            delta = -right * step
            dir_label = "Влево"
        elif self.direction == "UP":
            delta = mathutils.Vector((0.0, 0.0, step))
            dir_label = "Вверх"
        elif self.direction == "DOWN":
            delta = mathutils.Vector((0.0, 0.0, -step))
            dir_label = "Вниз"

        cur = context.scene.cursor.location
        cur.x = round(cur.x + delta.x, 6)
        cur.y = round(cur.y + delta.y, 6)
        cur.z = round(cur.z + delta.z, 6)

        grabbed = _get_grabbed_obj(context)
        if grabbed is not None:
            grabbed.location.x = round(grabbed.location.x + delta.x, 6)
            grabbed.location.y = round(grabbed.location.y + delta.y, 6)
            grabbed.location.z = round(grabbed.location.z + delta.z, 6)
            context.view_layer.update()

        _sync_viewport(context)
        contact_msg = _check_contacts(context, grabbed, cur)
        prefix = f"{_obj_display_name(grabbed)} {dir_label}" if grabbed else dir_label
        coords_short = f"X {_fmt_num(cur.x, step)}, Y {_fmt_num(cur.y, step)}, Z {_fmt_num(cur.z, step)}"
        msg = f"{prefix}: {coords_short}"
        if contact_msg:
            msg = f"{contact_msg}! {msg}"
        _speak_3d(msg, 1)
        return {'FINISHED'}

class ACCESS_OT_change_step(bpy.types.Operator):
    bl_idname = "view3d.access_change_step"
    bl_label = "Изменить шаг перемещения"

    increase: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        cur = _state["step_size"]
        best_idx = min(range(len(_STEP_PRESETS)), key=lambda i: abs(_STEP_PRESETS[i] - cur))
        if self.increase:
            new_idx = min(len(_STEP_PRESETS) - 1, best_idx + 1)
        else:
            new_idx = max(0, best_idx - 1)
        _state["step_size"] = _STEP_PRESETS[new_idx]
        _speak_3d(f"Шаг перемещения: {_format_step_human(_state['step_size'])}", 1)
        return {'FINISHED'}

class ACCESS_OT_coords_info(bpy.types.Operator):
    bl_idname = "view3d.access_coords_info"
    bl_label = "Озвучить текущие координаты"

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        cur = context.scene.cursor.location
        msg = (
            f"Координаты: X {_fmt_num(cur.x)}, Y {_fmt_num(cur.y)}, Z {_fmt_num(cur.z)} м. "
            f"Взгляд: {int(round(_state['yaw_deg']))} градусов, наклон {int(round(_state['pitch_deg']))}. "
            f"Шаг: {_format_step_human(_state['step_size'])}."
        )
        grabbed = _get_grabbed_obj(context)
        active = grabbed or (context.view_layer.objects.active if context.view_layer else None)
        if active is not None:
            bmin, bmax = _world_bbox(active)
            dim = active.dimensions
            state_lbl = "В руках" if grabbed else "Выбран"
            msg += (
                f" {state_lbl}: {_obj_display_name(active)}. "
                f"От X {_fmt_num(bmin.x)} до {_fmt_num(bmax.x)}, "
                f"От Y {_fmt_num(bmin.y)} до {_fmt_num(bmax.y)}, "
                f"От Z {_fmt_num(bmin.z)} до {_fmt_num(bmax.z)}. "
                f"Размер {_fmt_num(dim.x)} на {_fmt_num(dim.y)} на {_fmt_num(dim.z)} м."
            )
        _speak_3d(msg, 1)
        return {'FINISHED'}

class ACCESS_OT_toggle_grab(bpy.types.Operator):
    bl_idname = "view3d.access_toggle_grab"
    bl_label = "Захватить или отпустить деталь"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        if context.mode != 'OBJECT':
            return {'PASS_THROUGH'}

        grabbed = _get_grabbed_obj(context)
        if grabbed is not None:
            _state["grabbed_name"] = ""
            bmin, bmax = _world_bbox(grabbed)
            contact = _check_contacts(context, grabbed, context.scene.cursor.location)
            msg = (
                f"Поставлен: {_obj_display_name(grabbed)}. "
                f"От X {_fmt_num(bmin.x)} до {_fmt_num(bmax.x)}, "
                f"От Y {_fmt_num(bmin.y)} до {_fmt_num(bmax.y)}, "
                f"От Z {_fmt_num(bmin.z)} до {_fmt_num(bmax.z)}."
            )
            if contact:
                msg += f" {contact}."
            _speak_3d(msg, 1)
            return {'FINISHED'}

        # Find nearest or active object to grab
        cur = context.scene.cursor.location
        target = context.view_layer.objects.active if context.view_layer else None
        objs = list(context.scene.objects)
        if not objs:
            _speak_3d("На сцене нет объектов для захвата", 1)
            return {'FINISHED'}

        # Prefer nearest object to 3D cursor if cursor is closer to another object
        nearest = min(objs, key=lambda o: (o.location - cur).length)
        if target is None or (nearest.location - cur).length < (target.location - cur).length:
            target = nearest

        for o in objs:
            o.select_set(False)
        target.select_set(True)
        context.view_layer.objects.active = target
        _state["grabbed_name"] = target.name
        dim = target.dimensions
        _speak_3d(
            f"Взят в руки: {_obj_display_name(target)}, размер {_fmt_num(dim.x)} на {_fmt_num(dim.y)} на {_fmt_num(dim.z)} м",
            1
        )
        return {'FINISHED'}

class ACCESS_OT_rotate_or_look(bpy.types.Operator):
    bl_idname = "view3d.access_rotate_or_look"
    bl_label = "Поворот взгляда или детали"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.StringProperty(default="YAW_LEFT")
    scale_mode: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        if context.mode != 'OBJECT':
            return {'PASS_THROUGH'}

        grabbed = _get_grabbed_obj(context)
        active = context.view_layer.objects.active if context.view_layer else None
        target_obj = grabbed or (active if (active is not None and active.type in ('CAMERA', 'LIGHT')) else None)
        rot_step = _state["rot_step_deg"]
        step = _state["step_size"]

        if target_obj is not None:
            gname = _obj_display_name(target_obj)
            if self.scale_mode:
                if target_obj.type == 'CAMERA':
                    delta_deg = 5.0 if self.action in ("PITCH_UP", "YAW_RIGHT") else -5.0
                    cur_deg = math.degrees(target_obj.data.angle)
                    new_deg = max(5.0, min(170.0, cur_deg + delta_deg))
                    target_obj.data.angle = math.radians(new_deg)
                    context.view_layer.update()
                    fov_x = round(math.degrees(target_obj.data.angle_x), 1)
                    fov_y = round(math.degrees(target_obj.data.angle_y), 1)
                    lens_mm = round(target_obj.data.lens, 1)
                    _speak_3d(f"Угол обзора камеры {gname}: {fov_x} на {fov_y} градусов (фокус {lens_mm} мм)", 1)
                    return {'FINISHED'}
                if target_obj.type == 'LIGHT':
                    ld = target_obj.data
                    delta_deg = 5.0 if self.action in ("PITCH_UP", "YAW_RIGHT") else -5.0
                    if ld.type == 'SPOT':
                        cur_deg = math.degrees(ld.spot_size)
                        new_deg = max(5.0, min(180.0, cur_deg + delta_deg))
                        ld.spot_size = math.radians(new_deg)
                        context.view_layer.update()
                        _speak_3d(f"Угол раскрытия прожектора {gname}: {round(new_deg, 1)} градусов", 1)
                    elif ld.type == 'AREA':
                        cur_deg = math.degrees(getattr(ld, 'spread', math.pi))
                        new_deg = max(5.0, min(180.0, cur_deg + delta_deg))
                        ld.spread = math.radians(new_deg)
                        context.view_layer.update()
                        _speak_3d(f"Угол разброса света {gname}: {round(new_deg, 1)} градусов", 1)
                    elif ld.type == 'SUN':
                        cur_deg = math.degrees(ld.angle)
                        new_deg = max(0.5, min(90.0, cur_deg + (1.0 if delta_deg > 0 else -1.0)))
                        ld.angle = math.radians(new_deg)
                        context.view_layer.update()
                        _speak_3d(f"Угол солнечного луча {gname}: {round(new_deg, 1)} градусов", 1)
                    else:
                        _speak_3d(f"Точечная лампа {gname} светит во все стороны на 360 градусов", 1)
                    return {'FINISHED'}
                delta_s = step if self.action in ("PITCH_UP", "YAW_RIGHT") else -step
                for i in range(3):
                    target_obj.dimensions[i] = max(0.0001, target_obj.dimensions[i] + delta_s)
                context.view_layer.update()
                d = target_obj.dimensions
                _speak_3d(
                    f"Размер {gname}: {_fmt_num(d.x)} на {_fmt_num(d.y)} на {_fmt_num(d.z)} м",
                    1
                )
                return {'FINISHED'}

            if self.action == "YAW_LEFT":
                target_obj.rotation_euler.z += math.radians(rot_step)
                deg = round(math.degrees(target_obj.rotation_euler.z)) % 360
                _speak_3d(f"Поворот {gname} по Z: {deg} градусов", 1)
            elif self.action == "YAW_RIGHT":
                target_obj.rotation_euler.z -= math.radians(rot_step)
                deg = round(math.degrees(target_obj.rotation_euler.z)) % 360
                _speak_3d(f"Поворот {gname} по Z: {deg} градусов", 1)
            elif self.action == "PITCH_UP":
                target_obj.rotation_euler.x += math.radians(rot_step)
                deg = round(math.degrees(target_obj.rotation_euler.x)) % 360
                _speak_3d(f"Наклон {gname} по X: {deg} градусов", 1)
            elif self.action == "PITCH_DOWN":
                target_obj.rotation_euler.x -= math.radians(rot_step)
                deg = round(math.degrees(target_obj.rotation_euler.x)) % 360
                _speak_3d(f"Наклон {gname} по X: {deg} градусов", 1)
            context.view_layer.update()
            return {'FINISHED'}

        # Rotate view direction and synchronize viewport monitor
        if self.action == "YAW_LEFT":
            _state["yaw_deg"] = (_state["yaw_deg"] - rot_step) % 360.0
            _sync_viewport(context)
            _speak_3d(f"Взгляд влево: {int(round(_state['yaw_deg']))} градусов", 1)
        elif self.action == "YAW_RIGHT":
            _state["yaw_deg"] = (_state["yaw_deg"] + rot_step) % 360.0
            _sync_viewport(context)
            _speak_3d(f"Взгляд вправо: {int(round(_state['yaw_deg']))} градусов", 1)
        elif self.action == "PITCH_UP":
            _state["pitch_deg"] = max(-85.0, min(85.0, _state["pitch_deg"] + rot_step))
            _sync_viewport(context)
            _speak_3d(f"Взгляд вверх: {int(round(_state['pitch_deg']))} градусов", 1)
        elif self.action == "PITCH_DOWN":
            _state["pitch_deg"] = max(-85.0, min(85.0, _state["pitch_deg"] - rot_step))
            _sync_viewport(context)
            _speak_3d(f"Взгляд вниз: {int(round(_state['pitch_deg']))} градусов", 1)
        return {'FINISHED'}

class ACCESS_OT_radar_scan(bpy.types.Operator):
    bl_idname = "view3d.access_radar_scan"
    bl_label = "Осмотреться (Что передо мной)"

    open_list: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}

        cur = context.scene.cursor.location
        fwd, right = _view_forward_right()
        objs = list(context.scene.objects)
        if not objs:
            _speak_3d("Сцена пуста", 1)
            return {'FINISHED'}

        if self.open_list:
            objs_sorted = sorted(objs, key=lambda o: (o.location - cur).length)
            def draw_obj_menu(menu_self, menu_ctx):
                layout = menu_self.layout
                for o in objs_sorted:
                    dist = (o.location - cur).length
                    t_ru = _TYPE_NAMES_RU.get(o.type, o.type)
                    op = layout.operator("view3d.access_jump_to_object", text=f"{_obj_display_name(o)} ({t_ru}, {_fmt_num(dist)} м)")
                    op.target_name = o.name
            context.window_manager.popup_menu(draw_obj_menu, title="Объекты сцены", icon='OBJECT_DATA')
            return {'FINISHED'}

        parts = []
        # 1. Native Blender ray_cast straight ahead
        try:
            depsgraph = context.evaluated_depsgraph_get()
            hit, hit_loc, hit_norm, hit_idx, hit_obj, _ = context.scene.ray_cast(depsgraph, cur, fwd)
            if hit and hit_obj is not None:
                hit_dist = (hit_loc - cur).length
                parts.append(f"Луч прямо упирается в {_obj_display_name(hit_obj)} через {_fmt_num(hit_dist)} м")
        except Exception:
            pass

        # 2. Relative position and distance of scene objects
        items = []
        for o in objs:
            vec = o.location - cur
            dist = vec.length
            items.append((dist, o, vec))
        items.sort(key=lambda x: x[0])

        for dist, o, vec in items[:6]:
            t_ru = _TYPE_NAMES_RU.get(o.type, o.type)
            dim = o.dimensions
            oname = _obj_display_name(o)
            if dist < 1e-4:
                rel = "Прямо в твоей точке"
            else:
                f_proj = vec.dot(fwd)
                r_proj = vec.dot(right)
                z_proj = vec.z
                dirs = []
                if abs(f_proj) >= 0.05:
                    dirs.append("впереди" if f_proj > 0 else "сзади")
                if abs(r_proj) >= 0.05:
                    dirs.append("правее" if r_proj > 0 else "левее")
                if abs(z_proj) >= 0.05:
                    dirs.append("выше" if z_proj > 0 else "ниже")
                rel = ", ".join(dirs).capitalize() if dirs else "Рядом"
            if o.type == 'MESH':
                parts.append(f"{rel} в {_fmt_num(dist)} м: {oname} (размер {_fmt_num(dim.x)}×{_fmt_num(dim.y)}×{_fmt_num(dim.z)} м)")
            else:
                parts.append(f"{rel} в {_fmt_num(dist)} м: {oname} ({t_ru})")

        _speak_3d(". ".join(parts), 1)
        return {'FINISHED'}

class ACCESS_OT_jump_to_object(bpy.types.Operator):
    bl_idname = "view3d.access_jump_to_object"
    bl_label = "Перейти к объекту"
    bl_options = {'REGISTER', 'UNDO'}

    target_name: bpy.props.StringProperty()

    def execute(self, context):
        if not context.scene:
            return {'CANCELLED'}
        obj = context.scene.objects.get(self.target_name)
        if obj is None:
            return {'CANCELLED'}
        for o in context.scene.objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        context.scene.cursor.location = obj.location.copy()
        _sync_viewport(context)
        dim = obj.dimensions
        _speak_3d(
            f"Перешёл к {_obj_display_name(obj)}. Координаты X {_fmt_num(obj.location.x)}, Y {_fmt_num(obj.location.y)}, Z {_fmt_num(obj.location.z)}. "
            f"Размер {_fmt_num(dim.x)} на {_fmt_num(dim.y)} на {_fmt_num(dim.z)} м",
            1
        )
        return {'FINISHED'}

class ACCESS_OT_bounds_from_to(bpy.types.Operator):
    bl_idname = "view3d.access_bounds_from_to"
    bl_label = "Задать координаты От и До и шаг"
    bl_options = {'REGISTER', 'UNDO'}

    from_x: bpy.props.FloatProperty(name="От X (м)", default=-1.0, precision=4)
    to_x:   bpy.props.FloatProperty(name="До X (м)", default=1.0, precision=4)
    from_y: bpy.props.FloatProperty(name="От Y (м)", default=-1.0, precision=4)
    to_y:   bpy.props.FloatProperty(name="До Y (м)", default=1.0, precision=4)
    from_z: bpy.props.FloatProperty(name="От Z (м)", default=-1.0, precision=4)
    to_z:   bpy.props.FloatProperty(name="До Z (м)", default=1.0, precision=4)
    step_val: bpy.props.FloatProperty(name="Шаг перемещения (м)", default=0.5, min=0.00001, max=100.0, precision=4)
    rot_val:  bpy.props.FloatProperty(name="Шаг поворота (градусы)", default=15.0, min=0.1, max=180.0, precision=1)

    def invoke(self, context, event):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        self.step_val = _state["step_size"]
        self.rot_val = _state["rot_step_deg"]
        active = context.view_layer.objects.active if context.view_layer else None
        if active is not None:
            bmin, bmax = _world_bbox(active)
            self.from_x, self.to_x = bmin.x, bmax.x
            self.from_y, self.to_y = bmin.y, bmax.y
            self.from_z, self.to_z = bmin.z, bmax.z
            _speak_3d(f"Окно координат От и До для {_obj_display_name(active)}. Стрелки Вверх и Вниз: поля, Enter: ввод и подтверждение", 1)
        else:
            cur = context.scene.cursor.location
            self.from_x = self.to_x = cur.x
            self.from_y = self.to_y = cur.y
            self.from_z = self.to_z = cur.z
            _speak_3d("Окно координат и настройки шага", 1)
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        if not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        _state["step_size"] = max(0.00001, float(self.step_val))
        _state["rot_step_deg"] = max(0.1, float(self.rot_val))
        active = context.view_layer.objects.active if context.view_layer else None
        x0, x1 = min(self.from_x, self.to_x), max(self.from_x, self.to_x)
        y0, y1 = min(self.from_y, self.to_y), max(self.from_y, self.to_y)
        z0, z1 = min(self.from_z, self.to_z), max(self.from_z, self.to_z)
        cx, cy, cz = (x0 + x1) * 0.5, (y0 + y1) * 0.5, (z0 + z1) * 0.5
        sx, sy, sz = max(0.0001, x1 - x0), max(0.0001, y1 - y0), max(0.0001, z1 - z0)

        if active is not None:
            if active.type in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'LATTICE'):
                active.dimensions = (sx, sy, sz)
                context.view_layer.update()
            bmin, bmax = _world_bbox(active)
            cur_center = (bmin + bmax) * 0.5
            offset = mathutils.Vector((cx, cy, cz)) - cur_center
            active.location += offset
            context.view_layer.update()
            context.scene.cursor.location = mathutils.Vector((cx, cy, cz))
            _sync_viewport(context)
            _speak_3d(
                f"Установлено для {_obj_display_name(active)}: X от {_fmt_num(x0)} до {_fmt_num(x1)}, "
                f"Y от {_fmt_num(y0)} до {_fmt_num(y1)}, Z от {_fmt_num(z0)} до {_fmt_num(z1)}. "
                f"Размер {_fmt_num(sx)} на {_fmt_num(sy)} на {_fmt_num(sz)} м. Шаг: {_format_step_human(_state['step_size'])}",
                1
            )
        else:
            context.scene.cursor.location = mathutils.Vector((cx, cy, cz))
            _sync_viewport(context)
            _speak_3d(
                f"Курсор перемещён на X {_fmt_num(cx)}, Y {_fmt_num(cy)}, Z {_fmt_num(cz)}. "
                f"Шаг: {_format_step_human(_state['step_size'])}",
                1
            )
        return {'FINISHED'}

class ACCESS_OT_delete_active(bpy.types.Operator):
    bl_idname = "view3d.access_delete_active"
    bl_label = "Удалить выбранный объект"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        if context.mode != 'OBJECT':
            return {'PASS_THROUGH'}
        active = context.view_layer.objects.active if context.view_layer else None
        if active is None:
            _speak_3d("Нет выбранного объекта для удаления", 1)
            return {'FINISHED'}
        name = active.name
        disp = _obj_display_name(active)
        if _state["grabbed_name"] == name:
            _state["grabbed_name"] = ""
        active.select_set(True)
        bpy.ops.object.delete(use_global=False, confirm=False)
        _speak_3d(f"Удалён объект: {disp}", 1)
        return {'FINISHED'}

class ACCESS_OT_frame_step(bpy.types.Operator):
    bl_idname = "view3d.access_frame_step"
    bl_label = "Шаг по кадрам анимации"

    delta: bpy.props.IntProperty(default=1)

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        scn = context.scene
        new_f = max(scn.frame_start, min(scn.frame_end, scn.frame_current + self.delta))
        scn.frame_set(new_f)
        msg = f"Кадр {scn.frame_current} из {scn.frame_end}"
        active = context.view_layer.objects.active if context.view_layer else None
        if active is not None:
            loc = active.location
            msg += f". {_obj_display_name(active)}: X {_fmt_num(loc.x)}, Y {_fmt_num(loc.y)}, Z {_fmt_num(loc.z)}"
        _speak_3d(msg, 1)
        return {'FINISHED'}

class ACCESS_OT_toggle_edit_mode(bpy.types.Operator):
    bl_idname = "view3d.access_toggle_edit_mode"
    bl_label = "Переключить режим объекта и редактирования"

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        active = context.view_layer.objects.active if context.view_layer else None
        if active is None or active.type not in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'ARMATURE', 'LATTICE'):
            return {'PASS_THROUGH'}
        try:
            bpy.ops.object.editmode_toggle()
            disp = _obj_display_name(active)
            if context.mode == 'OBJECT':
                _speak_3d(f"Объектный режим: {disp}", 1)
            else:
                _speak_3d(f"Режим редактирования вершин и граней: {disp}. Нажмите Tab или Escape для возврата в Объектный режим", 1)
            return {'FINISHED'}
        except Exception:
            return {'PASS_THROUGH'}

class ACCESS_OT_escape_scene(bpy.types.Operator):
    bl_idname = "view3d.access_escape_scene"
    bl_label = "Выход в 3D-сцену"

    def execute(self, context):
        if not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
                _speak_3d("Возврат в Объектный режим. 3D-сцена", 1)
            except Exception:
                pass
        return {'PASS_THROUGH'}

class ACCESS_OT_set_label(bpy.types.Operator):
    bl_idname = "view3d.access_set_label"
    bl_label = "Задать метку объекта"
    bl_options = {'REGISTER', 'UNDO'}

    label_text: bpy.props.StringProperty(name="Метка объекта", default="")

    def invoke(self, context, event):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        active = context.view_layer.objects.active if context.view_layer else None
        if active is None:
            _speak_3d("Нет выбранного объекта для метки", 1)
            return {'FINISHED'}
        self.label_text = str(active.get("access_label", ""))
        _speak_3d(
            f"Метка для {active.name}. Введите текст и нажмите Enter, пустое поле удаляет метку",
            1
        )
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        if not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        active = context.view_layer.objects.active if context.view_layer else None
        if active is None:
            _speak_3d("Нет выбранного объекта", 1)
            return {'CANCELLED'}
        val = self.label_text.strip()
        if val:
            active["access_label"] = val
            _speak_3d(f"Сохранена метка: {val} для {active.name}", 1)
        else:
            if "access_label" in active:
                del active["access_label"]
            _speak_3d(f"Метка удалена для {active.name}", 1)
        return {'FINISHED'}

def _dir_vec_ru(vec, ref_right=None, ref_fwd=None):
    v = vec.normalized() if vec.length > 1e-6 else mathutils.Vector((0.0, 0.0, 1.0))
    parts = []
    if abs(v.z) >= 0.3:
        parts.append("сверху" if v.z > 0 else "снизу")
    if ref_right is not None and ref_fwd is not None:
        rx = v.dot(ref_right)
        fy = v.dot(ref_fwd)
        if abs(rx) >= 0.25:
            parts.append("справа" if rx > 0 else "слева")
        if abs(fy) >= 0.3:
            parts.append("спереди" if fy > 0 else "сзади")
    else:
        if abs(v.x) >= 0.25:
            parts.append("справа" if v.x > 0 else "слева")
        if abs(v.y) >= 0.25:
            parts.append("сзади" if v.y > 0 else "спереди")
    return "-".join(parts) if parts else "спереди"

def _ray_dir_ru(vec, ref_right=None, ref_fwd=None):
    v = vec.normalized() if vec.length > 1e-6 else mathutils.Vector((0.0, 0.0, -1.0))
    parts = []
    if v.z <= -0.35:
        parts.append("вниз")
    elif v.z >= 0.35:
        parts.append("вверх")
    if ref_right is not None and ref_fwd is not None:
        r_xy = mathutils.Vector((ref_right.x, ref_right.y, 0.0))
        f_xy = mathutils.Vector((ref_fwd.x, ref_fwd.y, 0.0))
        rx = v.dot(r_xy.normalized()) if r_xy.length > 1e-6 else v.x
        fy = v.dot(f_xy.normalized()) if f_xy.length > 1e-6 else v.y
        if abs(rx) >= 0.28:
            parts.append("вправо" if rx > 0 else "влево")
        if abs(fy) >= 0.28:
            parts.append("вперёд" if fy > 0 else "назад")
    else:
        if abs(v.x) >= 0.28:
            parts.append("вправо" if v.x > 0 else "влево")
        if abs(v.y) >= 0.28:
            parts.append("вперёд" if v.y > 0 else "назад")
    if not parts:
        return "прямо вниз" if v.z < 0 else "вперёд"
    return "-".join(parts)

def _frame_pos_ru(u, v):
    if 0.35 <= u <= 0.65 and 0.35 <= v <= 0.65:
        return "по центру"
    h = "слева" if u < 0.38 else ("справа" if u > 0.62 else "по центру горизонтали")
    vert = "сверху" if v > 0.62 else ("снизу" if v < 0.38 else "")
    return f"{vert} {h}".strip()

def _face_side_ru(norm_w):
    ax, ay, az = abs(norm_w.x), abs(norm_w.y), abs(norm_w.z)
    if az >= ax and az >= ay:
        return "верхняя грань" if norm_w.z > 0 else "нижняя грань"
    if ax >= ay:
        return "правая грань" if norm_w.x > 0 else "левая грань"
    return "дальняя грань" if norm_w.y > 0 else "передняя грань"

def _select_camera(context):
    grabbed = _get_grabbed_obj(context)
    if grabbed is not None and grabbed.type == 'CAMERA':
        return grabbed
    active = context.view_layer.objects.active if context.view_layer else None
    if active is not None and active.type == 'CAMERA':
        return active
    scene = context.scene
    return scene.camera or next((o for o in scene.objects if o.type == 'CAMERA'), None)

def _camera_cone_report(context, detailed, target_cam=None):
    scene = context.scene
    depsgraph = context.evaluated_depsgraph_get()
    cam = target_cam or _select_camera(context)
    if cam is None:
        return "Камера в сцене не найдена"

    fov_x = round(math.degrees(cam.data.angle_x), 1)
    fov_y = round(math.degrees(cam.data.angle_y), 1)
    lens_mm = round(cam.data.lens, 1)
    cam_hdr = f"Камера {_obj_display_name(cam)} (обзор {fov_x}×{fov_y}°, {lens_mm} мм)"

    corners = cam.data.view_frame(scene=scene)
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    z_pl = sum(c.z for c in corners) / float(len(corners))
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)

    mw = cam.matrix_world
    cam_origin = mw.translation
    cam_fwd = (mw.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
    grid_n = 15
    total_rays = grid_n * grid_n
    hit_stats = {}
    center_obj = None

    for iy in range(grid_n):
        v = iy / float(grid_n - 1)
        ly = y0 + v * (y1 - y0)
        for ix in range(grid_n):
            u = ix / float(grid_n - 1)
            lx = x0 + u * (x1 - x0)
            if cam.data.type == 'ORTHO':
                plane_pt = cam_origin + (mw.to_3x3() @ mathutils.Vector((lx, ly, 0.0)))
                r_orig = plane_pt + cam_fwd * cam.data.clip_start
                r_dir = cam_fwd
            else:
                pt_world = mw @ mathutils.Vector((lx, ly, z_pl))
                r_orig = cam_origin
                r_dir = (pt_world - cam_origin).normalized()
            hit, hloc, _, _, hobj, _ = scene.ray_cast(depsgraph, r_orig, r_dir, distance=cam.data.clip_end)
            if not hit or hobj is None:
                continue
            dist = (hloc - cam_origin).length
            st = hit_stats.get(hobj.name)
            if st is None:
                st = {"obj": hobj, "hits": 0, "sum_u": 0.0, "sum_v": 0.0, "min_dist": dist, "border": False}
                hit_stats[hobj.name] = st
            st["hits"] += 1
            st["sum_u"] += u
            st["sum_v"] += v
            st["min_dist"] = min(st["min_dist"], dist)
            if ix in (0, grid_n - 1) or iy in (0, grid_n - 1):
                st["border"] = True
            if ix == grid_n // 2 and iy == grid_n // 2:
                center_obj = hobj

    parts = []
    if not hit_stats:
        parts.append(f"{cam_hdr}: в кадре пусто")
    else:
        ordered = sorted(hit_stats.values(), key=lambda s: (-s["hits"], s["min_dist"]))
        limit_in = len(ordered) if detailed else min(4, len(ordered))
        in_items = []
        for s in ordered[:limit_in]:
            o = s["obj"]
            pct = max(1, round(s["hits"] * 100.0 / total_rays))
            au = s["sum_u"] / s["hits"]
            av = s["sum_v"] / s["hits"]
            pos_str = "по центру кадра" if (center_obj == o or (0.35 <= au <= 0.65 and 0.35 <= av <= 0.65)) else _frame_pos_ru(au, av)
            clipped = s["border"]
            if not clipped and hasattr(o, "bound_box") and o.bound_box:
                for c in o.bound_box:
                    ndc = bpy_extras.object_utils.world_to_camera_view(scene, cam, o.matrix_world @ mathutils.Vector(c))
                    if ndc.z > 0.0 and (ndc.x < 0.0 or ndc.x > 1.0 or ndc.y < 0.0 or ndc.y > 1.0):
                        clipped = True
                        break
            clip_txt = ", обрезан краем" if clipped else ""
            in_items.append(f"{pos_str}: {_obj_display_name(o)} ({pct}% кадра, {_fmt_num(s['min_dist'])} м{clip_txt})")
        parts.append(f"{cam_hdr}: " + "; ".join(in_items))

    missed = []
    for o in scene.objects:
        if o.type in ('CAMERA', 'LIGHT', 'EMPTY') or o.name in hit_stats:
            continue
        pts = [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box] if (hasattr(o, "bound_box") and o.bound_box) else [o.location]
        ndcs = [bpy_extras.object_utils.world_to_camera_view(scene, cam, p) for p in pts]
        if all(n.z <= 0.0 for n in ndcs):
            missed.append(f"{_obj_display_name(o)} (сзади за камерой)")
        elif any((n.z > 0.0 and 0.0 <= n.x <= 1.0 and 0.0 <= n.y <= 1.0) for n in ndcs):
            missed.append(f"{_obj_display_name(o)} (заслонён другими объектами)")
        else:
            cx_n = sum(n.x for n in ndcs) / len(ndcs)
            cy_n = sum(n.y for n in ndcs) / len(ndcs)
            side = []
            if cx_n < 0.0:
                side.append("слева за экраном")
            elif cx_n > 1.0:
                side.append("справа за экраном")
            if cy_n < 0.0:
                side.append("ниже экрана")
            elif cy_n > 1.0:
                side.append("выше экрана")
            missed.append(f"{_obj_display_name(o)} ({', '.join(side) if side else 'вне кадра'})")
    if missed:
        lim = len(missed) if detailed else min(3, len(missed))
        parts.append("В кадр не попало: " + "; ".join(missed[:lim]))
    return ". ".join(parts)

def _span_interval_ru(pts):
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    spans = [("X", min(xs), max(xs)), ("Y", min(ys), max(ys)), ("Z", min(zs), max(zs))]
    axis_lbl, smin, smax = max(spans, key=lambda t: t[2] - t[1])
    if smax - smin > 0.02:
        return f"на интервале {axis_lbl} от {_fmt_num(smin)} до {_fmt_num(smax)} м"
    p0 = pts[0]
    return f"в точке X {_fmt_num(p0.x)}, Y {_fmt_num(p0.y)}, Z {_fmt_num(p0.z)} м"

def _raycast_light_forward(scene, depsgraph, r_orig, r_dir, max_dist=1000.0):
    hit1, loc1, norm1, _, obj1, _ = scene.ray_cast(depsgraph, r_orig, r_dir, distance=max_dist)
    if not hit1 or obj1 is None:
        return None
    # Continue the exact same ray past Hit 1 (skipping exit faces of obj1) to find Hit 2 ("Тень")
    p_cont = loc1 + r_dir * 0.002
    hit2_obj = None
    hit2_loc = None
    for _ in range(8):
        h2, l2, _, _, o2, _ = scene.ray_cast(depsgraph, p_cont, r_dir, distance=max_dist)
        if not h2 or o2 is None:
            break
        if o2 != obj1:
            hit2_obj = o2
            hit2_loc = l2
            break
        p_cont = l2 + r_dir * 0.002
    return (obj1, loc1, norm1, hit2_obj, hit2_loc)

def _lights_shadow_report(context, detailed, target_light=None):
    scene = context.scene
    depsgraph = context.evaluated_depsgraph_get()
    lights = [o for o in scene.objects if o.type == 'LIGHT']
    if not lights:
        return "В сцене нет источников света"
    meshes = [o for o in scene.objects if o.type == 'MESH']
    if not meshes:
        return f"Источников света: {len(lights)}, геометрии для теней нет"

    if target_light is not None and target_light.type == 'LIGHT':
        target_lights = [target_light]
    else:
        grabbed = _get_grabbed_obj(context)
        active = context.view_layer.objects.active if context.view_layer else None
        focus_light = grabbed if (grabbed is not None and grabbed.type == 'LIGHT') else (active if (active is not None and active.type == 'LIGHT') else None)
        if focus_light is not None:
            ordered_lights = [focus_light] + [l for l in lights if l != focus_light]
            target_lights = ordered_lights if detailed else [focus_light]
        else:
            target_lights = lights if detailed else lights[:2]

    cam = _select_camera(context)
    if cam is not None:
        ref_right = (cam.matrix_world.to_3x3() @ mathutils.Vector((1.0, 0.0, 0.0))).normalized()
        ref_fwd = (cam.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
    else:
        ref_right = mathutils.Vector((1.0, 0.0, 0.0))
        ref_fwd = mathutils.Vector((0.0, 1.0, 0.0))

    # Gather world bounding points of meshes for SUN parallel ray sweep
    mesh_pts_w = []
    for o in meshes:
        if hasattr(o, "bound_box") and o.bound_box:
            mesh_pts_w.extend([o.matrix_world @ mathutils.Vector(c) for c in o.bound_box])
        else:
            mesh_pts_w.append(o.location.copy())

    reports = []
    for lt in target_lights:
        ldata = lt.data
        mw = lt.matrix_world
        lt_orig = mw.translation
        rot3 = mw.to_3x3()
        emit_dir = (rot3 @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
        lt_right = (rot3 @ mathutils.Vector((1.0, 0.0, 0.0))).normalized()
        lt_up = (rot3 @ mathutils.Vector((0.0, 1.0, 0.0))).normalized()

        rays = []
        if ldata.type == 'SPOT':
            cone_deg = round(math.degrees(ldata.spot_size), 1)
            l_desc = f"{_obj_display_name(lt)} (Прожектор, угол {cone_deg}°) на X {_fmt_num(lt_orig.x)}, Y {_fmt_num(lt_orig.y)}, Z {_fmt_num(lt_orig.z)}, светит {_ray_dir_ru(emit_dir, ref_right, ref_fwd)}"
            half_ang = max(0.01, ldata.spot_size * 0.5)
            rays.append((lt_orig, emit_dir))
            for frac in (0.25, 0.52, 0.78, 0.97):
                theta = min(math.pi * 0.495, half_ang * frac)
                for k in range(12):
                    phi = (2.0 * math.pi * k) / 12.0
                    d = (emit_dir * math.cos(theta) + (lt_right * math.cos(phi) + lt_up * math.sin(phi)) * math.sin(theta)).normalized()
                    rays.append((lt_orig, d))
        elif ldata.type == 'AREA':
            spread_rad = getattr(ldata, 'spread', math.pi)
            cone_deg = round(math.degrees(spread_rad), 1)
            l_desc = f"{_obj_display_name(lt)} (Площадной свет, угол {cone_deg}°) на X {_fmt_num(lt_orig.x)}, Y {_fmt_num(lt_orig.y)}, Z {_fmt_num(lt_orig.z)}, светит {_ray_dir_ru(emit_dir, ref_right, ref_fwd)}"
            half_ang = max(0.02, min(math.pi * 0.48, spread_rad * 0.5))
            rays.append((lt_orig, emit_dir))
            for frac in (0.25, 0.52, 0.78, 0.97):
                theta = half_ang * frac
                for k in range(12):
                    phi = (2.0 * math.pi * k) / 12.0
                    d = (emit_dir * math.cos(theta) + (lt_right * math.cos(phi) + lt_up * math.sin(phi)) * math.sin(theta)).normalized()
                    rays.append((lt_orig, d))
        elif ldata.type == 'POINT':
            l_desc = f"{_obj_display_name(lt)} (Точечный, обзор 360°) на X {_fmt_num(lt_orig.x)}, Y {_fmt_num(lt_orig.y)}, Z {_fmt_num(lt_orig.z)}"
            golden = math.pi * (3.0 - math.sqrt(5.0))
            for i in range(64):
                yy = 1.0 - (i / 63.0) * 2.0
                r_xy = math.sqrt(max(0.0, 1.0 - yy * yy))
                phi = golden * i
                d = (lt_right * (math.cos(phi) * r_xy) + lt_up * (math.sin(phi) * r_xy) + (-emit_dir) * yy).normalized()
                rays.append((lt_orig, d))
        else:
            sun_deg = round(math.degrees(ldata.angle), 2)
            l_desc = f"{_obj_display_name(lt)} (Солнце, угол диска {sun_deg}°) светит {_ray_dir_ru(emit_dir, ref_right, ref_fwd)}"
            us = [p.dot(lt_right) for p in mesh_pts_w]
            vs = [p.dot(lt_up) for p in mesh_pts_w]
            ws = [p.dot(emit_dir) for p in mesh_pts_w]
            u0, u1 = min(us) - 0.5, max(us) + 0.5
            v0, v1 = min(vs) - 0.5, max(vs) + 0.5
            w_start = min(ws) - 10.0
            for iy in range(8):
                vv = v0 + (iy / 7.0) * (v1 - v0)
                for ix in range(8):
                    uu = u0 + (ix / 7.0) * (u1 - u0)
                    orig = lt_right * uu + lt_up * vv + emit_dir * w_start
                    rays.append((orig, emit_dir))

        lit_hits = {}
        shadows = {}
        floor_shadows = {}
        for r_orig, r_dir in rays:
            res = _raycast_light_forward(scene, depsgraph, r_orig + r_dir * 0.002, r_dir)
            if res is None:
                continue
            obj1, loc1, norm1, obj2, loc2 = res
            st1 = lit_hits.get(obj1.name)
            if st1 is None:
                st1 = {"obj": obj1, "pts": [], "norms": mathutils.Vector((0.0, 0.0, 0.0))}
                lit_hits[obj1.name] = st1
            st1["pts"].append(loc1)
            st1["norms"] += norm1

            if obj2 is not None:
                key = (obj1.name, obj2.name)
                sh = shadows.get(key)
                if sh is None:
                    sh = [obj1, obj2, []]
                    shadows[key] = sh
                sh[2].append(loc2)
            elif r_dir.z < -0.02 and loc1.z > 0.02:
                t_g = -loc1.z / r_dir.z
                if 0.0 < t_g < 200.0:
                    g_pt = loc1 + r_dir * t_g
                    floor_shadows.setdefault(obj1.name, [obj1, []])[1].append(g_pt)

        l_parts = [l_desc]
        if lit_hits:
            lit_sorted = sorted(lit_hits.values(), key=lambda x: -len(x["pts"]))
            lit_msgs = []
            for st in lit_sorted[:(5 if detailed else 3)]:
                o = st["obj"]
                side_ru = _face_side_ru(st["norms"])
                span_ru = _span_interval_ru(st["pts"])
                lit_msgs.append(f"{_obj_display_name(o)} ({side_ru}, {span_ru})")
            l_parts.append("Свет (1-е касание) падает на: " + "; ".join(lit_msgs))
        else:
            l_parts.append("Луч света в пределах конуса не попадает ни на один объект")

        if shadows:
            sh_list = sorted(shadows.values(), key=lambda x: -len(x[2]))
            sh_msgs = []
            for blocker, rec, sh_pts in sh_list[:(4 if detailed else 2)]:
                sh_msgs.append(f"Тень от «{_obj_display_name(blocker)}» падает на «{_obj_display_name(rec)}» {_span_interval_ru(sh_pts)}")
            l_parts.extend(sh_msgs)
        elif floor_shadows:
            fl_list = sorted(floor_shadows.values(), key=lambda x: -len(x[1]))
            for blocker, fl_pts in fl_list[:(3 if detailed else 1)]:
                l_parts.append(f"Тень от «{_obj_display_name(blocker)}» проецируется до уровня пола Z 0 {_span_interval_ru(fl_pts)}")
        reports.append(". ".join(l_parts))
    return ". ".join(reports)

def _collect_light_rays(lt, meshes):
    ldata = lt.data
    mw = lt.matrix_world
    lt_orig = mw.translation
    rot3 = mw.to_3x3()
    emit_dir = (rot3 @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
    lt_right = (rot3 @ mathutils.Vector((1.0, 0.0, 0.0))).normalized()
    lt_up = (rot3 @ mathutils.Vector((0.0, 1.0, 0.0))).normalized()

    rays = []
    if ldata.type == 'SPOT':
        half_ang = max(0.01, ldata.spot_size * 0.5)
        rays.append((lt_orig, emit_dir))
        for frac in (0.25, 0.52, 0.78, 0.97):
            theta = min(math.pi * 0.495, half_ang * frac)
            for k in range(12):
                phi = (2.0 * math.pi * k) / 12.0
                d = (emit_dir * math.cos(theta) + (lt_right * math.cos(phi) + lt_up * math.sin(phi)) * math.sin(theta)).normalized()
                rays.append((lt_orig, d))
    elif ldata.type == 'AREA':
        spread_rad = getattr(ldata, 'spread', math.pi)
        half_ang = max(0.02, min(math.pi * 0.48, spread_rad * 0.5))
        rays.append((lt_orig, emit_dir))
        for frac in (0.25, 0.52, 0.78, 0.97):
            theta = half_ang * frac
            for k in range(12):
                phi = (2.0 * math.pi * k) / 12.0
                d = (emit_dir * math.cos(theta) + (lt_right * math.cos(phi) + lt_up * math.sin(phi)) * math.sin(theta)).normalized()
                rays.append((lt_orig, d))
    elif ldata.type == 'POINT':
        golden = math.pi * (3.0 - math.sqrt(5.0))
        for i in range(64):
            yy = 1.0 - (i / 63.0) * 2.0
            r_xy = math.sqrt(max(0.0, 1.0 - yy * yy))
            phi = golden * i
            d = (lt_right * (math.cos(phi) * r_xy) + lt_up * (math.sin(phi) * r_xy) + (-emit_dir) * yy).normalized()
            rays.append((lt_orig, d))
    else:
        mesh_pts_w = []
        for o in meshes:
            if hasattr(o, "bound_box") and o.bound_box:
                mesh_pts_w.extend([o.matrix_world @ mathutils.Vector(c) for c in o.bound_box])
            else:
                mesh_pts_w.append(o.location.copy())
        if mesh_pts_w:
            us = [p.dot(lt_right) for p in mesh_pts_w]
            vs = [p.dot(lt_up) for p in mesh_pts_w]
            ws = [p.dot(emit_dir) for p in mesh_pts_w]
            u0, u1 = min(us) - 0.5, max(us) + 0.5
            v0, v1 = min(vs) - 0.5, max(vs) + 0.5
            w_start = min(ws) - 10.0
            for iy in range(8):
                vv = v0 + (iy / 7.0) * (v1 - v0)
                for ix in range(8):
                    uu = u0 + (ix / 7.0) * (u1 - u0)
                    orig = lt_right * uu + lt_up * vv + emit_dir * w_start
                    rays.append((orig, emit_dir))
    return rays

def _object_light_camera_report(context, target):
    scene = context.scene
    depsgraph = context.evaluated_depsgraph_get()
    oname = _obj_display_name(target)
    parts = [f"Объект «{oname}»"]

    # 1. Where target appears in active camera frame
    cam = _select_camera(context)
    if cam is not None:
        corners = cam.data.view_frame(scene=scene)
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        z_pl = sum(c.z for c in corners) / float(len(corners))
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        mw = cam.matrix_world
        cam_origin = mw.translation
        cam_fwd = (mw.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
        fov_x = round(math.degrees(cam.data.angle_x), 1)
        fov_y = round(math.degrees(cam.data.angle_y), 1)

        hits = 0
        sum_u = 0.0
        sum_v = 0.0
        min_d = 1e9
        clipped = False
        grid_n = 15
        for iy in range(grid_n):
            v = iy / float(grid_n - 1)
            ly = y0 + v * (y1 - y0)
            for ix in range(grid_n):
                u = ix / float(grid_n - 1)
                lx = x0 + u * (x1 - x0)
                if cam.data.type == 'ORTHO':
                    plane_pt = cam_origin + (mw.to_3x3() @ mathutils.Vector((lx, ly, 0.0)))
                    r_orig = plane_pt + cam_fwd * cam.data.clip_start
                    r_dir = cam_fwd
                else:
                    pt_world = mw @ mathutils.Vector((lx, ly, z_pl))
                    r_orig = cam_origin
                    r_dir = (pt_world - cam_origin).normalized()
                hit, hloc, _, _, hobj, _ = scene.ray_cast(depsgraph, r_orig, r_dir, distance=cam.data.clip_end)
                if hit and hobj == target:
                    hits += 1
                    sum_u += u
                    sum_v += v
                    min_d = min(min_d, (hloc - cam_origin).length)
                    if ix in (0, grid_n - 1) or iy in (0, grid_n - 1):
                        clipped = True
        if hits > 0:
            pct = max(1, round(hits * 100.0 / (grid_n * grid_n)))
            pos_str = _frame_pos_ru(sum_u / hits, sum_v / hits)
            clip_txt = ", обрезан краем" if clipped else ""
            parts.append(f"В камере «{_obj_display_name(cam)}» ({fov_x}×{fov_y}°): {pos_str}, {pct}% кадра, {_fmt_num(min_d)} м{clip_txt}")
        else:
            parts.append(f"В кадр камеры «{_obj_display_name(cam)}» сейчас не попадает")

    # 2. Direct light hitting target & shadow cast by target
    lights = [o for o in scene.objects if o.type == 'LIGHT']
    meshes = [o for o in scene.objects if o.type == 'MESH']
    if lights and meshes:
        lit_msgs = []
        cast_msgs = []
        shaded_by = []
        for lt in lights:
            rays = _collect_light_rays(lt, meshes)
            lit_pts = []
            lit_norms = mathutils.Vector((0.0, 0.0, 0.0))
            cast_recs = {}
            cast_floor = []
            for r_orig, r_dir in rays:
                res = _raycast_light_forward(scene, depsgraph, r_orig + r_dir * 0.002, r_dir)
                if res is None:
                    continue
                obj1, loc1, norm1, obj2, loc2 = res
                if obj1 == target:
                    lit_pts.append(loc1)
                    lit_norms += norm1
                    if obj2 is not None:
                        cast_recs.setdefault(obj2.name, [obj2, []])[1].append(loc2)
                    elif r_dir.z < -0.02 and loc1.z > 0.02:
                        t_g = -loc1.z / r_dir.z
                        if 0.0 < t_g < 200.0:
                            cast_floor.append(loc1 + r_dir * t_g)
                elif obj2 == target:
                    shaded_by.append(_obj_display_name(obj1))

            if lit_pts:
                lit_msgs.append(f"от «{_obj_display_name(lt)}» ({_face_side_ru(lit_norms)}, {_span_interval_ru(lit_pts)})")
            if cast_recs:
                for rec, spts in sorted(cast_recs.values(), key=lambda x: -len(x[1])):
                    cast_msgs.append(f"на «{_obj_display_name(rec)}» {_span_interval_ru(spts)}")
            elif cast_floor:
                cast_msgs.append(f"до уровня пола Z 0 {_span_interval_ru(cast_floor)}")

        if lit_msgs:
            parts.append("Освещён: " + "; ".join(lit_msgs[:3]))
        elif shaded_by:
            parts.append(f"В тени (заслонён от света объектом «{shaded_by[0]}»)")
        else:
            parts.append("Прямой свет от ламп сейчас на объект не попадает")

        if cast_msgs:
            parts.append("Тень от него падает: " + "; ".join(cast_msgs[:3]))

    return ". ".join(parts)

def _object_under_cursor_or_active(context):
    grabbed = _get_grabbed_obj(context)
    if grabbed is not None:
        return grabbed
    cur = context.scene.cursor.location
    candidates = []
    for o in context.scene.objects:
        bmin, bmax = _world_bbox(o)
        dx = max(0.0, max(bmin.x - cur.x, cur.x - bmax.x))
        dy = max(0.0, max(bmin.y - cur.y, cur.y - bmax.y))
        dz = max(0.0, max(bmin.z - cur.z, cur.z - bmax.z))
        d_box = math.sqrt(dx * dx + dy * dy + dz * dz)
        if d_box <= 0.15:
            candidates.append((d_box, (o.location - cur).length, o))
    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][2]
    return context.view_layer.objects.active if context.view_layer else None

class ACCESS_OT_camera_light_summary(bpy.types.Operator):
    bl_idname = "view3d.access_camera_light_summary"
    bl_label = "Сводка кадра камеры и освещения"

    detailed: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        if self.detailed:
            cam_msg = _camera_cone_report(context, True)
            light_msg = _lights_shadow_report(context, True)
            _speak_3d(f"{cam_msg}. {light_msg}", 1)
            return {'FINISHED'}

        focus = _object_under_cursor_or_active(context)
        if focus is None:
            cam_msg = _camera_cone_report(context, False)
            light_msg = _lights_shadow_report(context, False)
            _speak_3d(f"{cam_msg}. {light_msg}", 1)
        elif focus.type == 'CAMERA':
            _speak_3d(_camera_cone_report(context, False, target_cam=focus), 1)
        elif focus.type == 'LIGHT':
            _speak_3d(_lights_shadow_report(context, False, target_light=focus), 1)
        else:
            _speak_3d(_object_light_camera_report(context, focus), 1)
        return {'FINISHED'}

class ACCESS_OT_render_frame(bpy.types.Operator):
    bl_idname = "view3d.access_render_frame"
    bl_label = "Сделать снимок камеры и озвучить кадр"

    align_to_view: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        cam = _select_camera(context)
        if cam is None:
            _speak_3d("Камера в сцене не найдена", 1)
            return {'FINISHED'}
        if self.align_to_view:
            fwd, right = _view_forward_right()
            up = right.cross(fwd)
            if up.length < 1e-6:
                up = mathutils.Vector((0.0, 0.0, 1.0))
            else:
                up.normalize()
            rot_mat = mathutils.Matrix((right.normalized(), up, -fwd.normalized())).transposed()
            cam.location = context.scene.cursor.location.copy()
            cam.rotation_euler = rot_mat.to_euler(cam.rotation_mode if cam.rotation_mode in ('XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX') else 'XYZ')
            context.scene.camera = cam
            context.view_layer.update()

        out_path = os.path.join(tempfile.gettempdir(), "blender_nvda_render.png")
        context.scene.render.filepath = out_path
        render_status = ""
        try:
            bpy.ops.render.render(write_still=True)
            render_status = f"Снимок сохранён в {out_path}"
        except Exception as exc:
            render_status = f"Проверка ракурса без сохранения файла ({exc})"

        cam_msg = _camera_cone_report(context, True)
        light_msg = _lights_shadow_report(context, True)
        _speak_3d(f"{render_status}. {cam_msg}. {light_msg}", 1)
        return {'FINISHED'}

def _trace_cut_loops(cut_edges):
    adj = {}
    for e in cut_edges:
        v0, v1 = e.verts[0], e.verts[1]
        adj.setdefault(v0, []).append(v1)
        adj.setdefault(v1, []).append(v0)
    visited = set()
    loops = []
    for start in list(adj.keys()):
        if start in visited:
            continue
        comp = []
        queue = [start]
        visited.add(start)
        while queue:
            cur = queue.pop()
            comp.append(cur)
            for nb in adj.get(cur, ()):
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)
        closed = all(len(adj.get(v, ())) >= 2 for v in comp)
        # Order chain when possible for perimeter sampling
        ordered = [comp[0]]
        used = {comp[0]}
        cur = comp[0]
        while True:
            nxt = next((nb for nb in adj.get(cur, ()) if nb not in used), None)
            if nxt is None:
                break
            ordered.append(nxt)
            used.add(nxt)
            cur = nxt
        for v in comp:
            if v not in used:
                ordered.append(v)
        loops.append(([v.co.copy() for v in ordered], closed))
    return loops

def _point_in_poly_2d(px, py, poly):
    inside = False
    n = len(poly)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / ((yj - yi) if abs(yj - yi) > 1e-12 else 1e-12) + xi):
            inside = not inside
        j = i
    return inside

def _poly_area_2d(pts):
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) * 0.5

def _build_polytree_2d(loops_2d):
    ordered = sorted(loops_2d, key=lambda x: -x[0])
    nodes = []
    for i, (area, eq_r, c2, pts, is_closed) in enumerate(ordered):
        parent = -1
        probe = pts[0] if pts else (float(c2[0]), float(c2[1]))
        for j in range(i - 1, -1, -1):
            if _point_in_poly_2d(probe[0], probe[1], ordered[j][3]):
                parent = j
                break
        depth = 0 if parent == -1 else (nodes[parent]["depth"] + 1)
        node = {
            "idx": i,
            "parent": parent,
            "depth": depth,
            "children": [],
            "area": area,
            "eq_r": eq_r,
            "c2": c2,
            "pts": pts,
            "closed": is_closed,
        }
        nodes.append(node)
        if parent != -1:
            nodes[parent]["children"].append(i)
    return nodes

def _efa_kuhl_giardina(pts_2d, n_harm=36):
    if len(pts_2d) < 3:
        return None
    pts = np.asarray(pts_2d, dtype=np.float64)
    diffs = np.roll(pts, -1, axis=0) - pts
    dt = np.hypot(diffs[:, 0], diffs[:, 1])
    mask = dt > 1e-9
    if np.count_nonzero(mask) < 3:
        return None
    dx = diffs[mask, 0]
    dy = diffs[mask, 1]
    dt = dt[mask]
    t = np.concatenate(([0.0], np.cumsum(dt)))
    T = float(t[-1])
    if T < 1e-8:
        return None
    t0 = t[:-1]
    t1 = t[1:]
    dxdt = dx / dt
    dydt = dy / dt

    n = np.arange(1, n_harm + 1, dtype=np.float64)[:, None]
    fac = T / (2.0 * (math.pi ** 2) * (n[:, 0] ** 2))
    w0 = (2.0 * math.pi * n * t0[None, :]) / T
    w1 = (2.0 * math.pi * n * t1[None, :]) / T
    dcos = np.cos(w1) - np.cos(w0)
    dsin = np.sin(w1) - np.sin(w0)

    an = fac * (dcos @ dxdt)
    bn = fac * (dsin @ dxdt)
    cn = fac * (dcos @ dydt)
    dn = fac * (dsin @ dydt)

    power = np.sqrt(an * an + bn * bn + cn * cn + dn * dn)
    p1 = float(power[0])
    if p1 < 1e-8:
        return None
    m1 = np.array([[an[0], bn[0]], [cn[0], dn[0]]], dtype=np.float64)
    svals = np.linalg.svd(m1, compute_uv=False)
    maj_1 = float(svals[0])
    min_1 = float(svals[1])
    elong = maj_1 / max(1e-8, min_1)
    efa_norm = power / p1
    efa_rough = float(np.sum(efa_norm[1:]))
    return {
        "maj_1": maj_1,
        "min_1": min_1,
        "elong": elong,
        "efa_norm": efa_norm,
        "efa_rough": efa_rough,
    }

def _fft_loop_profile(pts_2d, m_bins=128):
    if len(pts_2d) < 3:
        return None
    efa = _efa_kuhl_giardina(pts_2d, n_harm=36)
    arr = np.asarray(pts_2d, dtype=np.float64)
    c = arr.mean(axis=0)
    rel = arr - c
    # Subdivide edges densely so low-poly primitives (e.g. cube = 4 cut verts) still form full waveform
    ring = []
    n = len(rel)
    sub_per_edge = max(4, 192 // max(1, n))
    for i in range(n):
        p0 = rel[i]
        p1 = rel[(i + 1) % n]
        for s in range(sub_per_edge):
            t = s / float(sub_per_edge)
            ring.append(p0 * (1.0 - t) + p1 * t)
    ring = np.asarray(ring, dtype=np.float64)
    angles = np.mod(np.arctan2(ring[:, 1], ring[:, 0]), 2.0 * math.pi)
    radii = np.hypot(ring[:, 0], ring[:, 1])
    if radii.max() < 1e-6:
        return None

    bins = [[] for _ in range(m_bins)]
    bin_idx = np.clip((angles / (2.0 * math.pi) * m_bins).astype(int), 0, m_bins - 1)
    for idx, r in zip(bin_idx, radii):
        bins[idx].append(r)

    r_uniform = np.zeros(m_bins, dtype=np.float64)
    valid = [i for i, b in enumerate(bins) if b]
    if len(valid) < 4:
        return None
    for i in valid:
        r_uniform[i] = float(np.mean(bins[i]))
    for i in range(m_bins):
        if not bins[i]:
            v_arr = np.asarray(valid, dtype=np.float64)
            r_uniform[i] = r_uniform[valid[int(np.argmin(np.minimum(np.abs(v_arr - i), m_bins - np.abs(v_arr - i))))]]

    fft_mag = np.abs(np.fft.rfft(r_uniform))
    dc = fft_mag[0]
    if dc < 1e-8:
        return None
    harm = fft_mag / dc
    h2 = float(harm[2]) if len(harm) > 2 else 0.0
    k_range = list(range(3, min(37, len(harm))))
    k_dom = max(k_range, key=lambda k: harm[k]) if k_range else 0
    h_dom = float(harm[k_dom]) if k_dom > 0 else 0.0
    max_higher = float(np.max(harm[2:min(37, len(harm))])) if len(harm) > 2 else 0.0
    return (float(dc / m_bins), h2, k_dom, h_dom, max_higher, efa)

def _euler_genus_components(bm):
    visited = set()
    comps = []
    for v0 in bm.verts:
        if v0 in visited:
            continue
        q = [v0]
        visited.add(v0)
        cverts = set()
        cedges = set()
        cfaces = set()
        while q:
            v = q.pop()
            cverts.add(v)
            for e in v.link_edges:
                cedges.add(e)
                ov = e.other_vert(v)
                if ov not in visited:
                    visited.add(ov)
                    q.append(ov)
            for f in v.link_faces:
                cfaces.add(f)
        nv = len(cverts)
        ne = len(cedges)
        nf = len(cfaces)
        has_boundary = any(len(e.link_faces) < 2 for e in cedges)
        chi = nv - ne + nf
        genus = max(0, (2 - chi) // 2) if (not has_boundary and nv >= 4 and nf >= 4) else -1
        comps.append((nv, ne, nf, chi, genus, has_boundary))
    return comps

def _blind_cavity_probe(obj_eval, mw, min_l, max_l):
    center_l = (min_l + max_l) * 0.5
    mw_inv = mw.inverted_safe()
    top_dir_l = (mw_inv.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0)))
    if top_dir_l.length < 1e-6:
        return None
    top_dir_l.normalize()

    ext_l = max_l - min_l
    span_z = max(0.05, ext_l.length * 1.2)
    w_corners = [mw @ mathutils.Vector((x, y, z))
                 for x in (min_l.x, max_l.x)
                 for y in (min_l.y, max_l.y)
                 for z in (min_l.z, max_l.z)]
    min_w_z = min(c.z for c in w_corners)
    max_w_z = max(c.z for c in w_corners)
    h_w = max(0.05, max_w_z - min_w_z)

    def _top_hit_z(xy_l):
        p_top = xy_l - top_dir_l * span_z
        hits = []
        cur_p = p_top
        for _ in range(8):
            h, loc, norm, _ = obj_eval.ray_cast(cur_p, top_dir_l)
            if not h:
                break
            hits.append((mw @ loc).z)
            cur_p = loc + top_dir_l * 1e-4
        return hits

    hits_c = _top_hit_z(center_l)
    if len(hits_c) < 2:
        return None
    z_floor = hits_c[0]
    if z_floor <= min_w_z + 0.02 * h_w or z_floor >= max_w_z - 0.10 * h_w:
        return None

    # Verify enclosing rim on all 4 cardinal quadrants (rejects tilted cones / ramps)
    rx_max = max(0.01, ext_l.x * 0.49)
    ry_max = max(0.01, ext_l.y * 0.49)
    card_rims = []
    for dx, dy in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
        best_rim_z = None
        for frac in (0.65, 0.82, 0.94, 0.98):
            off = mathutils.Vector((center_l.x + dx * rx_max * frac, center_l.y + dy * ry_max * frac, center_l.z))
            hz = _top_hit_z(off)
            if hz and (best_rim_z is None or hz[0] > best_rim_z):
                best_rim_z = hz[0]
        if best_rim_z is None or best_rim_z < z_floor + 0.08 * h_w:
            return None
        card_rims.append(best_rim_z)

    avg_rim = sum(card_rims) / len(card_rims)
    depth = avg_rim - z_floor
    return depth if depth > 0.08 * h_w else None

def _ultrasound_echo_scan(obj_eval, mw, min_pt_l, max_pt_l):
    center_l = (min_pt_l + max_pt_l) * 0.5
    diag_l = (max_pt_l - min_pt_l).length
    if diag_l < 1e-5:
        return None
    span = diag_l * 1.1
    mw3 = mw.to_3x3()

    dirs_l = []
    for dx in (-1.0, 0.0, 1.0):
        for dy in (-1.0, 0.0, 1.0):
            for dz in (-1.0, 0.0, 1.0):
                if dx == 0.0 and dy == 0.0 and dz == 0.0:
                    continue
                dirs_l.append(mathutils.Vector((dx, dy, dz)).normalized())

    wall_thicknesses = []
    cavity_gaps = []
    single_sided = 0
    for d in dirs_l:
        p = center_l - d * span
        segments = []
        for _ in range(12):
            hit, loc, norm, _ = obj_eval.ray_cast(p, d)
            if not hit:
                break
            dot = d.dot(norm)
            segments.append((loc.copy(), dot))
            p = loc + d * 1e-4

        if len(segments) >= 2:
            if segments[0][1] < 0.0 and segments[1][1] > 0.0:
                w_m = (mw3 @ (segments[1][0] - segments[0][0])).length
                wall_thicknesses.append(w_m)
                if len(segments) >= 4 and segments[2][1] < 0.0 and segments[3][1] > 0.0:
                    gap_m = (mw3 @ (segments[2][0] - segments[1][0])).length
                    if gap_m > 1e-4:
                        cavity_gaps.append(gap_m)
                    wall_thicknesses.append((mw3 @ (segments[3][0] - segments[2][0])).length)
        elif len(segments) == 1:
            single_sided += 1

    return {
        "walls": wall_thicknesses,
        "cavities": cavity_gaps,
        "single_sided": single_sided,
    }

def _shrinkwrap_globe_scan(context, obj, obj_eval, eval_mesh, center_w, max_r):
    bm_g = bmesh.new()
    mesh_g = None
    obj_g = None
    try:
        bmesh.ops.create_uvsphere(bm_g, u_segments=20, v_segments=10, radius=max(0.05, max_r * 1.15))
        mesh_g = bpy.data.meshes.new("_AccessTempGlobeMesh")
        bm_g.to_mesh(mesh_g)
        obj_g = bpy.data.objects.new("_AccessTempGlobeObj", mesh_g)
        context.scene.collection.objects.link(obj_g)
        obj_g.location = center_w.copy()
        mod = obj_g.modifiers.new("AccessWrap", 'SHRINKWRAP')
        mod.target = obj
        mod.wrap_method = 'NEAREST_SURFACEPOINT'

        dg = context.evaluated_depsgraph_get()
        g_eval = obj_g.evaluated_get(dg)
        w_mesh = g_eval.to_mesh()
        try:
            mw_g = g_eval.matrix_world
            mw_inv = obj.matrix_world.inverted_safe()
            pts_w = [mw_g @ v.co for v in w_mesh.vertices]
            if not pts_w:
                return "Оболочка не смогла обтянуть объект"
            radii = np.array([(p - center_w).length for p in pts_w], dtype=np.float64)
            mean_r = float(np.mean(radii))
            cv = float(np.std(radii) / max(1e-6, mean_r))

            # Cardinal poles & equator probe
            dirs_card = [
                ("Север +Z", mathutils.Vector((0.0, 0.0, 1.0))),
                ("Юг -Z", mathutils.Vector((0.0, 0.0, -1.0))),
                ("Справа +X", mathutils.Vector((1.0, 0.0, 0.0))),
                ("Слева -X", mathutils.Vector((-1.0, 0.0, 0.0))),
                ("Сзади +Y", mathutils.Vector((0.0, 1.0, 0.0))),
                ("Спереди -Y", mathutils.Vector((0.0, -1.0, 0.0))),
            ]
            card_msgs = []
            for cname, cdir in dirs_card:
                best_p = max(pts_w, key=lambda p: (p - center_w).normalized().dot(cdir) if (p - center_w).length > 1e-6 else -1.0)
                card_msgs.append(f"{cname} {_fmt_num((best_p - center_w).length)} м")

            # Drum-effect bridge test on mesh edges over object concavities
            mw3_obj = obj.matrix_world.to_3x3()
            bridge_dirs = []
            max_gap = 0.0
            for edge in w_mesh.edges:
                p0 = pts_w[edge.vertices[0]]
                p1 = pts_w[edge.vertices[1]]
                if (p1 - p0).length < max_r * 0.04:
                    continue
                mid_w = (p0 + p1) * 0.5
                ok, cp_l, _, _ = obj_eval.closest_point_on_mesh(mw_inv @ mid_w)
                if ok:
                    gap_m = (mw3_obj @ (cp_l - (mw_inv @ mid_w))).length
                    if gap_m > max_r * 0.06:
                        max_gap = max(max_gap, gap_m)
                        bridge_dirs.append(mid_w - center_w)

            card_summary = ", ".join(card_msgs)
            if cv < 0.08 and not bridge_dirs:
                return f"Режим глобуса: плотное прилегание со всех сторон, почти сфера (отклонение {round(cv * 100)}%, R около {_fmt_num(mean_r)} м; {card_summary})"
            summary = f"Режим глобуса: оболочка R от {_fmt_num(float(radii.min()))} до {_fmt_num(float(radii.max()))} м (неровность {round(cv * 100)}%; {card_summary})"
            if bridge_dirs:
                avg_dir = sum(bridge_dirs, mathutils.Vector((0.0, 0.0, 0.0)))
                summary += f". Эффект барабана (вогнутости/вырезы глубиной до {_fmt_num(max_gap)} м, преимущественно {_dir_vec_ru(avg_dir)})"
            else:
                summary += ". Глубоких впадин не обнаружено"
            return summary
        finally:
            g_eval.to_mesh_clear()
    finally:
        bm_g.free()
        if obj_g is not None:
            bpy.data.objects.remove(obj_g, do_unlink=True)
        if mesh_g is not None and mesh_g.users == 0:
            bpy.data.meshes.remove(mesh_g)

def _analyze_mesh_object(context, obj, globe_mode):
    depsgraph = context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    eval_mesh = obj_eval.to_mesh()
    bm_base = bmesh.new()
    try:
        bm_base.from_mesh(eval_mesh)
        if len(bm_base.verts) == 0:
            return f"{_obj_display_name(obj)}: пустой меш (0 вершин)"

        mw = obj.matrix_world
        verts_l = np.array([[v.co.x, v.co.y, v.co.z] for v in bm_base.verts], dtype=np.float64)
        min_l = mathutils.Vector(verts_l.min(axis=0))
        max_l = mathutils.Vector(verts_l.max(axis=0))

        verts_w = np.array([(mw @ v.co)[:] for v in bm_base.verts], dtype=np.float64)
        center_w_np = verts_w.mean(axis=0)
        center_w = mathutils.Vector(center_w_np)
        centered = verts_w - center_w_np

        if len(centered) > 15000:
            stride = max(1, len(centered) // 15000)
            pca_pts = centered[::stride]
        else:
            pca_pts = centered
        _, _, vt = np.linalg.svd(pca_pts, full_matrices=False)
        proj = centered @ vt.T
        ext = proj.max(axis=0) - proj.min(axis=0)
        l1, l2, l3 = float(ext[0]), float(ext[1]), float(ext[2])
        max_r = float(np.linalg.norm(centered, axis=1).max()) if len(centered) else 0.5

        if globe_mode:
            return f"{_obj_display_name(obj)}. " + _shrinkwrap_globe_scan(context, obj, obj_eval, eval_mesh, center_w, max_r)

        # Cube 2 topology: Euler-Poincare genus on base mesh components
        topo_comps = _euler_genus_components(bm_base)

        # Build world-space bmesh for 9-layer CT slicing along vertical axis (or primary PCA axis if flat)
        bm_base.transform(mw)
        w_min_z = float(verts_w[:, 2].min())
        w_max_z = float(verts_w[:, 2].max())
        hz = w_max_z - w_min_z
        hx = float(verts_w[:, 0].max() - verts_w[:, 0].min())
        hy = float(verts_w[:, 1].max() - verts_w[:, 1].min())

        use_vert_z = (hz >= 0.22 * max(hx, hy, hz, 1e-4) and hz > 1e-4)
        if use_vert_z:
            slice_axis = mathutils.Vector((0.0, 0.0, 1.0))
            axis_u = mathutils.Vector((1.0, 0.0, 0.0))
            axis_v = mathutils.Vector((0.0, 1.0, 0.0))
            s_min, s_max = 0.0, hz
            origin_ref = mathutils.Vector((center_w.x, center_w.y, w_min_z))
        else:
            slice_axis = mathutils.Vector(vt[0]).normalized()
            axis_u = mathutils.Vector(vt[1]).normalized()
            axis_v = mathutils.Vector(vt[2]).normalized()
            s_min, s_max = float(proj[:, 0].min()), float(proj[:, 0].max())
            origin_ref = center_w

        slice_widths = []
        slice_centers = []
        max_tree_depth = 0
        max_level1_holes = 0
        tree_wall_thickness = []
        branch_slices = 0
        fft_samples = []

        if s_max - s_min > 1e-5:
            fracs = (0.05, 0.16, 0.27, 0.38, 0.50, 0.62, 0.73, 0.84, 0.95)
            for t in fracs:
                s_val = s_min + t * (s_max - s_min)
                plane_co = origin_ref + slice_axis * s_val
                bm_s = bm_base.copy()
                try:
                    geom = bm_s.verts[:] + bm_s.edges[:] + bm_s.faces[:]
                    res = bmesh.ops.bisect_plane(bm_s, geom=geom, plane_co=plane_co, plane_no=slice_axis, clear_inner=False, clear_outer=False)
                    cut_edges = [e for e in res.get('geom_cut', []) if isinstance(e, bmesh.types.BMEdge)]
                    loops = _trace_cut_loops(cut_edges) if cut_edges else []
                finally:
                    bm_s.free()

                if not loops:
                    continue
                loops_2d = []
                for pts_loop, is_closed in loops:
                    pts2d = [((co - plane_co).dot(axis_u), (co - plane_co).dot(axis_v)) for co in pts_loop]
                    arr2 = np.asarray(pts2d, dtype=np.float64)
                    c2 = arr2.mean(axis=0)
                    eq_r = float(np.hypot(arr2[:, 0] - c2[0], arr2[:, 1] - c2[1]).mean())
                    area2 = max(_poly_area_2d(pts2d), math.pi * eq_r * eq_r * 0.05)
                    loops_2d.append((area2, eq_r, c2, pts2d, is_closed))

                tree = _build_polytree_2d(loops_2d)
                if not tree:
                    continue
                roots = [nd for nd in tree if nd["depth"] == 0]
                if len(roots) >= 2:
                    branch_slices += 1
                depth_here = max(nd["depth"] for nd in tree)
                max_tree_depth = max(max_tree_depth, depth_here)
                lvl1_cnt = sum(1 for nd in tree if nd["depth"] == 1)
                max_level1_holes = max(max_level1_holes, lvl1_cnt)
                for rt in roots:
                    for ch_idx in rt["children"]:
                        wt = rt["eq_r"] - tree[ch_idx]["eq_r"]
                        if wt > 1e-4:
                            tree_wall_thickness.append(wt)

                outer = tree[0]
                arr_out = np.asarray(outer["pts"], dtype=np.float64)
                width_here = max(outer["eq_r"] * 2.0, float((arr_out.max(axis=0) - arr_out.min(axis=0)).mean()))
                slice_widths.append((t, width_here))
                slice_centers.append((t, outer["c2"], s_val))

                if 0.25 <= t <= 0.75 or len(fft_samples) == 0:
                    prof = _fft_loop_profile(outer["pts"])
                    if prof is not None:
                        fft_samples.append(prof)

        parts = [f"Скан {_obj_display_name(obj)}: габариты {_fmt_num(hx)} × {_fmt_num(hy)} × {_fmt_num(hz)} м (оси {_fmt_num(l1)} × {_fmt_num(l2)} × {_fmt_num(l3)})"]

        # Topological Euler genus (rings, mug handles, separate shells)
        max_genus = max((c[4] for c in topo_comps), default=-1)
        if max_genus == 1:
            parts.append("топология: кольцо, тор или ручка (топологический род 1)")
        elif max_genus >= 2:
            parts.append(f"сложная замкнутая топология со сквозными петлями (род {max_genus})")
        if len(topo_comps) >= 2:
            parts.append(f"состоит из {len(topo_comps)} отдельных элементов")

        # Bottom-to-top tactile floor profile + spine bend
        if len(slice_widths) >= 5:
            w_vals = [w for _, w in slice_widths]
            w_bot = w_vals[0]
            w_q1 = w_vals[len(w_vals) // 4]
            w_mid = w_vals[len(w_vals) // 2]
            w_q3 = w_vals[(3 * len(w_vals)) // 4]
            w_top = w_vals[-1]
            w_max = max(w_vals)
            if w_max - min(w_vals) < 0.08 * max(w_max, 1e-4):
                parts.append(f"профиль снизу вверх ровный (ширина около {_fmt_num(w_mid)} м)")
            elif w_bot > w_mid * 0.92 and w_mid > w_top * 0.92 and w_top < w_bot * 0.70:
                parts.append(f"сужается кверху (конус или пирамида): у дна {_fmt_num(w_bot)}, середина {_fmt_num(w_mid)}, у верха {_fmt_num(w_top)} м")
            elif w_top > w_mid * 0.92 and w_mid > w_bot * 0.92 and w_bot < w_top * 0.70:
                parts.append(f"расширяется кверху (перевёрнутый конус): у дна {_fmt_num(w_bot)}, середина {_fmt_num(w_mid)}, у верха {_fmt_num(w_top)} м")
            elif w_mid < min(w_bot, w_top) * 0.84:
                parts.append(f"сужается посередине (песочные часы / гиперболоид): дно {_fmt_num(w_bot)}, талия {_fmt_num(w_mid)}, верх {_fmt_num(w_top)} м")
            elif w_mid > max(w_bot, w_top) * 1.14:
                parts.append(f"выпуклая посередине (бочка или шар): дно {_fmt_num(w_bot)}, середина {_fmt_num(w_mid)}, верх {_fmt_num(w_top)} м")
            else:
                parts.append(f"сложный профиль (ваза / бутылка): дно {_fmt_num(w_bot)}, четверть {_fmt_num(w_q1)}, середина {_fmt_num(w_mid)}, три четверти {_fmt_num(w_q3)}, верх {_fmt_num(w_top)} м")

        if len(slice_centers) >= 3:
            c0 = mathutils.Vector((slice_centers[0][1][0], slice_centers[0][1][1], slice_centers[0][2]))
            cm = mathutils.Vector((slice_centers[len(slice_centers) // 2][1][0], slice_centers[len(slice_centers) // 2][1][1], slice_centers[len(slice_centers) // 2][2]))
            c1 = mathutils.Vector((slice_centers[-1][1][0], slice_centers[-1][1][1], slice_centers[-1][2]))
            chord = c1 - c0
            clen = chord.length
            max_bend = 0.0
            bend_vec = mathutils.Vector((0.0, 0.0, 0.0))
            for _, c2, s_val in slice_centers[1:-1]:
                pm = mathutils.Vector((c2[0], c2[1], s_val))
                if clen > 1e-6:
                    ch_n = chord / clen
                    proj_pt = c0 + ch_n * ((pm - c0).dot(ch_n))
                    dev = pm - proj_pt
                else:
                    dev = pm - c0
                if dev.length > max_bend:
                    max_bend = dev.length
                    bend_vec = dev
            if max_bend > 0.06 * max(s_max - s_min, 1e-4):
                dev_w = axis_u * bend_vec.x + axis_v * bend_vec.y
                # 3-point circumcircle curvature radius R = (a*b*c)/(4*Area)
                a_len = (cm - c0).length
                b_len = (c1 - cm).length
                c_len = clen
                area2_tri = (cm - c0).cross(c1 - c0).length
                r_txt = ""
                if area2_tri > 1e-6:
                    r_curv = (a_len * b_len * c_len) / (2.0 * area2_tri)
                    r_txt = f", радиус дуги {_fmt_num(r_curv)} м"
                parts.append(f"ось изогнута: к середине уходит {_dir_vec_ru(dev_w)} на {_fmt_num(max_bend)} м{r_txt}")

        # Cube 3 PolyTree nesting hierarchy + branching
        if branch_slices >= 2:
            parts.append("хребет ветвится на несколько отдельных рукавов")
        if max_tree_depth >= 2:
            parts.append(f"вложенная структура (дерево контуров глубины {max_tree_depth}: труба/остров внутри отверстия)")
        elif max_tree_depth == 1:
            wt_txt = f", толщина стенки около {_fmt_num(sum(tree_wall_thickness) / len(tree_wall_thickness))} м" if tree_wall_thickness else ""
            if max_level1_holes >= 2:
                parts.append(f"внутри {max_level1_holes} параллельных канала{wt_txt}")
            else:
                parts.append(f"полое сечение с внутренним отверстием/каналом{wt_txt}")

        # Cube 1 EFA + Radial FFT cross-section analysis
        if fft_samples:
            _, h2, k_dom, h_dom, max_h, efa = fft_samples[len(fft_samples) // 2]
            elong_txt = ""
            is_oval = False
            if efa is not None and efa["elong"] >= 1.25:
                is_oval = True
                elong_txt = f" (вытянутость {round(efa['elong'], 2)}:1)"
            if max_h < 0.032 and not is_oval:
                parts.append("сечение круглое (гармоники почти нулевые)")
            elif max_h < 0.045 and is_oval:
                parts.append(f"сечение эллиптическое / овал{elong_txt}")
            elif k_dom == 4 and h_dom > 0.035:
                parts.append(f"сечение прямоугольное (4 грани){elong_txt}" if (h2 > 0.06 or is_oval) else "сечение квадратное (4 грани)")
            elif k_dom in (3, 5, 6) and h_dom > 0.035:
                sharp = "острые зубья" if h_dom > 0.11 else "чёткие грани"
                parts.append(f"сечение {k_dom}-угольное / {k_dom}-лучевое ({sharp}, глубина {round(h_dom * 100)}%{elong_txt})")
            elif k_dom >= 7 and h_dom > 0.018:
                parts.append(f"в сечении около {k_dom} зубьев или лепестков (пик {k_dom}-й гармоники Фурье, глубина {round(h_dom * 100)}%)")
            elif h2 >= 0.05 or is_oval:
                parts.append(f"сечение эллиптическое (овал{elong_txt})")

        # Normal-aware ultrasound double echo + blind cup/bowl probe
        cup_depth = _blind_cavity_probe(obj_eval, mw, min_l, max_l)
        us = _ultrasound_echo_scan(obj_eval, mw, min_l, max_l)
        if cup_depth is not None:
            parts.append(f"сверху углубление / чаша глубиной около {_fmt_num(cup_depth)} м (дно закрыто)")
        if us is not None:
            if us["cavities"]:
                w_avg = sum(us["walls"]) / len(us["walls"])
                g_avg = sum(us["cavities"]) / len(us["cavities"])
                parts.append(f"УЗИ выявило внутреннюю полость {_fmt_num(g_avg)} м (толщина стенок около {_fmt_num(w_avg)} м)")
            elif us["walls"] and max_tree_depth == 0:
                w_min = min(us["walls"])
                w_max = max(us["walls"])
                parts.append(f"сплошной монолит, толщина просвечивания от {_fmt_num(w_min)} до {_fmt_num(w_max)} м")
            elif us["single_sided"] > 0 and max_tree_depth == 0 and cup_depth is None:
                parts.append("тонкостенная открытая оболочка без замкнутого объёма")

        return ". ".join(parts)
    finally:
        bm_base.free()
        obj_eval.to_mesh_clear()

class ACCESS_OT_scan_shape(bpy.types.Operator):
    bl_idname = "view3d.access_scan_shape"
    bl_label = "Математический скан 3D-формы"

    globe_mode: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        grabbed = _get_grabbed_obj(context)
        target = grabbed or (context.view_layer.objects.active if context.view_layer else None)
        if target is None:
            _speak_3d("Нет выбранного объекта для сканирования", 1)
            return {'FINISHED'}
        if target.type != 'MESH':
            t_ru = _TYPE_NAMES_RU.get(target.type, target.type)
            _speak_3d(f"{_obj_display_name(target)} — это {t_ru}, а не меш", 1)
            return {'FINISHED'}
        msg = _analyze_mesh_object(context, target, self.globe_mode)
        _speak_3d(msg, 1)
        return {'FINISHED'}

_PROP_TAB_NAMES_RU = {
    'TOOL': 'Инструмент и рабочие настройки',
    'RENDER': 'Рендер',
    'OUTPUT': 'Вывод (разрешение и файл)',
    'VIEW_LAYER': 'Слои вида',
    'SCENE': 'Сцена',
    'WORLD': 'Мир и фон',
    'COLLECTION': 'Коллекция',
    'OBJECT': 'Объект (координаты и трансформации)',
    'MODIFIER': 'Модификаторы',
    'PARTICLES': 'Частицы',
    'PHYSICS': 'Физика',
    'CONSTRAINT': 'Ограничители',
    'DATA': 'Данные объекта (Меш / Камера / Свет)',
    'MATERIAL': 'Материалы',
    'TEXTURE': 'Текстуры',
    'SHADERFX': 'Эффекты',
    'BONE': 'Кость',
    'BONE_CONSTRAINT': 'Ограничители кости',
}

def _find_properties_space(context):
    scr = getattr(context, "screen", None)
    if scr is None:
        return None
    for ar in scr.areas:
        if ar.type == 'PROPERTIES' and ar.spaces.active is not None:
            return ar.spaces.active
    return None

class ACCESS_OT_switch_workspace(bpy.types.Operator):
    bl_idname = "view3d.access_switch_workspace"
    bl_label = "Переключить рабочий раздел"

    ws_name: bpy.props.StringProperty()

    def execute(self, context):
        ws = bpy.data.workspaces.get(self.ws_name)
        if ws is None or not context.window:
            _speak_3d(f"Раздел {self.ws_name} не найден", 1)
            return {'CANCELLED'}
        try:
            context.window.workspace = ws
            is_3d_ws = ws.name in ('Layout', 'Планировка', 'Modeling', 'Моделирование', 'Sculpting', 'Скульптинг')
            _set_zone(0 if is_3d_ws else 2)
            if _bridge is not None and is_3d_ws:
                _bridge.CenterMouseInView3D()
            if is_3d_ws:
                _speak_3d(
                    f"Раздел: {ws.name}. Вы в 3D-сцене. Нажмите F6 для перехода к панелям или Shift+P для выбора вкладки",
                    1
                )
            else:
                _speak_3d(
                    f"Раздел: {ws.name}. Нажмите Стрелки Вверх и Вниз для чтения настроек, F6 для смены области или Escape в 3D-сцену",
                    1
                )
            return {'FINISHED'}
        except Exception as exc:
            _speak_3d(f"Не удалось переключить раздел: {exc}", 1)
            return {'CANCELLED'}

class ACCESS_OT_switch_prop_tab(bpy.types.Operator):
    bl_idname = "view3d.access_switch_prop_tab"
    bl_label = "Переключить вкладку свойств"

    tab_id: bpy.props.StringProperty()
    tab_name: bpy.props.StringProperty()

    def execute(self, context):
        sp = _find_properties_space(context)
        if sp is None:
            _speak_3d("В текущем разделе нет панели Свойств. Откройте Layout или Modeling через Shift+P", 1)
            return {'CANCELLED'}
        try:
            sp.context = self.tab_id
            _set_zone(2)
            _speak_3d(
                f"Открыта вкладка настроек: {self.tab_name}. Стрелки Вверх и Вниз: пункты вкладки, Enter: изменить, F6: смена зоны",
                1
            )
            return {'FINISHED'}
        except Exception:
            _speak_3d(f"Вкладка {self.tab_name} недоступна для текущего выделенного объекта", 1)
            return {'CANCELLED'}

class ACCESS_OT_workspace_menu(bpy.types.Operator):
    bl_idname = "view3d.access_workspace_menu"
    bl_label = "Меню разделов и вкладок Blender"

    from_shift: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        if _is_popup_open():
            return {'PASS_THROUGH'}
        if (not self.from_shift) and context.mode != 'OBJECT':
            return {'PASS_THROUGH'}

        cur_ws = context.window.workspace.name if (context.window and context.window.workspace) else ""
        ws_names = [ws.name for ws in bpy.data.workspaces]

        prop_items = []
        sp = _find_properties_space(context)
        cur_tab = getattr(sp, "context", "") if sp is not None else ""
        if sp is not None:
            try:
                for it in sp.bl_rna.properties['context'].enum_items:
                    prop_items.append((it.identifier, _PROP_TAB_NAMES_RU.get(it.identifier, it.name)))
            except Exception:
                pass
        if not prop_items:
            for tid in ('RENDER', 'OUTPUT', 'VIEW_LAYER', 'SCENE', 'WORLD', 'COLLECTION', 'OBJECT', 'MODIFIER', 'PARTICLES', 'PHYSICS', 'CONSTRAINT', 'DATA', 'MATERIAL', 'TEXTURE'):
                prop_items.append((tid, _PROP_TAB_NAMES_RU.get(tid, tid)))

        def draw_menu(menu_self, menu_ctx):
            layout = menu_self.layout
            layout.label(text="Большие разделы (Workspaces):")
            for wname in ws_names:
                mark = " [текущий]" if wname == cur_ws else ""
                op = layout.operator(ACCESS_OT_switch_workspace.bl_idname, text=f"Раздел: {wname}{mark}")
                op.ws_name = wname
            layout.separator()
            layout.label(text="Вкладки настроек (Properties):")
            for tid, tlabel in prop_items:
                mark = " [текущая]" if tid == cur_tab else ""
                op = layout.operator(ACCESS_OT_switch_prop_tab.bl_idname, text=f"Вкладка: {tlabel}{mark}")
                op.tab_id = tid
                op.tab_name = tlabel

        _speak_3d("Меню разделов и вкладок. Стрелки Вверх и Вниз: выбор, Enter: открыть, Escape: закрыть", 1)
        context.window_manager.popup_menu(draw_menu, title="Разделы и вкладки настроек", icon='PREFERENCES')
        return {'FINISHED'}

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
