import math
import numpy as np
import bpy
import bmesh
import mathutils

from .bridge import (
    _TYPE_NAMES_RU,
    _fmt_num,
    _get_grabbed_obj,
    _get_zone,
    _is_popup_open,
    _is_view3d_context,
    _obj_display_name,
    _speak_3d,
    _world_bbox,
)
from .camera_light import (
    _camera_cone_report,
    _lights_shadow_report,
)

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

def _count_boundary_loops(bm):
    b_edges = {e for e in bm.edges if len(e.link_faces) < 2}
    visited = set()
    loops = 0
    for e0 in b_edges:
        if e0 in visited:
            continue
        loops += 1
        stack = [e0]
        visited.add(e0)
        while stack:
            e = stack.pop()
            for v in e.verts:
                for ne in v.link_edges:
                    if ne in b_edges and ne not in visited:
                        visited.add(ne)
                        stack.append(ne)
    return len(b_edges), loops

def _slice_tier_islands(bm_base, e_arr, z_min, hz):
    if hz <= 1e-4 or len(bm_base.edges) == 0:
        return None
    z0_raw = e_arr[:, 0, 2]
    z1_raw = e_arr[:, 1, 2]
    edges = bm_base.edges
    tier_counts = []
    for frac in (0.10, 0.50, 0.90):
        zk = float(z_min) + frac * hz
        # Perturb vertices landing exactly on the cut plane so grid rings never split across coplanar vertices
        z0 = np.where(np.abs(z0_raw - zk) < 1e-5, zk + 1e-5, z0_raw)
        z1 = np.where(np.abs(z1_raw - zk) < 1e-5, zk + 1e-5, z1_raw)
        dz = z1 - z0
        valid = np.abs(dz) > 1e-6
        crossed_idx = np.nonzero(valid & (((z0 <= zk) & (zk < z1)) | ((z1 <= zk) & (zk < z0))))[0]
        if len(crossed_idx) == 0:
            tier_counts.append(0)
            continue
        crossed_set = {edges[int(i)] for i in crossed_idx}
        edge_to_xy = {}
        for i in crossed_idx:
            i = int(i)
            t_e = (zk - z0[i]) / dz[i]
            px = float(e_arr[i, 0, 0] + t_e * (e_arr[i, 1, 0] - e_arr[i, 0, 0]))
            py = float(e_arr[i, 0, 1] + t_e * (e_arr[i, 1, 1] - e_arr[i, 0, 1]))
            edge_to_xy[edges[i]] = (px, py)

        visited = set()
        boxes = []
        for e0 in crossed_set:
            if e0 in visited:
                continue
            visited.add(e0)
            q = [e0]
            xs, ys = [], []
            while q:
                ce = q.pop()
                px, py = edge_to_xy[ce]
                xs.append(px)
                ys.append(py)
                for v in ce.verts:
                    for ne in v.link_edges:
                        if ne in crossed_set and ne not in visited:
                            visited.add(ne)
                            q.append(ne)
                for f in ce.link_faces:
                    for fe in f.edges:
                        if fe in crossed_set and fe not in visited:
                            visited.add(fe)
                            q.append(fe)
            boxes.append((min(xs), min(ys), max(xs), max(ys)))

        # Ignore concentric inner shell islands strictly enclosed inside an outer ring (e.g. hollow cavity walls)
        outer_count = 0
        for idx_a, (ax0, ay0, ax1, ay1) in enumerate(boxes):
            nested = any(
                idx_b != idx_a and ax0 > bx0 + 1e-4 and ax1 < bx1 - 1e-4 and ay0 > by0 + 1e-4 and ay1 < by1 - 1e-4
                for idx_b, (bx0, by0, bx1, by1) in enumerate(boxes)
            )
            if not nested:
                outer_count += 1
        tier_counts.append(max(outer_count, 1 if boxes else 0))
    return tuple(tier_counts)

def _analyze_relief_from_ram(bm_base, verts_w, min_w, max_w, ext_w, center_w, skip_sides=()):
    convex_ridges = 0
    concave_crevices = 0
    e_stride = max(1, len(bm_base.edges) // 12000)
    for idx in range(0, len(bm_base.edges), e_stride):
        e = bm_base.edges[idx]
        if len(e.link_faces) == 2:
            ang = e.calc_face_angle_signed(0.0)
            if ang > 0.38:
                convex_ridges += 1
            elif ang < -0.38:
                concave_crevices += 1

    pts_list = [verts_w]
    nrm_list = [np.array([[v.normal.x, v.normal.y, v.normal.z] for v in bm_base.verts], dtype=np.float64)]
    if len(bm_base.faces) > 0 and len(bm_base.verts) <= 8000:
        pts_list.append(np.array([[f.calc_center_median().x, f.calc_center_median().y, f.calc_center_median().z] for f in bm_base.faces], dtype=np.float64))
        nrm_list.append(np.array([[f.normal.x, f.normal.y, f.normal.z] for f in bm_base.faces], dtype=np.float64))
    if len(bm_base.edges) > 0 and len(bm_base.verts) <= 4000:
        pts_list.append(np.array([[(e.verts[0].co.x + e.verts[1].co.x) * 0.5,
                                   (e.verts[0].co.y + e.verts[1].co.y) * 0.5,
                                   (e.verts[0].co.z + e.verts[1].co.z) * 0.5] for e in bm_base.edges], dtype=np.float64))
        enrms = []
        for e in bm_base.edges:
            en = e.verts[0].normal + e.verts[1].normal
            if en.length > 1e-6:
                en.normalize()
            enrms.append([en.x, en.y, en.z])
        nrm_list.append(np.array(enrms, dtype=np.float64))

    pts = np.vstack(pts_list)
    norms = np.vstack(nrm_list)

    protrusions = []
    cavities = []
    nb = 5
    c_arr = (float(center_w.x), float(center_w.y), float(center_w.z))
    sides = (
        ("справа +X", 0, 1.0, 1, 2),
        ("слева -X", 0, -1.0, 1, 2),
        ("сзади +Y", 1, 1.0, 0, 2),
        ("спереди -Y", 1, -1.0, 0, 2),
        ("сверху +Z", 2, 1.0, 0, 1),
        ("снизу -Z", 2, -1.0, 0, 1),
    )
    for label_ru, ax, sign, u_ax, v_ax in sides:
        if label_ru in skip_sides:
            continue
        span = float(ext_w[ax])
        if span < 1e-4:
            continue

        # Only examine points genuinely on this side's hemisphere and facing toward that side
        mask = ((norms[:, ax] * sign) > 0.45) & (((pts[:, ax] - c_arr[ax]) * sign) >= -0.05 * span)
        if np.count_nonzero(mask) < 4:
            continue
        s_pts = pts[mask]
        u_min = float(s_pts[:, u_ax].min())
        u_max = float(s_pts[:, u_ax].max())
        v_min = float(s_pts[:, v_ax].min())
        v_max = float(s_pts[:, v_ax].max())
        u_span = u_max - u_min
        v_span = v_max - v_min
        if u_span < 1e-4 or v_span < 1e-4:
            continue

        bu = np.clip(((s_pts[:, u_ax] - u_min) / u_span * nb).astype(int), 0, nb - 1)
        bv = np.clip(((s_pts[:, v_ax] - v_min) / v_span * nb).astype(int), 0, nb - 1)
        vals = s_pts[:, ax] * sign

        grid_max = np.full((nb, nb), np.nan, dtype=np.float64)
        grid_min = np.full((nb, nb), np.nan, dtype=np.float64)
        for i_pt in range(len(vals)):
            ui, vi, val = int(bu[i_pt]), int(bv[i_pt]), float(vals[i_pt])
            if np.isnan(grid_max[ui, vi]) or val > grid_max[ui, vi]:
                grid_max[ui, vi] = val
            if np.isnan(grid_min[ui, vi]) or val < grid_min[ui, vi]:
                grid_min[ui, vi] = val

        occ = grid_max[~np.isnan(grid_max)]
        if len(occ) < 4:
            continue

        wall_base = float(np.percentile(occ, 65))
        peak_val = float(occ.max())
        prot_amt = peak_val - wall_base
        prot_thresh = max(0.08, 0.14 * span)
        if prot_amt >= prot_thresh:
            high_cnt = int(np.count_nonzero(occ >= wall_base + 0.5 * prot_amt))
            if high_cnt <= max(1, int(0.42 * len(occ))):
                protrusions.append((prot_amt, label_ru))

        best_recess = 0.0
        for ui in range(1, nb - 1):
            for vi in range(1, nb - 1):
                val_min = grid_min[ui, vi]
                if np.isnan(val_min):
                    continue
                left_vals = [grid_max[k, vi] for k in range(ui) if not np.isnan(grid_max[k, vi])]
                right_vals = [grid_max[k, vi] for k in range(ui + 1, nb) if not np.isnan(grid_max[k, vi])]
                down_vals = [grid_max[ui, k] for k in range(vi) if not np.isnan(grid_max[ui, k])]
                up_vals = [grid_max[ui, k] for k in range(vi + 1, nb) if not np.isnan(grid_max[ui, k])]
                rec_u = (min(max(left_vals), max(right_vals)) - val_min) if (left_vals and right_vals) else 0.0
                rec_v = (min(max(down_vals), max(up_vals)) - val_min) if (down_vals and up_vals) else 0.0
                # Require surrounding walls across both orthogonal axes or strong flanking pocket so smooth domes do not false-trigger
                recess = min(rec_u, rec_v) if (rec_u > 0.0 and rec_v > 0.0) else 0.0
                if recess > best_recess:
                    best_recess = recess
        if best_recess >= max(0.08, 0.14 * span):
            cavities.append((best_recess, label_ru))

    protrusions.sort(key=lambda x: -x[0])
    cavities.sort(key=lambda x: -x[0])
    return convex_ridges, concave_crevices, protrusions, cavities

def _extract_user_part_labels_ram(obj, mw, center_w, ext_w):
    if obj.type != 'MESH' or not obj.data or not getattr(obj, 'vertex_groups', None):
        return ""
    vgroups = list(obj.vertex_groups)
    if not vgroups:
        return ""

    group_pts = {vg.index: [] for vg in vgroups}
    if obj.mode == 'EDIT':
        bm_ed = bmesh.from_edit_mesh(obj.data)
        dvert_lay = bm_ed.verts.layers.deform.active
        if dvert_lay is not None:
            for v in bm_ed.verts:
                dv = v[dvert_lay]
                if len(dv) == 0:
                    continue
                wco = mw @ v.co
                for gi, wval in dv.items():
                    if gi in group_pts and wval > 0.01:
                        group_pts[gi].append(wco)
    else:
        for v in obj.data.vertices:
            if not v.groups:
                continue
            wco = mw @ v.co
            for ge in v.groups:
                if ge.group in group_pts and ge.weight > 0.01:
                    group_pts[ge.group].append(wco)

    summaries = []
    max_span = max(float(ext_w[0]), float(ext_w[1]), float(ext_w[2]), 1e-4)
    for vg in vgroups:
        pts_g = group_pts.get(vg.index)
        if not pts_g:
            continue
        arr = np.array([[p.x, p.y, p.z] for p in pts_g], dtype=np.float64)
        pmin = arr.min(axis=0)
        pmax = arr.max(axis=0)
        pext = pmax - pmin
        pc = (pmin + pmax) * 0.5
        dx = float(pc[0] - center_w.x)
        dy = float(pc[1] - center_w.y)
        dz = float(pc[2] - center_w.z)
        axes = [
            (abs(dx), "справа +X" if dx > 0 else "слева -X"),
            (abs(dy), "сзади +Y" if dy > 0 else "спереди -Y"),
            (abs(dz), "сверху +Z" if dz > 0 else "снизу -Z"),
        ]
        axes.sort(key=lambda t: -t[0])
        side_txt = axes[0][1] if axes[0][0] > 0.08 * max_span else "по центру"
        summaries.append(
            f"{vg.name} ({side_txt}, {_fmt_num(pext[0])}×{_fmt_num(pext[1])}×{_fmt_num(pext[2])} м)"
        )
    if not summaries:
        return ""
    return "Размеченные части: " + "; ".join(summaries[:6])

def _analyze_special_object(obj, globe_mode, header, t_ru):
    bmin, bmax = _world_bbox(obj)
    ext = bmax - bmin
    hx, hy, hz = float(ext.x), float(ext.y), float(ext.z)
    cw = (bmin + bmax) * 0.5
    loc = obj.location
    extra = []
    if obj.type == 'ARMATURE' and obj.data and hasattr(obj.data, 'bones'):
        bones = list(obj.data.bones)
        extra.append(f"Костей: {len(bones)}")
        if globe_mode and bones:
            bnames = ", ".join(b.name for b in bones[:5])
            extra.append(f"Имена костей: {bnames}")
    elif obj.type == 'LATTICE' and obj.data:
        extra.append(f"Сетка деформации: {obj.data.points_u} × {obj.data.points_v} × {obj.data.points_w} узлов")
    elif obj.type == 'EMPTY':
        disp_t = getattr(obj, "empty_display_type", "")
        disp_s = getattr(obj, "empty_display_size", 1.0)
        extra.append(f"Отображение: {disp_t}, размер {_fmt_num(disp_s)} м")
    elif obj.type == 'SPEAKER' and obj.data:
        vol = getattr(obj.data, "volume", 1.0)
        extra.append(f"Громкость: {_fmt_num(vol)}")
    extra.append(f"Центр X {_fmt_num(loc.x)}, Y {_fmt_num(loc.y)}, Z {_fmt_num(loc.z)} м")

    if globe_mode:
        return (
            f"{header}. Габариты {_fmt_num(hx)} × {_fmt_num(hy)} × {_fmt_num(hz)} м. "
            f"Сверху +Z {_fmt_num(bmax.z - cw.z)} м, Снизу -Z {_fmt_num(cw.z - bmin.z)} м, "
            f"Справа +X {_fmt_num(bmax.x - cw.x)} м, Слева -X {_fmt_num(cw.x - bmin.x)} м, "
            f"Сзади +Y {_fmt_num(bmax.y - cw.y)} м, Спереди -Y {_fmt_num(cw.y - bmin.y)} м. "
            + ". ".join(extra)
        )
    return f"{header}: габариты {_fmt_num(hx)} × {_fmt_num(hy)} × {_fmt_num(hz)} м. " + ". ".join(extra)

def _analyze_wire_bmesh(obj, bm_base, globe_mode, header, verts_w, min_w, max_w, hx, hy, hz, center_w, sp_note, font_note):
    total_len = sum(e.calc_length() for e in bm_base.edges)
    open_ends = [v for v in bm_base.verts if len(v.link_edges) == 1]
    mods = [m.name for m in obj.modifiers]

    if globe_mode:
        dz_pos = float(max_w[2] - center_w.z)
        dz_neg = float(center_w.z - min_w[2])
        dx_pos = float(max_w[0] - center_w.x)
        dx_neg = float(center_w.x - min_w[0])
        dy_pos = float(max_w[1] - center_w.y)
        dy_neg = float(center_w.y - min_w[1])
        closure_txt = "Замкнутый контур" if len(open_ends) == 0 else f"Разомкнутая кривая (концов: {len(open_ends)})"
        extra = [f"Точек: {len(bm_base.verts)}, сегментов: {len(bm_base.edges)}, длина {_fmt_num(total_len)} м", closure_txt]
        if sp_note:
            extra.append(sp_note)
        if font_note:
            extra.append(font_note)
        if mods:
            extra.append(f"Модификаторы: {', '.join(mods)}")
        return (
            f"{header}. Габариты {_fmt_num(hx)} × {_fmt_num(hy)} × {_fmt_num(hz)} м. "
            f"Сверху +Z {_fmt_num(dz_pos)} м, Снизу -Z {_fmt_num(dz_neg)} м, "
            f"Справа +X {_fmt_num(dx_pos)} м, Слева -X {_fmt_num(dx_neg)} м, "
            f"Сзади +Y {_fmt_num(dy_pos)} м, Спереди -Y {_fmt_num(dy_neg)} м. "
            + ". ".join(extra)
        )

    parts = [f"{header}: габариты {_fmt_num(hx)} × {_fmt_num(hy)} × {_fmt_num(hz)} м"]
    centered = verts_w - np.array([center_w.x, center_w.y, center_w.z], dtype=np.float64)
    pca_pts = centered[::max(1, len(centered) // 12000)] if len(centered) > 12000 else centered
    _, _, vt = np.linalg.svd(pca_pts, full_matrices=False)
    proj = centered @ vt.T
    p_ext = proj.max(axis=0) - proj.min(axis=0)
    is_planar = float(p_ext.min()) < 0.05 * max(float(p_ext.max()), 1e-5)

    if len(open_ends) == 0 and len(bm_base.edges) >= 3:
        radii = np.linalg.norm(centered, axis=1)
        r_mean = float(radii.mean())
        r_std = float(radii.std())
        if is_planar and r_mean > 1e-5 and r_std < 0.05 * r_mean:
            parts.append(f"ровная окружность (радиус {_fmt_num(r_mean)} м, диаметр {_fmt_num(2.0 * r_mean)} м)")
            parts.append(f"длина {_fmt_num(total_len)} м, замкнутый контур")
        else:
            kind_txt = "плоский " if is_planar else "пространственный "
            parts.append(f"замкнутый {kind_txt}контур длиной {_fmt_num(total_len)} м")
    elif len(open_ends) == 2:
        chord = (open_ends[1].co - open_ends[0].co).length
        if total_len <= chord * 1.03 + 1e-4:
            parts.append(f"прямая линия длиной {_fmt_num(total_len)} м")
        else:
            parts.append(f"изогнутая кривая (дуга) длиной {_fmt_num(total_len)} м, расстояние между концами {_fmt_num(chord)} м")
    else:
        parts.append(f"проволочный контур длиной {_fmt_num(total_len)} м (концов: {len(open_ends)})")

    if sp_note:
        parts.append(sp_note)
    if font_note:
        parts.append(font_note)
    return ". ".join(parts)

def _analyze_mesh_object(context, obj, globe_mode):
    oname = _obj_display_name(obj)
    t_ru = _TYPE_NAMES_RU.get(obj.type, obj.type)
    header = oname if obj.type == 'MESH' else f"{oname} ({t_ru})"

    if obj.type == 'LIGHT':
        return _lights_shadow_report(context, globe_mode, target_light=obj)
    if obj.type == 'CAMERA':
        return _camera_cone_report(context, globe_mode, target_cam=obj)
    if obj.type not in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT'):
        return _analyze_special_object(obj, globe_mode, header, t_ru)

    font_body = obj.data.body.strip() if (obj.type == 'FONT' and obj.data and getattr(obj.data, 'body', None)) else ""
    font_note = f"Текст: «{font_body[:80]}»" if font_body else ""
    sp_note = ""
    splines = []
    if obj.type in ('CURVE', 'SURFACE') and obj.data and hasattr(obj.data, 'splines'):
        splines = list(obj.data.splines)
        ctrl_cnt = sum((len(sp.bezier_points) if sp.type == 'BEZIER' else len(sp.points)) for sp in splines)
        if obj.type == 'SURFACE' and splines and hasattr(splines[0], 'point_count_u'):
            sp0 = splines[0]
            sp_note = f"сплайнов: {len(splines)}, сетка {sp0.point_count_u}×{sp0.point_count_v} (контрольных точек: {ctrl_cnt})"
        else:
            sp_note = f"сплайнов: {len(splines)}, контрольных точек: {ctrl_cnt}"

    depsgraph = context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    eval_mesh = None
    bm_base = bmesh.new()
    try:
        eval_mesh = obj_eval.to_mesh()
        if eval_mesh is not None and len(eval_mesh.vertices) > 0:
            bm_base.from_mesh(eval_mesh)
        elif obj.type in ('CURVE', 'SURFACE') and obj.data and hasattr(obj.data, 'splines'):
            for sp in obj.data.splines:
                pts_sp = [bp.co.copy() for bp in sp.bezier_points] if sp.type == 'BEZIER' else [p.co.xyz.copy() for p in sp.points]
                bverts = [bm_base.verts.new(p) for p in pts_sp]
                for i in range(len(bverts) - 1):
                    try:
                        bm_base.edges.new((bverts[i], bverts[i + 1]))
                    except ValueError:
                        pass
                if sp.use_cyclic_u and len(bverts) >= 3:
                    try:
                        bm_base.edges.new((bverts[-1], bverts[0]))
                    except ValueError:
                        pass

        if len(bm_base.verts) == 0:
            if obj.type == 'META' and obj.data and hasattr(obj.data, 'elements'):
                els = list(obj.data.elements)
                el_map = {'BALL': 'шар', 'CAPSULE': 'капсула', 'PLANE': 'плоскость', 'ELLIPSOID': 'эллипсоид', 'CUBE': 'куб'}
                bmin, bmax = _world_bbox(obj)
                ext = bmax - bmin
                kinds = ", ".join(el_map.get(el.type, el.type) for el in els[:4])
                r_txt = f", радиус {_fmt_num(els[0].radius)} м" if els else ""
                return f"{header}: габариты {_fmt_num(ext.x)} × {_fmt_num(ext.y)} × {_fmt_num(ext.z)} м. Элементов: {len(els)} ({kinds}{r_txt})"
            if sp_note:
                bmin, bmax = _world_bbox(obj)
                ext = bmax - bmin
                return f"{header}: габариты {_fmt_num(ext.x)} × {_fmt_num(ext.y)} × {_fmt_num(ext.z)} м. {sp_note}"
            return f"{header}: пустая геометрия (0 вершин)" + (f". {font_note}" if font_note else "")

        if obj.type in ('SURFACE', 'CURVE', 'FONT', 'META') and 0 < len(bm_base.verts) <= 25000:
            bmesh.ops.remove_doubles(bm_base, verts=bm_base.verts, dist=1e-4)

        mw = obj.matrix_world
        # Convert private BMesh copy to world space once for exact normals/areas/coords in RAM
        bm_base.transform(mw)
        bm_base.normal_update()
        bm_base.verts.ensure_lookup_table()
        bm_base.edges.ensure_lookup_table()
        bm_base.faces.ensure_lookup_table()

        verts_w = np.array([[v.co.x, v.co.y, v.co.z] for v in bm_base.verts], dtype=np.float64)
        min_w = verts_w.min(axis=0)
        max_w = verts_w.max(axis=0)
        ext_w = max_w - min_w
        hx, hy, hz = float(ext_w[0]), float(ext_w[1]), float(ext_w[2])
        center_w_np = (min_w + max_w) * 0.5
        center_w = mathutils.Vector(center_w_np)
        centered = verts_w - center_w_np

        user_parts_note = _extract_user_part_labels_ram(obj, mw, center_w, ext_w)

        if len(bm_base.faces) == 0:
            return _analyze_wire_bmesh(
                obj, bm_base, globe_mode, header, verts_w, min_w, max_w, hx, hy, hz, center_w, sp_note, font_note
            )

        topo_comps = _euler_genus_components(bm_base)
        b_edges_cnt, b_loops_cnt = _count_boundary_loops(bm_base)
        max_genus = max((c[4] for c in topo_comps), default=-1)

        if globe_mode:
            dz_pos = float(max_w[2] - center_w.z)
            dz_neg = float(center_w.z - min_w[2])
            dx_pos = float(max_w[0] - center_w.x)
            dx_neg = float(center_w.x - min_w[0])
            dy_pos = float(max_w[1] - center_w.y)
            dy_neg = float(center_w.y - min_w[1])
            closure_txt = "Замкнутый объём" if b_edges_cnt == 0 else f"Открытых краёв: {b_edges_cnt} (петель: {b_loops_cnt})"
            mods = [m.name for m in obj.modifiers]
            mod_txt = f". Модификаторы: {', '.join(mods)}" if mods else ""
            extra_txt = (f". {font_note}" if font_note else "") + (f". {user_parts_note}" if user_parts_note else "") + (f". {sp_note}" if sp_note else "")
            return (
                f"{header}. Габариты {_fmt_num(hx)} × {_fmt_num(hy)} × {_fmt_num(hz)} м. "
                f"Сверху +Z {_fmt_num(dz_pos)} м, Снизу -Z {_fmt_num(dz_neg)} м, "
                f"Справа +X {_fmt_num(dx_pos)} м, Слева -X {_fmt_num(dx_neg)} м, "
                f"Сзади +Y {_fmt_num(dy_pos)} м, Спереди -Y {_fmt_num(dy_neg)} м. "
                f"Вершин: {len(bm_base.verts)}, рёбер: {len(bm_base.edges)}, граней: {len(bm_base.faces)}. "
                f"{closure_txt}{extra_txt}{mod_txt}"
            )

        parts = [f"{header}: габариты {_fmt_num(hx)} × {_fmt_num(hy)} × {_fmt_num(hz)} м"]
        if font_note:
            parts.append(font_note)
        if len(topo_comps) >= 2:
            parts.append(f"состоит из {len(topo_comps)} отдельных элементов")

        if len(centered) > 12000:
            stride = max(1, len(centered) // 12000)
            pca_pts = centered[::stride]
        else:
            pca_pts = centered
        _, _, vt = np.linalg.svd(pca_pts, full_matrices=False)

        # 1. Ring / Torus directly from RAM topology + symmetry normal
        if max_genus >= 1:
            axis_n = vt[2]
            if hz <= min(hx, hy) * 0.8:
                axis_n = np.array([0.0, 0.0, 1.0], dtype=np.float64)
            h_proj = centered @ axis_n
            ring_h = float(h_proj.max() - h_proj.min())
            r_ring = np.linalg.norm(centered - np.outer(h_proj, axis_n), axis=1)
            r_min = float(r_ring.min())
            r_max = float(r_ring.max())
            if r_min > 0.08 * max(r_max, 1e-6):
                hole_d = 2.0 * r_min
                rim_w = r_max - r_min
                parts.append(
                    f"кольцо (тор) со сквозным отверстием в центре диаметром {_fmt_num(hole_d)} м, "
                    f"толщина обода {_fmt_num(rim_w)} на {_fmt_num(ring_h)} м"
                )
                parts.append("замкнутый объём" if b_edges_cnt == 0 else f"открытых краёв: {b_edges_cnt}")
                return ". ".join(parts)
            parts.append(f"имеет сквозное отверстие / ручку (петель: {max_genus})")

        # 2. Height-binned local XY centerlines to evaluate face normals cleanly
        n_bins = 8
        bin_centers = [center_w_np[:2]] * n_bins
        if hz > 1e-5:
            z_idx = np.clip(((verts_w[:, 2] - float(min_w[2])) / hz * n_bins).astype(int), 0, n_bins - 1)
            for b_i in range(n_bins):
                pts_b = verts_w[z_idx == b_i, :2]
                if len(pts_b) > 0:
                    bin_centers[b_i] = pts_b.mean(axis=0)

        faces = bm_base.faces
        n_faces = len(faces)
        f_stride = max(1, n_faces // 15000)
        norm_groups = []
        total_area = 0.0
        out_area = 0.0
        out_r_sum = 0.0
        in_area = 0.0
        in_r_sum = 0.0
        z_min_w = float(min_w[2])

        for idx in range(0, n_faces, f_stride):
            f = faces[idx]
            fa = f.calc_area()
            if fa <= 1e-10:
                continue
            fn = f.normal
            fc = f.calc_center_median()
            total_area += fa

            if len(norm_groups) <= 32:
                matched = False
                for g in norm_groups:
                    gn = g[0].normalized()
                    if gn.dot(fn) > 0.992:
                        g[0] += fn * fa
                        g[1] += fa
                        matched = True
                        break
                if not matched:
                    norm_groups.append([fn * fa, fa])

            bi = min(n_bins - 1, max(0, int((fc.z - z_min_w) / hz * n_bins))) if hz > 1e-5 else 0
            cxy = bin_centers[bi]
            rx = fc.x - float(cxy[0])
            ry = fc.y - float(cxy[1])
            r_xy = math.hypot(rx, ry)
            if abs(fn.z) < 0.5 and r_xy > 1e-5:
                rad_dot = (rx * fn.x + ry * fn.y) / r_xy
                if rad_dot > 0.25:
                    out_area += fa
                    out_r_sum += r_xy * fa
                elif rad_dot < -0.25:
                    in_area += fa
                    in_r_sum += r_xy * fa

        has_hollow_walls = False
        r_out = (out_r_sum / out_area) if out_area > 0.0 else 0.0
        r_in = (in_r_sum / in_area) if in_area > 0.0 else 0.0
        cav_floors = []
        cav_ceils = []
        any_top_cap = False
        any_bot_cap = False
        if out_area > 0.0 and in_area > 0.08 * out_area and r_in < r_out - 0.01:
            has_hollow_walls = True
            inner_lim = max(r_in * 0.85, r_in - 0.015)
            z_max_w = float(max_w[2])
            for idx in range(0, n_faces, f_stride):
                f = faces[idx]
                fn = f.normal
                if abs(fn.z) <= 0.7:
                    continue
                fc = f.calc_center_median()
                bi = min(n_bins - 1, max(0, int((fc.z - z_min_w) / hz * n_bins))) if hz > 1e-5 else 0
                cxy = bin_centers[bi]
                r_xy = math.hypot(fc.x - float(cxy[0]), fc.y - float(cxy[1]))
                if r_xy < inner_lim:
                    if fc.z >= z_max_w - 0.08 * max(hz, 1e-4):
                        any_top_cap = True
                    if fc.z <= z_min_w + 0.08 * max(hz, 1e-4):
                        any_bot_cap = True
                    if fn.z > 0.7 and z_min_w + 0.005 < fc.z < z_max_w - 0.08 * max(hz, 1e-4):
                        cav_floors.append(fc.z)
                    elif fn.z < -0.7 and z_min_w + 0.08 * max(hz, 1e-4) < fc.z < z_max_w - 0.005:
                        cav_ceils.append(fc.z)

        # 3. Flat-faced Cube / Rectangular block
        is_box = False
        if not has_hollow_walls and max_genus == 0 and total_area > 0.0 and 6 <= len(norm_groups) <= 12:
            norm_groups.sort(key=lambda g: -g[1])
            top6 = norm_groups[:6]
            area6 = sum(g[1] for g in top6)
            if area6 >= 0.90 * total_area:
                dirs6 = [g[0].normalized() for g in top6]
                ortho_ok = True
                for i_d, d0 in enumerate(dirs6):
                    has_opp = any(d0.dot(dirs6[j_d]) < -0.92 for j_d in range(6) if j_d != i_d)
                    all_ortho_or_opp = all(abs(d0.dot(dirs6[j_d])) < 0.08 or abs(d0.dot(dirs6[j_d])) > 0.92 for j_d in range(6) if j_d != i_d)
                    if not (has_opp and all_ortho_or_opp):
                        ortho_ok = False
                        break
                if ortho_ok:
                    is_box = True
                    proj_ext = np.ptp(centered @ vt.T, axis=0)
                    e_min, e_max = float(proj_ext.min()), float(proj_ext.max())
                    if e_max - e_min < 0.05 * max(e_max, 1e-5):
                        parts.append("ровный куб (6 плоских граней)")
                    else:
                        parts.append("прямоугольный блок (6 плоских граней)")

        # 4. Sphere / Ellipsoid
        is_sphere = False
        if not is_box and not has_hollow_walls and max_genus == 0:
            proj = centered @ vt.T
            p_ext = proj.max(axis=0) - proj.min(axis=0)
            half_pca = np.maximum(p_ext * 0.5, 1e-6)
            r_norm = np.linalg.norm(proj / half_pca, axis=1)
            if float(np.std(r_norm)) < 0.055:
                is_sphere = True
                mean_r_w = float(np.linalg.norm(centered, axis=1).mean())
                if float(p_ext.max() - p_ext.min()) < 0.08 * max(float(p_ext.max()), 1e-5):
                    parts.append(f"шар (радиус {_fmt_num(mean_r_w)} м)")
                else:
                    parts.append("овальный эллипсоид")

        # 4.5 Open NURBS surface patch / single-loop sheet read directly from RAM splines & boundary loops
        is_open_sheet = False
        if not is_box and not is_sphere and not has_hollow_walls and n_faces >= 1:
            is_open_surface_spline = (
                obj.type == 'SURFACE' and splines and
                all((not getattr(sp, 'use_cyclic_u', False)) and (not getattr(sp, 'use_cyclic_v', False)) for sp in splines)
            )
            is_flat_single_loop = (max_genus == -1 and b_loops_cnt == 1 and hz <= 0.45 * max(hx, hy, 1e-4))
            if is_open_surface_spline or is_flat_single_loop:
                is_open_sheet = True
                if hz < 0.01 * max(hx, hy, 1e-4):
                    parts.append("плоский лист (пластина), один открытый контур по краю")
                else:
                    parts.append(f"изогнутый лист (участок поверхности), выгиб по высоте {_fmt_num(hz)} м, один открытый контур по краю")

        # 5. Tiered island slicing + bottom-to-top profile directly from edge intersections in RAM
        tier_islands = None
        has_split_tiers = False
        if not is_box and not is_sphere and not is_open_sheet and hz > 1e-4 and len(bm_base.edges) > 0:
            e_arr = np.array(
                [[[e.verts[0].co.x, e.verts[0].co.y, e.verts[0].co.z],
                  [e.verts[1].co.x, e.verts[1].co.y, e.verts[1].co.z]] for e in bm_base.edges],
                dtype=np.float64,
            )
            tier_islands = _slice_tier_islands(bm_base, e_arr, min_w[2], hz)
            if tier_islands is not None:
                n_bot, n_mid, n_top = tier_islands
                if n_bot >= 2:
                    has_hollow_walls = False
                if max(tier_islands) >= 2:
                    has_split_tiers = True
                    if n_bot >= 2 and n_top == 1:
                        parts.append(f"внизу отдельных опор: {n_bot}, вверху единая часть")
                    elif n_bot == 1 and n_top >= 2:
                        parts.append(f"снизу цельная опора, вверху разделяется на {n_top} частей")
                    else:
                        parts.append(f"отдельных частей по ярусам (низ / середина / верх): {n_bot} → {n_mid} → {n_top}")

            z0 = e_arr[:, 0, 2]
            z1 = e_arr[:, 1, 2]
            dz = z1 - z0
            valid_e = np.abs(dz) > 1e-6
            band_widths = []
            for frac in (0.04, 0.25, 0.50, 0.75, 0.96):
                zk = float(min_w[2]) + frac * hz
                mask = valid_e & (((z0 <= zk) & (zk <= z1)) | ((z1 <= zk) & (zk <= z0)))
                if np.any(mask):
                    t_e = (zk - z0[mask]) / dz[mask]
                    pts_xy = e_arr[mask, 0, :2] + t_e[:, None] * (e_arr[mask, 1, :2] - e_arr[mask, 0, :2])
                    c2 = pts_xy.mean(axis=0)
                    w_k = float(2.0 * np.hypot(pts_xy[:, 0] - c2[0], pts_xy[:, 1] - c2[1]).max())
                    band_widths.append(w_k)
            if len(band_widths) >= 5 and not has_split_tiers:
                w_bot, _, w_mid, _, w_top = band_widths
                w_max = max(band_widths)
                if w_max - min(band_widths) < 0.08 * max(w_max, 1e-4):
                    parts.append(f"прямой по высоте (цилиндр / столб): ширина {_fmt_num(w_mid)} м")
                elif w_bot > w_mid * 0.92 and w_mid > w_top * 0.92 and w_top < w_bot * 0.70:
                    parts.append(f"сужается кверху (конус / пирамида): у дна {_fmt_num(w_bot)}, середина {_fmt_num(w_mid)}, у верха {_fmt_num(w_top)} м")
                elif w_top > w_mid * 0.92 and w_mid > w_bot * 0.92 and w_bot < w_top * 0.70:
                    parts.append(f"расширяется кверху (чаша / воронка): у дна {_fmt_num(w_bot)}, середина {_fmt_num(w_mid)}, у верха {_fmt_num(w_top)} м")
                elif w_mid > max(w_bot, w_top) * 1.14:
                    parts.append(f"выпуклый посередине (бочка): у дна {_fmt_num(w_bot)}, середина {_fmt_num(w_mid)}, у верха {_fmt_num(w_top)} м")
                elif w_mid < min(w_bot, w_top) * 0.84:
                    parts.append(f"сужается посередине (талия): у дна {_fmt_num(w_bot)}, середина {_fmt_num(w_mid)}, у верха {_fmt_num(w_top)} м")
                else:
                    parts.append(f"переменная ширина снизу вверх: дно {_fmt_num(w_bot)}, середина {_fmt_num(w_mid)}, верх {_fmt_num(w_top)} м")

        # 5.5 Principle A: 6-side relief character, localized protrusions & cavities directly from RAM
        if not is_box and not is_sphere and not is_open_sheet and max_genus == 0 and n_faces >= 4:
            skip_sides = set()
            if has_hollow_walls:
                if not any_top_cap:
                    skip_sides.add("сверху +Z")
                if not any_bot_cap:
                    skip_sides.add("снизу -Z")
            convex_ridges, concave_crevices, protrusions, cavities = _analyze_relief_from_ram(
                bm_base, verts_w, min_w, max_w, ext_w, center_w, skip_sides=skip_sides
            )
            if not has_hollow_walls and concave_crevices >= 4 and convex_ridges >= 4:
                parts.append(f"неровный рельеф (резких гребней: {convex_ridges}, складок-впадин: {concave_crevices})")
            if protrusions:
                p_txt = ", ".join(f"{side} на {_fmt_num(amt)} м" for amt, side in protrusions[:2])
                parts.append(f"выступы: {p_txt}")
            if cavities:
                c_txt = ", ".join(f"{side} глубиной {_fmt_num(amt)} м" for amt, side in cavities[:2])
                parts.append(f"впадины: {c_txt}")

        # 6. Hollow / Cup / Pipe / Closure summary from RAM face normals
        if has_hollow_walls:
            wall_t = r_out - r_in
            inner_d = 2.0 * r_in
            z_max_w = float(max_w[2])
            if not any_top_cap and cav_floors:
                z_fl = sum(cav_floors) / len(cav_floors)
                parts.append(
                    f"полый внутри (стакан / чаша): открыт сверху, глубина внутри {_fmt_num(z_max_w - z_fl)} м, "
                    f"внутренний диаметр {_fmt_num(inner_d)} м, толщина стенок {_fmt_num(wall_t)} м, дно закрыто"
                )
            elif not any_bot_cap and cav_ceils:
                z_cl = sum(cav_ceils) / len(cav_ceils)
                parts.append(
                    f"полый внутри (перевёрнутая чаша): открыт снизу, глубина внутри {_fmt_num(z_cl - z_min_w)} м, "
                    f"внутренний диаметр {_fmt_num(inner_d)} м, толщина стенок {_fmt_num(wall_t)} м"
                )
            elif not any_top_cap and not any_bot_cap:
                parts.append(f"сквозная полая труба: внутренний диаметр {_fmt_num(inner_d)} м, толщина стенок {_fmt_num(wall_t)} м")
            else:
                parts.append(f"полый внутри: диаметр полости {_fmt_num(inner_d)} м, толщина стенок {_fmt_num(wall_t)} м")
        else:
            if b_edges_cnt == 0:
                parts.append("сплошной закрытый объём")
            elif not is_open_sheet:
                parts.append(f"открытая оболочка (открытых краёв: {b_edges_cnt})")

        if user_parts_note:
            parts.append(user_parts_note)
        if sp_note:
            parts.append(sp_note)
        return ". ".join(parts)
    finally:
        bm_base.free()
        try:
            obj_eval.to_mesh_clear()
        except Exception:
            pass

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
        msg = _analyze_mesh_object(context, target, self.globe_mode)
        _speak_3d(msg, 1)
        return {'FINISHED'}
