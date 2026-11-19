import os
import math
import tempfile
import bpy
import mathutils
import bpy_extras.object_utils

from .bridge import (
    _TYPE_NAMES_RU,
    _fmt_num,
    _get_grabbed_obj,
    _get_zone,
    _is_popup_open,
    _is_view3d_context,
    _obj_display_name,
    _speak_3d,
    _view_forward_right,
    _world_bbox,
)

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
    if v.z <= -0.25:
        parts.append("вниз")
    elif v.z >= 0.25:
        parts.append("вверх")
    if ref_right is not None and ref_fwd is not None:
        r_xy = mathutils.Vector((ref_right.x, ref_right.y, 0.0))
        f_xy = mathutils.Vector((ref_fwd.x, ref_fwd.y, 0.0))
        rx = v.dot(r_xy.normalized()) if r_xy.length > 1e-6 else v.x
        fy = v.dot(f_xy.normalized()) if f_xy.length > 1e-6 else v.y
        if abs(rx) >= 0.25:
            parts.append("вправо" if rx > 0 else "влево")
        if abs(fy) >= 0.25:
            parts.append("вперёд" if fy > 0 else "назад")
    else:
        if abs(v.x) >= 0.25:
            parts.append("вправо" if v.x > 0 else "влево")
        if abs(v.y) >= 0.25:
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

    in_items_wire = []
    missed = []
    for o in scene.objects:
        if o.type in ('CAMERA', 'LIGHT', 'EMPTY') or o.name in hit_stats:
            continue
        pts = [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box] if (hasattr(o, "bound_box") and o.bound_box) else [o.location.copy()]
        ndcs = [bpy_extras.object_utils.world_to_camera_view(scene, cam, p) for p in pts]
        if all(n.z <= 0.0 for n in ndcs):
            missed.append(f"{_obj_display_name(o)} (сзади за камерой)")
        elif any((n.z > 0.0 and 0.0 <= n.x <= 1.0 and 0.0 <= n.y <= 1.0) for n in ndcs):
            vis_probe = _is_obj_visible_in_camera_cone(scene, depsgraph, cam, cam_origin, o, pts, ndcs)
            if vis_probe is not None:
                vu, vv, vdist = vis_probe
                pos_str = "по центру кадра" if (0.35 <= vu <= 0.65 and 0.35 <= vv <= 0.65) else _frame_pos_ru(vu, vv)
                t_ru = _TYPE_NAMES_RU.get(o.type, o.type)
                in_items_wire.append(f"{pos_str}: {_obj_display_name(o)} ({t_ru}, контур в кадре, {_fmt_num(vdist)} м)")
            else:
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
    if in_items_wire:
        if not hit_stats:
            parts = [f"{cam_hdr}: " + "; ".join(in_items_wire[:(len(in_items_wire) if detailed else 4)])]
        else:
            parts[0] += "; " + "; ".join(in_items_wire[:(len(in_items_wire) if detailed else 2)])
    if missed:
        lim = len(missed) if detailed else min(3, len(missed))
        parts.append("В кадр не попало: " + "; ".join(missed[:lim]))
    return ". ".join(parts)

def _is_obj_visible_in_camera_cone(scene, depsgraph, cam, cam_origin, o, pts, ndcs):
    in_pts = [p for p, n in zip(pts, ndcs) if n.z > 0.0 and 0.0 <= n.x <= 1.0 and 0.0 <= n.y <= 1.0]
    loc_ndc = bpy_extras.object_utils.world_to_camera_view(scene, cam, o.location)
    if loc_ndc.z > 0.0 and 0.0 <= loc_ndc.x <= 1.0 and 0.0 <= loc_ndc.y <= 1.0:
        in_pts.insert(0, o.location.copy())
    if not in_pts:
        return None
    for p in in_pts:
        vec = p - cam_origin
        obj_dist = vec.length
        if obj_dist < 1e-4:
            return (0.5, 0.5, 0.0)
        r_dir = vec / obj_dist
        h, hloc, _, _, hobj, _ = scene.ray_cast(depsgraph, cam_origin, r_dir, distance=obj_dist)
        if (not h) or (hobj == o) or ((hloc - cam_origin).length >= obj_dist - 0.05):
            nd = bpy_extras.object_utils.world_to_camera_view(scene, cam, p)
            return (nd.x, nd.y, obj_dist)
    return None

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
    meshes = [o for o in scene.objects if o.type in ('MESH', 'SURFACE', 'META', 'FONT', 'CURVE')]
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

    ref_fwd, ref_right = _view_forward_right()

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

        if ldata.type == 'SPOT':
            cone_deg = round(math.degrees(ldata.spot_size), 1)
            l_desc = f"{_obj_display_name(lt)} (Прожектор, угол {cone_deg}°) на X {_fmt_num(lt_orig.x)}, Y {_fmt_num(lt_orig.y)}, Z {_fmt_num(lt_orig.z)}, светит {_ray_dir_ru(emit_dir, ref_right, ref_fwd)}"
        elif ldata.type == 'AREA':
            spread_rad = getattr(ldata, 'spread', math.pi)
            cone_deg = round(math.degrees(spread_rad), 1)
            l_desc = f"{_obj_display_name(lt)} (Площадной свет, угол {cone_deg}°) на X {_fmt_num(lt_orig.x)}, Y {_fmt_num(lt_orig.y)}, Z {_fmt_num(lt_orig.z)}, светит {_ray_dir_ru(emit_dir, ref_right, ref_fwd)}"
        elif ldata.type == 'POINT':
            l_desc = f"{_obj_display_name(lt)} (Точечный, обзор 360°) на X {_fmt_num(lt_orig.x)}, Y {_fmt_num(lt_orig.y)}, Z {_fmt_num(lt_orig.z)}"
        else:
            sun_deg = round(math.degrees(ldata.angle), 2)
            l_desc = f"{_obj_display_name(lt)} (Солнце, угол диска {sun_deg}°) светит {_ray_dir_ru(emit_dir, ref_right, ref_fwd)}"

        rays = _collect_light_rays(lt, meshes, mesh_pts_w)
        l_parts = [l_desc]
        if not rays and ldata.type == 'SUN':
            l_parts.append("В направлении луча объектов нет (объекты сцены находятся позади точки источника)")
            reports.append(". ".join(l_parts))
            continue

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

def _collect_light_rays(lt, meshes, mesh_pts_w=None):
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
        if mesh_pts_w is None:
            mesh_pts_w = []
            for o in meshes:
                if hasattr(o, "bound_box") and o.bound_box:
                    mesh_pts_w.extend([o.matrix_world @ mathutils.Vector(c) for c in o.bound_box])
                else:
                    mesh_pts_w.append(o.location.copy())
        if mesh_pts_w:
            w_sun = lt_orig.dot(emit_dir)
            horiz_len = math.hypot(emit_dir.x, emit_dir.y)
            front_pts = []
            for p in mesh_pts_w:
                dv = p - lt_orig
                if dv.dot(emit_dir) < 0.0:
                    continue
                if horiz_len >= 0.25 and (dv.x * emit_dir.x + dv.y * emit_dir.y) < -0.05:
                    continue
                if abs(emit_dir.z) >= 0.25 and (dv.z * emit_dir.z) < -0.05:
                    continue
                front_pts.append(p)
            if front_pts:
                us = [p.dot(lt_right) for p in front_pts]
                vs = [p.dot(lt_up) for p in front_pts]
                u0, u1 = min(us) - 0.5, max(us) + 0.5
                v0, v1 = min(vs) - 0.5, max(vs) + 0.5
                w_start = w_sun
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
            t_pts = [target.matrix_world @ mathutils.Vector(c) for c in target.bound_box] if (hasattr(target, "bound_box") and target.bound_box) else [target.location.copy()]
            t_ndcs = [bpy_extras.object_utils.world_to_camera_view(scene, cam, p) for p in t_pts]
            if any((n.z > 0.0 and 0.0 <= n.x <= 1.0 and 0.0 <= n.y <= 1.0) for n in t_ndcs):
                vis_probe = _is_obj_visible_in_camera_cone(scene, depsgraph, cam, cam_origin, target, t_pts, t_ndcs)
                if vis_probe is not None:
                    vu, vv, vdist = vis_probe
                    pos_str = "по центру кадра" if (0.35 <= vu <= 0.65 and 0.35 <= vv <= 0.65) else _frame_pos_ru(vu, vv)
                    parts.append(f"В камере «{_obj_display_name(cam)}» ({fov_x}×{fov_y}°): {pos_str} (контур в кадре, {_fmt_num(vdist)} м)")
                else:
                    parts.append(f"В камере «{_obj_display_name(cam)}» заслонён другими объектами")
            else:
                parts.append(f"В кадр камеры «{_obj_display_name(cam)}» сейчас не попадает")

    # 2. Direct light hitting target & shadow cast by target
    lights = [o for o in scene.objects if o.type == 'LIGHT']
    meshes = [o for o in scene.objects if o.type in ('MESH', 'SURFACE', 'META', 'FONT', 'CURVE')]
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
