import math
import bpy
import bmesh
import mathutils

from .bridge import (
    _STEP_PRESETS,
    _TYPE_NAMES_RU,
    _check_contacts,
    _fmt_num,
    _format_step_human,
    _get_grabbed_obj,
    _get_zone,
    _is_popup_open,
    _is_view3d_context,
    _obj_display_name,
    _speak_3d,
    _state,
    _sync_viewport,
    _view_forward_right,
    _world_bbox,
)
from .camera_light import _ray_dir_ru

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
                rot_msg = f"Поворот {gname} по Z: {deg} градусов"
            elif self.action == "YAW_RIGHT":
                target_obj.rotation_euler.z -= math.radians(rot_step)
                deg = round(math.degrees(target_obj.rotation_euler.z)) % 360
                rot_msg = f"Поворот {gname} по Z: {deg} градусов"
            elif self.action == "PITCH_UP":
                target_obj.rotation_euler.x += math.radians(rot_step)
                deg = round(math.degrees(target_obj.rotation_euler.x)) % 360
                rot_msg = f"Наклон {gname} по X: {deg} градусов"
            elif self.action == "PITCH_DOWN":
                target_obj.rotation_euler.x -= math.radians(rot_step)
                deg = round(math.degrees(target_obj.rotation_euler.x)) % 360
                rot_msg = f"Наклон {gname} по X: {deg} градусов"
            else:
                rot_msg = gname
            context.view_layer.update()
            if target_obj.type in ('LIGHT', 'CAMERA'):
                emit_dir = (target_obj.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
                ref_fwd, ref_right = _view_forward_right()
                verb = "светит" if target_obj.type == 'LIGHT' else "смотрит"
                rot_msg += f", {verb} {_ray_dir_ru(emit_dir, ref_right, ref_fwd)}"
            _speak_3d(rot_msg, 1)
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
    bl_label = "Задать метку объекта или выделенной части"
    bl_options = {'REGISTER', 'UNDO'}

    label_text: bpy.props.StringProperty(name="Метка", default="")

    def invoke(self, context, event):
        if _is_popup_open() or _get_zone() != 0 or not _is_view3d_context(context):
            return {'PASS_THROUGH'}
        active = context.view_layer.objects.active if context.view_layer else None
        if active is None:
            _speak_3d("Нет выбранного объекта для метки", 1)
            return {'FINISHED'}
        if context.mode == 'EDIT_MESH' and active.type == 'MESH':
            vg = active.vertex_groups.active
            self.label_text = vg.name if vg is not None else ""
            _speak_3d(
                f"Метка выделенной части для {active.name}. Введите название части (например, Ручка или Уступ) и нажмите Enter; пустое поле удаляет активную группу",
                1
            )
            return context.window_manager.invoke_props_dialog(self, width=360)
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
        if context.mode == 'EDIT_MESH' and active.type == 'MESH':
            bm = bmesh.from_edit_mesh(active.data)
            sel_verts = [v for v in bm.verts if v.select]
            if not val:
                vg = active.vertex_groups.active
                if vg is not None:
                    vname = vg.name
                    active.vertex_groups.remove(vg)
                    bmesh.update_edit_mesh(active.data)
                    _speak_3d(f"Удалена метка части «{vname}» для {active.name}", 1)
                else:
                    _speak_3d("Нет активной метки части для удаления", 1)
                return {'FINISHED'}
            if not sel_verts:
                _speak_3d("Сначала выделите вершины, рёбра или грани части в режиме редактирования", 1)
                return {'CANCELLED'}
            dvert_lay = bm.verts.layers.deform.verify()
            vg = active.vertex_groups.get(val)
            if vg is None:
                vg = active.vertex_groups.new(name=val)
            active.vertex_groups.active_index = vg.index
            for v in sel_verts:
                v[dvert_lay][vg.index] = 1.0
            bmesh.update_edit_mesh(active.data)
            _speak_3d(f"Сохранена метка части «{val}» ({len(sel_verts)} вершин) для {active.name}", 1)
            return {'FINISHED'}
        if val:
            active["access_label"] = val
            _speak_3d(f"Сохранена метка: {val} для {active.name}", 1)
        else:
            if "access_label" in active:
                del active["access_label"]
            _speak_3d(f"Метка удалена для {active.name}", 1)
        return {'FINISHED'}
