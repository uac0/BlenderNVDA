import bpy

from .bridge import (
    _bridge,
    _is_popup_open,
    _set_zone,
    _speak_3d,
)

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
