import os
import math
import ctypes
import bpy
import mathutils

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
            bmin2, bmax2 = _world_bbox(other)
            dx = max(0.0, max(bmin1.x - bmax2.x, bmin2.x - bmax1.x))
            dy = max(0.0, max(bmin1.y - bmax2.y, bmin2.y - bmax1.y))
            dz = max(0.0, max(bmin1.z - bmax2.z, bmin2.z - bmax1.z))
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            overlap_x = (bmin1.x < bmax2.x - tol) and (bmax1.x > bmin2.x + tol)
            overlap_y = (bmin1.y < bmax2.y - tol) and (bmax1.y > bmin2.y + tol)
            overlap_z = (bmin1.z < bmax2.z - tol) and (bmax1.z > bmin2.z + tol)
            if overlap_x and overlap_y and overlap_z:
                notes.append(f"Пересечение с {other.name}")
            elif dist <= tol:
                notes.append(f"Стыковка вплотную к {other.name}")
    else:
        for other in context.scene.objects:
            bmin2, bmax2 = _world_bbox(other)
            dx = max(0.0, max(bmin2.x - cursor_loc.x, cursor_loc.x - bmax2.x))
            dy = max(0.0, max(bmin2.y - cursor_loc.y, cursor_loc.y - bmax2.y))
            dz = max(0.0, max(bmin2.z - cursor_loc.z, cursor_loc.z - bmax2.z))
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if dist == 0.0:
                notes.append(f"Внутри {other.name}")
            elif dist <= tol:
                notes.append(f"Касание {other.name}")
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
        if not context.scene or _is_popup_open():
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
            t_ru = _TYPE_NAMES_RU.get(target.type, target.type)
            bmin, bmax = _world_bbox(target)
            dim = target.dimensions
            _speak_3d(
                f"{idx+1} из {len(objs)}: {target.name} ({t_ru}). "
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

        contact_msg = _check_contacts(context, grabbed, cur)
        prefix = f"{grabbed.name} {dir_label}" if grabbed else dir_label
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
        if _get_zone() != 0:
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
        if _get_zone() != 0 or not context.scene:
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
                f" {state_lbl}: {active.name}. "
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
        if _get_zone() != 0 or not context.scene:
            return {'PASS_THROUGH'}
        if context.mode != 'OBJECT':
            return {'PASS_THROUGH'}

        grabbed = _get_grabbed_obj(context)
        if grabbed is not None:
            _state["grabbed_name"] = ""
            bmin, bmax = _world_bbox(grabbed)
            contact = _check_contacts(context, grabbed, context.scene.cursor.location)
            msg = (
                f"Поставлен: {grabbed.name}. "
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
            f"Взят в руки: {target.name}, размер {_fmt_num(dim.x)} на {_fmt_num(dim.y)} на {_fmt_num(dim.z)} м",
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
        if _get_zone() != 0 or not context.scene:
            return {'PASS_THROUGH'}
        if context.mode != 'OBJECT':
            return {'PASS_THROUGH'}

        grabbed = _get_grabbed_obj(context)
        rot_step = _state["rot_step_deg"]
        step = _state["step_size"]

        if grabbed is not None:
            if self.scale_mode:
                delta_s = step if self.action in ("PITCH_UP", "YAW_RIGHT") else -step
                for i in range(3):
                    grabbed. dimensions[i] = max(0.0001, grabbed.dimensions[i] + delta_s)
                context.view_layer.update()
                d = grabbed.dimensions
                _speak_3d(
                    f"Размер {grabbed.name}: {_fmt_num(d.x)} на {_fmt_num(d.y)} на {_fmt_num(d.z)} м",
                    1
                )
                return {'FINISHED'}

            if self.action == "YAW_LEFT":
                grabbed.rotation_euler.z += math.radians(rot_step)
                deg = round(math.degrees(grabbed.rotation_euler.z)) % 360
                _speak_3d(f"Поворот {grabbed.name} по Z: {deg} градусов", 1)
            elif self.action == "YAW_RIGHT":
                grabbed.rotation_euler.z -= math.radians(rot_step)
                deg = round(math.degrees(grabbed.rotation_euler.z)) % 360
                _speak_3d(f"Поворот {grabbed.name} по Z: {deg} градусов", 1)
            elif self.action == "PITCH_UP":
                grabbed.rotation_euler.x += math.radians(rot_step)
                deg = round(math.degrees(grabbed.rotation_euler.x)) % 360
                _speak_3d(f"Наклон {grabbed.name} по X: {deg} градусов", 1)
            elif self.action == "PITCH_DOWN":
                grabbed.rotation_euler.x -= math.radians(rot_step)
                deg = round(math.degrees(grabbed.rotation_euler.x)) % 360
                _speak_3d(f"Наклон {grabbed.name} по X: {deg} градусов", 1)
            context.view_layer.update()
            return {'FINISHED'}

        # Rotate view direction
        if self.action == "YAW_LEFT":
            _state["yaw_deg"] = (_state["yaw_deg"] - rot_step) % 360.0
            _speak_3d(f"Взгляд влево: {int(round(_state['yaw_deg']))} градусов", 1)
        elif self.action == "YAW_RIGHT":
            _state["yaw_deg"] = (_state["yaw_deg"] + rot_step) % 360.0
            _speak_3d(f"Взгляд вправо: {int(round(_state['yaw_deg']))} градусов", 1)
        elif self.action == "PITCH_UP":
            _state["pitch_deg"] = max(-85.0, min(85.0, _state["pitch_deg"] + rot_step))
            _speak_3d(f"Взгляд вверх: {int(round(_state['pitch_deg']))} градусов", 1)
        elif self.action == "PITCH_DOWN":
            _state["pitch_deg"] = max(-85.0, min(85.0, _state["pitch_deg"] - rot_step))
            _speak_3d(f"Взгляд вниз: {int(round(_state['pitch_deg']))} градусов", 1)
        return {'FINISHED'}

class ACCESS_OT_radar_scan(bpy.types.Operator):
    bl_idname = "view3d.access_radar_scan"
    bl_label = "Осмотреться (Что передо мной)"

    open_list: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        if _get_zone() != 0 or not context.scene:
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
                    op = layout.operator("view3d.access_jump_to_object", text=f"{o.name} ({t_ru}, {_fmt_num(dist)} м)")
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
                parts.append(f"Луч прямо упирается в {hit_obj.name} через {_fmt_num(hit_dist)} м")
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
                parts.append(f"{rel} в {_fmt_num(dist)} м: {o.name} (размер {_fmt_num(dim.x)}×{_fmt_num(dim.y)}×{_fmt_num(dim.z)} м)")
            else:
                parts.append(f"{rel} в {_fmt_num(dist)} м: {o.name} ({t_ru})")

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
        dim = obj.dimensions
        _speak_3d(
            f"Перешёл к {obj.name}. Координаты X {_fmt_num(obj.location.x)}, Y {_fmt_num(obj.location.y)}, Z {_fmt_num(obj.location.z)}. "
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
        if _get_zone() != 0 or not context.scene:
            return {'PASS_THROUGH'}
        self.step_val = _state["step_size"]
        self.rot_val = _state["rot_step_deg"]
        active = context.view_layer.objects.active if context.view_layer else None
        if active is not None:
            bmin, bmax = _world_bbox(active)
            self.from_x, self.to_x = bmin.x, bmax.x
            self.from_y, self.to_y = bmin.y, bmax.y
            self.from_z, self.to_z = bmin.z, bmax.z
            _speak_3d(f"Окно координат От и До для {active.name}. Стрелки Вверх и Вниз: поля, Enter: ввод и подтверждение", 1)
        else:
            cur = context.scene.cursor.location
            self.from_x = self.to_x = cur.x
            self.from_y = self.to_y = cur.y
            self.from_z = self.to_z = cur.z
            _speak_3d("Окно координат и настройки шага", 1)
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
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
            _speak_3d(
                f"Установлено для {active.name}: X от {_fmt_num(x0)} до {_fmt_num(x1)}, "
                f"Y от {_fmt_num(y0)} до {_fmt_num(y1)}, Z от {_fmt_num(z0)} до {_fmt_num(z1)}. "
                f"Размер {_fmt_num(sx)} на {_fmt_num(sy)} на {_fmt_num(sz)} м. Шаг: {_format_step_human(_state['step_size'])}",
                1
            )
        else:
            context.scene.cursor.location = mathutils.Vector((cx, cy, cz))
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
        if _is_popup_open() or _get_zone() != 0 or not context.scene:
            return {'PASS_THROUGH'}
        if context.mode != 'OBJECT':
            return {'PASS_THROUGH'}
        active = context.view_layer.objects.active if context.view_layer else None
        if active is None:
            _speak_3d("Нет выбранного объекта для удаления", 1)
            return {'FINISHED'}
        name = active.name
        if _state["grabbed_name"] == name:
            _state["grabbed_name"] = ""
        active.select_set(True)
        bpy.ops.object.delete(use_global=False, confirm=False)
        _speak_3d(f"Удалён объект: {name}", 1)
        return {'FINISHED'}

class ACCESS_OT_frame_step(bpy.types.Operator):
    bl_idname = "view3d.access_frame_step"
    bl_label = "Шаг по кадрам анимации"

    delta: bpy.props.IntProperty(default=1)

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0 or not context.scene:
            return {'PASS_THROUGH'}
        scn = context.scene
        new_f = max(scn.frame_start, min(scn.frame_end, scn.frame_current + self.delta))
        scn.frame_set(new_f)
        msg = f"Кадр {scn.frame_current} из {scn.frame_end}"
        active = context.view_layer.objects.active if context.view_layer else None
        if active is not None:
            loc = active.location
            msg += f". {active.name}: X {_fmt_num(loc.x)}, Y {_fmt_num(loc.y)}, Z {_fmt_num(loc.z)}"
        _speak_3d(msg, 1)
        return {'FINISHED'}

class ACCESS_OT_toggle_edit_mode(bpy.types.Operator):
    bl_idname = "view3d.access_toggle_edit_mode"
    bl_label = "Переключить режим объекта и редактирования"

    def execute(self, context):
        if _is_popup_open() or _get_zone() != 0:
            return {'PASS_THROUGH'}
        active = context.view_layer.objects.active if context.view_layer else None
        if active is None or active.type not in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'ARMATURE', 'LATTICE'):
            return {'PASS_THROUGH'}
        try:
            bpy.ops.object.editmode_toggle()
            if context.mode == 'OBJECT':
                _speak_3d(f"Объектный режим: {active.name}", 1)
            else:
                _speak_3d(f"Режим редактирования вершин и граней: {active.name}. Нажмите Tab или Escape для возврата в Объектный режим", 1)
            return {'FINISHED'}
        except Exception:
            return {'PASS_THROUGH'}

class ACCESS_OT_escape_scene(bpy.types.Operator):
    bl_idname = "view3d.access_escape_scene"
    bl_label = "Выход в 3D-сцену"

    def execute(self, context):
        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
                _speak_3d("Возврат в Объектный режим. 3D-сцена", 1)
            except Exception:
                pass
        return {'PASS_THROUGH'}

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
        for k, act in (('A', 'YAW_LEFT'), ('D', 'YAW_RIGHT'), ('W', 'PITCH_UP'), ('S', 'PITCH_DOWN')):
            kmi = km.keymap_items.new(ACCESS_OT_rotate_or_look.bl_idname, k, 'PRESS', shift=sh)
            kmi.properties.action = act
            kmi.properties.scale_mode = sh
            _addon_keymaps.append((km, kmi))

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
            km_win = kc.keymaps.new(name='Window', space_type='EMPTY')
            _bind_access_keys_to_keymap(km_win)
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
