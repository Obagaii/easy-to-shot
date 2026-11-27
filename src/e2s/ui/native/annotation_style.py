from dataclasses import replace

from PySide6.QtCore import QEvent, QObject, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QHideEvent
from PySide6.QtWidgets import (
    QFontDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import LineEdit

from e2s.annotation.elements import (
    ERASER_TOOLS,
    HIGHLIGHT_TOOLS,
    MAX_FONT_SIZE_PX,
    MAX_STROKE_WIDTH_PX,
    MIN_FONT_SIZE_PX,
    SHAPE_TOOLS,
    Element,
    Stroke,
    Text,
    Tool,
    WatermarkStyle,
)
from e2s.ui.native.dialogs import prompt_text
from e2s.ui.native.annotation_color_picker import AnnotationColorPicker
from e2s.ui.native.annotation_controls import (
    CAPTURE_CONTROLS_STYLE,
    ColorControl,
    ModeControl,
    NumericPresets,
    OpacityControl,
    PanelPosition,
    SizeControl,
    color_name,
    describe_control,
)
from e2s.ui.native.toolbar_icons import toolbar_icon

_SIDEBAR_WIDTH = 244
_HEADS = {
    "none": "无", "open": "开放箭头", "bar": "竖线", "dot": "圆点",
    "circle": "实心圆", "circle_outline": "空心圆", "indented_triangle": "凹尾三角",
    "triangle": "实心三角", "triangle_outline": "空心三角", "diamond": "实心菱形",
    "diamond_outline": "空心菱形", "crowfoot_one": "单线", "crowfoot_many": "鱼尾",
    "crowfoot_one_or_many": "单线鱼尾",
}
_ROLES = {
    Tool.RECTANGLE: ("color", "fill_color", "width_px", "line_style", "line_effect",
                     "corner_radius_px", "opacity", "layers"),
    Tool.ELLIPSE: ("color", "fill_color", "width_px", "line_style", "line_effect",
                   "opacity", "layers"),
    Tool.ARROW: ("color", "width_px", "line_style", "line_effect", "arrow_type", "arrow_outline",
                 "arrow_outline_width", "arrow_ratio", "start_head", "shaft", "end_head",
                 "opacity", "layers"),
    Tool.PEN: ("color", "fill_color", "width_px", "line_style", "brush_mode",
               "opacity", "layers"),
    Tool.TEXT: ("color", "family", "font_size_px", "emphasis", "alignment", "outline",
                "outline_width", "background", "corner_radius_px", "opacity", "layers"),
    Tool.RECT_HIGHLIGHT: ("highlight_mode", "color", "highlight_outline", "highlight_border",
                          "opacity", "layers"),
    Tool.HIGHLIGHT: ("highlight_mode", "color", "brush_width", "opacity", "layers"),
    Tool.ERASER: ("eraser_mode",),
    Tool.RECT_ERASER: ("eraser_mode",),
    Tool.BRUSH_ERASER: ("eraser_mode", "brush_width"),
    Tool.WATERMARK: ("color", "watermark_text", "watermark_font_size", "templates",
                     "angle", "gap_px", "watermark_opacity"),
}
_MODES = {
    "highlight_mode": ("高亮模式", {
        "rect_highlight": ("矩形高亮", "rectangle"), "highlight": ("画笔高亮", "highlight"),
    }),
    "eraser_mode": ("橡皮擦模式", {
        "eraser": ("元素橡皮擦", "eraser"), "rect_eraser": ("矩形橡皮擦", "rect_eraser"),
        "brush_eraser": ("画笔橡皮擦", "brush_eraser"),
    }),
}
_SEGMENTS = {
    "arrow_type": ("箭头路径", {
        "straight": ("直箭头", "arrow"), "curve": ("曲线箭头", "arrow_curve"),
        "elbow": ("折线箭头", "arrow_elbow"),
    }),
    "brush_mode": ("画笔模式", {
        "regular": ("普通画笔", "pen"), "pressure": ("压感画笔", "brush_pressure"),
    }),
    "line_style": ("边框样式", {
        "solid": ("实线", "line_solid"), "dash": ("虚线", "line_dash"), "dot": ("点线", "line_dot"),
    }),
    "line_effect": ("线条风格", {
        "precise": ("标准", "line_precise"), "architect": ("建筑手绘", "line_architect"),
        "artist": ("艺术手绘", "line_artist"),
    }),
    "alignment": ("文字对齐", {
        "left": ("左对齐", "align_left"), "center": ("居中", "align_center"),
        "right": ("右对齐", "align_right"),
    }),
    "shaft": ("箭杆", {
        "solid": ("普通箭杆", "arrow"), "tapered": ("渐细箭杆", "arrow_tapered"),
    }),
}
_COLORS = {
    "color": "描边", "fill_color": "背景", "outline": "文字描边", "background": "文字背景",
    "arrow_outline": "箭头描边", "highlight_outline": "高亮描边",
}
_NUMBERS = {"arrow_ratio": ("箭头大小", 5, 300, "%"), "angle": ("水印角度", -180, 180, "°"),
            "gap_px": ("水印间距", 0, 512, " px")}
_WIDTHS = {2: ("细", "width_thin"), 4: ("中", "width_medium"), 8: ("粗", "width_thick")}
_OUTLINE_WIDTHS = {0: ("无描边", "line_dot"), **_WIDTHS}
_SIZE_ICONS = ("size_s", "size_m", "size_l", "size_xl")


def _size_presets(*sizes: int) -> dict[int, tuple[str, str]]:
    return {size: (f"{size} px", icon) for size, icon in zip(sizes, _SIZE_ICONS, strict=True)}


_PRESETS = {
    "width_px": ("描边宽度", _WIDTHS, 1, MAX_STROKE_WIDTH_PX),
    "brush_width": ("画笔宽度", _size_presets(24, 30, 42, 54), 1, MAX_STROKE_WIDTH_PX),
    "font_size_px": ("字号", _size_presets(24, 30, 42, 54), MIN_FONT_SIZE_PX, MAX_FONT_SIZE_PX),
    "watermark_font_size": ("字号", _size_presets(12, 16, 24, 30),
                            MIN_FONT_SIZE_PX, MAX_FONT_SIZE_PX),
    "outline_width": ("文字描边宽度", _OUTLINE_WIDTHS, 0, 24),
    "arrow_outline_width": ("箭头描边宽度", _OUTLINE_WIDTHS, 0, 24),
    "highlight_border": ("高亮描边宽度", _OUTLINE_WIDTHS, 0, 24),
    "corner_radius_px": ("边角", {0: ("直角", "corner_square"), 12: ("圆角", "corner_round")}, 0, 128),
}
_ALIASES = {"brush_width": "width_px", "watermark_font_size": "font_size_px"}
_LAYER_ACTIONS = {
    "bottom": ("置于底层", "layer_bottom"), "lower": ("下移一层", "layer_lower"),
    "raise": ("上移一层", "layer_raise"), "top": ("置于顶层", "layer_top"),
}
_EMPHASIS = {
    "bold": ("粗体", "bold"), "italic": ("斜体", "italic"),
    "underline": ("下划线", "underline"), "strikethrough": ("删除线", "strikethrough"),
}


class AnnotationStyleModel:
    """Store creation defaults separately from the currently selected element."""

    def __init__(self) -> None:
        self._defaults: dict[Tool, Element] = {
            tool: Stroke(tool, ((0, 0),), "#1f1f1f", 4)
            for tool in (*SHAPE_TOOLS, Tool.ARROW, Tool.PEN, *HIGHLIGHT_TOOLS, *ERASER_TOOLS)
        }
        self._defaults.update({
            Tool.RECT_HIGHLIGHT: Stroke(Tool.RECT_HIGHLIGHT, ((0, 0),), "#60fadb14", 12),
            Tool.HIGHLIGHT: Stroke(Tool.HIGHLIGHT, ((0, 0),), "#60fadb14", 24),
            Tool.BRUSH_ERASER: Stroke(Tool.BRUSH_ERASER, ((0, 0),), "#000000", 30),
            Tool.TEXT: Text((0, 0), "", "#1f1f1f", 24),
            Tool.WATERMARK: Text((0, 0), "", "#000000", 16, Tool.WATERMARK),
        })

    def get(self, tool: Tool) -> Element | None:
        return self._defaults.get(tool)

    def set(self, value: Element) -> None:
        self._defaults[value.tool] = value


class AnnotationStylePanel(QFrame):
    variant_changed = Signal(object)
    style_changed = Signal(object)
    watermark_preview_changed = Signal(object)
    color_preview_changed = Signal(object)
    color_sampling_requested = Signal()
    opacity_preview_changed = Signal(object)
    selection_requested = Signal(str)
    selection_opacity_requested = Signal(int)
    layer_requested = Signal(str)
    alignment_requested = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setProperty("toolbarSurface", True)
        self.setObjectName("toolSettings")
        self.setAccessibleName("工具属性")
        self.setStyleSheet(CAPTURE_CONTROLS_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 9, 12)
        layout.setSpacing(3)
        grip = QToolButton(self)
        grip.setFixedSize(50, 24)
        grip.setIconSize(QSize(45, 45))
        grip.setIcon(toolbar_icon("drag_sidebar"))
        describe_control(grip, "拖动属性侧栏")
        layout.addWidget(grip, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.position = PanelPosition(self, grip)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._scroll)
        self._content = QWidget()
        self._content.setObjectName("styleSections")
        self._sections_layout = QVBoxLayout(self._content)
        self._sections_layout.setContentsMargins(2, 0, 3, 1)
        self._sections_layout.setSpacing(13)
        self._sections_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._content)

        self._model = AnnotationStyleModel()
        self._tool = Tool.MOVE
        self._value: Element | None = None
        self._is_selection = False
        self._is_loading = False
        self._roles: tuple[str, ...] = ()
        self._settings = QSettings("EasyToShot", "Annotation")
        self._controls: dict[str, QWidget] = {}
        self._sections: dict[str, QWidget] = {}
        self._picker_role: str | None = None
        self._sample_role: str | None = None
        self._picker = AnnotationColorPicker(parent)
        self._picker.setStyleSheet(CAPTURE_CONTROLS_STYLE)
        self._picker.color_previewed.connect(self._preview_color)
        self._picker.color_committed.connect(self._commit_color)
        self._picker.sample_requested.connect(self._start_color_sampling)
        self._picker.closed.connect(self._clear_color_preview)
        self._scroll.verticalScrollBar().valueChanged.connect(self._picker.hide)
        self.position.moved.connect(self._picker.reposition)
        self._create_controls()
        self.hide()

    @property
    def value(self) -> Element | None:
        return self._value

    @property
    def has_controls(self) -> bool:
        return bool(self._roles)

    def show_style(
        self, tool: Tool, element: Element | None, *, selected_opacities: tuple[int, ...] = ()
    ) -> None:
        value = element if element is not None else self._model.get(tool)
        roles = _ROLES.get(value.tool if value else tool, ())
        if element is not None and element.tool is not Tool.WATERMARK:
            roles = tuple(role for role in roles if role not in _MODES)
            if tool is Tool.SELECT:
                roles += ("selection_actions",)
        elif selected_opacities:
            roles = ("layers", "horizontal", "vertical", "opacity", "selection_actions")
        self._controls["layers"].setEnabled(
            bool(selected_opacities) or (element is not None and element.tool is not Tool.WATERMARK)
        )
        for role in ("horizontal", "vertical"):
            self._controls[role].findChild(QToolButton, "distribute").setEnabled(
                len(selected_opacities) >= 3
            )
        if selected_opacities:
            slider = self._controls["opacity"]
            self._is_loading = True
            slider.set_value(round(sum(selected_opacities) / len(selected_opacities)))
            if len(set(selected_opacities)) > 1:
                slider.setToolTip("所选元素有不同的透明度")
            self._is_loading = False
        if (tool, value, roles) == (self._tool, self._value, self._roles):
            return
        self._tool, self._value = tool, value
        self._is_selection = element is not None
        if roles != self._roles:
            self._roles = roles
            self._layout_sections()
        color_label = {
            Tool.TEXT: "文字颜色", Tool.WATERMARK: "水印颜色",
            Tool.RECT_HIGHLIGHT: "高亮颜色", Tool.HIGHLIGHT: "高亮颜色",
        }.get(value.tool if value else tool, _COLORS["color"])
        self._sections["color"].findChild(QLabel).setText(color_label)
        self._load_values()

    def fit_to_viewport(self, viewport: QSize) -> None:
        self._sections_layout.activate()
        height = self._content.sizeHint().height() + 50
        self.resize(min(_SIDEBAR_WIDTH, viewport.width()), min(height, viewport.height()))
        self.layout().activate()

    def focus_color(self) -> None:
        self._open_color_picker("color", True)

    def place_color_picker(self) -> None:
        self._picker.reposition()

    def close_color_picker(self) -> None:
        self._picker.hide()

    def finish_color_sampling(self, color: QColor | None) -> None:
        role, self._sample_role = self._sample_role, None
        if role in self._roles and color is not None and color.isValid():
            self._controls[role].set_qcolor(color)

    def hideEvent(self, event: QHideEvent) -> None:
        self.close_color_picker()
        super().hideEvent(event)

    def _open_color_picker(self, role: str, sticky: bool) -> None:
        if role not in self._roles or not self.isVisible() or not self.isEnabled():
            return
        if self._picker_role != role:
            self.close_color_picker()
        field = self._controls[role]
        if field.isVisible():
            self._picker_role = role
            self._picker.open_at(field.custom_button, self, field.color, sticky=sticky)

    def _commit_color(self, color: QColor) -> None:
        role = self._picker_role
        if role is not None:
            self._controls[role].set_qcolor(color)
            self.color_preview_changed.emit(None)

    def _preview_color(self, color: QColor) -> None:
        role = self._picker_role
        value = self._value
        if role in self._roles and value is not None:
            setting = color_name(color)
            self._controls[role].preview_color(setting)
            self.color_preview_changed.emit(self._with_setting(value, role, setting))

    def _clear_color_preview(self) -> None:
        role, self._picker_role = self._picker_role, None
        if role is not None:
            field = self._controls[role]
            field.preview_color(field.color)
            self.color_preview_changed.emit(None)

    def _start_color_sampling(self) -> None:
        self._sample_role = self._picker_role
        if self._sample_role is not None:
            self.close_color_picker()
            self.color_sampling_requested.emit()

    def step_size(self, increase: bool) -> None:
        for role in ("width_px", "brush_width", "font_size_px", "watermark_font_size",
                     "highlight_border"):
            if role in self._roles:
                self._controls[role].step(increase)
                return

    def update_element(self, element: Element) -> Element:
        value = self._value
        if isinstance(element, Stroke) and isinstance(value, Stroke):
            return replace(element, color=value.color, width_px=value.width_px, style=value.style,
                           is_filled=value.is_filled, opacity=value.opacity)
        if isinstance(element, Text) and isinstance(value, Text):
            return replace(element, color=value.color, font_size_px=value.font_size_px,
                           style=value.style, watermark=value.watermark, opacity=value.opacity)
        return element

    def _create_controls(self) -> None:
        for role, label in _COLORS.items():
            field = ColorControl(label, self._content, optional=role != "color")
            field.color_changed.connect(lambda value, role=role: self._set(role, value))
            field.custom_requested.connect(
                lambda sticky, role=role: self._open_color_picker(role, sticky)
            )
            self._add_section(role, label, field)
        for role, (label, *arguments) in _NUMBERS.items():
            field = SizeControl(label, *arguments, self._content)
            field.valueChanged.connect(lambda value, role=role: self._set(role, value))
            self._add_section(role, label, field)
        for role, (label, *arguments) in _PRESETS.items():
            field = NumericPresets(label, *arguments, self._content)
            field.value_changed.connect(lambda value, role=role: self._set(role, value))
            self._add_section(role, label, field)
        for role, (label, options) in _MODES.items():
            field = ModeControl(label, options, self._content)
            field.value_changed.connect(lambda value: self.variant_changed.emit(Tool(value)))
            self._add_section(role, label, field)
        for role, (label, options) in _SEGMENTS.items():
            field = ModeControl(label, options, self._content)
            field.value_changed.connect(lambda value, role=role: self._set(role, value))
            self._add_section(role, label, field)
        for role in ("opacity", "watermark_opacity"):
            slider = OpacityControl(self._content)
            slider.sliderMoved.connect(lambda value, role=role: self._preview_opacity(role, value))
            if role == "watermark_opacity":
                slider.sliderReleased.connect(lambda: self.watermark_preview_changed.emit(None))
            else:
                slider.sliderReleased.connect(lambda: self.opacity_preview_changed.emit(None))
            slider.valueChanged.connect(lambda value, role=role: self._set(role, value))
            self._add_section(role, "透明度", slider, expand=True)

        for role, label in (("start_head", "起点箭头"), ("end_head", "终点箭头")):
            button = self._button(label, "arrow")
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(button)
            for option, name in _HEADS.items():
                action = menu.addAction(toolbar_icon(f"head_{option}"), name)
                action.triggered.connect(lambda _checked=False, option=option, role=role: self._set(role, option))
                action.setData(option)
                action.setCheckable(True)
            button.setMenu(menu)
            self._add_section(role, label, button)
        emphasis = ModeControl("文字样式", _EMPHASIS, self._content, exclusive=False)
        emphasis.value_changed.connect(lambda role: self._set(role, not self._read(role)))
        self._add_section("emphasis", "文字样式", emphasis)

        family = self._button("字体", "font_size")
        family.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        family.setMinimumWidth(116)
        family.clicked.connect(self._choose_font)
        self._add_section("family", "字体", family)
        text = LineEdit(self._content)
        text.setAccessibleName("水印内容")
        text.setPlaceholderText("输入水印内容")
        text.setFixedHeight(34)
        text.setMaxLength(512)
        text.installEventFilter(self)
        text.textEdited.connect(self._preview_watermark_text)
        text.editingFinished.connect(lambda: self._set("watermark_text", text.text().strip()))
        self._add_section("watermark_text", "水印内容", text, expand=True)

        templates = self._button("水印模板", "watermark")
        templates.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        templates.setMenu(QMenu(templates))
        templates.menu().aboutToShow.connect(self._load_templates)
        self._add_section("templates", "水印模板", templates)
        self._add_actions("layers", "图层", _LAYER_ACTIONS, self.layer_requested)
        self._add_actions("horizontal", "水平对齐", {
            "left": ("左对齐", "objects_left"), "center_x": ("水平居中", "objects_center_x"),
            "right": ("右对齐", "objects_right"), "distribute_x": ("水平分布", "objects_distribute_x"),
        }, self.alignment_requested)
        self._add_actions("vertical", "垂直对齐", {
            "top": ("顶部对齐", "objects_top"), "center_y": ("垂直居中", "objects_center_y"),
            "bottom": ("底部对齐", "objects_bottom"), "distribute_y": ("垂直分布", "objects_distribute_y"),
        }, self.alignment_requested)
        self._add_actions("selection_actions", "所选元素", {
            "duplicate": ("复制所选元素", "copy"),
            "delete": ("删除所选元素（Delete）", "delete"),
        }, self.selection_requested)

    def _add_actions(
        self, role: str, label: str, actions: dict[str, tuple[str, str]], signal
    ) -> None:
        group = QFrame(self._content)
        row = QHBoxLayout(group)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(11)
        for action, (description, icon) in actions.items():
            button = self._button(description, icon)
            if action.startswith("distribute"):
                button.setObjectName("distribute")
            button.clicked.connect(lambda _checked=False, action=action: signal.emit(action))
            row.addWidget(button)
        self._add_section(role, label, group)

    def _add_section(self, role: str, label: str, control: QWidget, *, expand: bool = False) -> None:
        section = QWidget(self._content)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        title = QLabel(label, section)
        title.setObjectName("styleLabel")
        layout.addWidget(title)
        layout.addWidget(control, alignment=Qt.AlignmentFlag(0) if expand else Qt.AlignmentFlag.AlignLeft)
        control.setProperty("styleRole", role)
        section.hide()
        self._controls[role] = control
        self._sections[role] = section

    def _layout_sections(self) -> None:
        self.close_color_picker()
        while self._sections_layout.count():
            self._sections_layout.takeAt(0).widget().hide()
        for role in self._roles:
            section = self._sections[role]
            self._sections_layout.addWidget(section)
            section.show()
        self._scroll.verticalScrollBar().setValue(0)

    def _button(self, label: str, icon: str) -> QToolButton:
        button = QToolButton(self._content)
        button.setProperty("optionButton", True)
        button.setIcon(toolbar_icon(icon))
        button.setIconSize(QSize(18, 18))
        button.setMinimumSize(38, 38)
        describe_control(button, label)
        return button

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            isinstance(watched, QLineEdit)
            and event.type() == QEvent.Type.ShortcutOverride
            and event.key() != Qt.Key.Key_Escape
        ):
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _load_values(self) -> None:
        value = self._value
        if value is None:
            return
        self._is_loading = True
        try:
            for role in self._roles:
                control = self._controls[role]
                if role in _MODES:
                    control.set_value(value.tool.value)
                elif role == "emphasis":
                    control.set_checked_values(key for key in _EMPHASIS if self._read(key))
                elif role == "family":
                    control.setText(value.style.family or QFont().family())
                elif role == "watermark_text":
                    if not control.hasFocus():
                        control.setText(value.watermark.value)
                elif role in _COLORS:
                    control.set_color(self._read(role))
                elif role in _NUMBERS or role in _PRESETS or role in _SEGMENTS or "opacity" in role:
                    control.set_value(self._read(role))
                elif role in ("start_head", "end_head"):
                    head = self._read(role)
                    control.setIcon(toolbar_icon(f"head_{head}"))
                    for action in control.menu().actions():
                        action.setChecked(action.data() == head)
        finally:
            self._is_loading = False

    def _read(self, role: str):
        value = self._value
        if value is None:
            return None
        field = _ALIASES.get(role, role)
        if role == "watermark_text":
            return value.watermark.value
        if role == "watermark_opacity":
            return value.watermark.opacity
        if hasattr(value, field):
            return getattr(value, field)
        if hasattr(value.style, field):
            return getattr(value.style, field)
        if isinstance(value, Text):
            return getattr(value.watermark, field, None)
        return None

    def _set(self, role: str, setting) -> None:
        if self._is_loading or (role not in self._roles and role not in _EMPHASIS):
            return
        value = self._value
        if value is None:
            if role == "opacity":
                self.selection_opacity_requested.emit(setting)
            return
        if setting != self._read(role):
            self._apply(self._with_setting(value, role, setting))

    @staticmethod
    def _with_setting(value: Element, role: str, setting) -> Element:
        field = _ALIASES.get(role, role)
        if hasattr(value, field):
            return replace(value, **{field: setting})
        if hasattr(value.style, field):
            return replace(value, style=replace(value.style, **{field: setting}))
        if isinstance(value, Text):
            field = {"watermark_text": "value", "watermark_opacity": "opacity"}.get(role, field)
            return replace(value, watermark=replace(value.watermark, **{field: setting}))
        return value

    def _apply(self, value: Element) -> None:
        self._value = value
        if not self._is_selection or value.tool is Tool.WATERMARK:
            self._model.set(value)
        self._load_values()
        self.style_changed.emit(value)

    def _preview_opacity(self, role: str, opacity: int) -> None:
        value = self._value
        if role == "watermark_opacity" and isinstance(value, Text):
            self.watermark_preview_changed.emit(
                replace(value, watermark=replace(value.watermark, opacity=opacity))
            )
        else:
            self.opacity_preview_changed.emit(opacity)

    def _preview_watermark_text(self, text: str) -> None:
        value = self._value
        if isinstance(value, Text) and value.tool is Tool.WATERMARK:
            draft = replace(value, watermark=replace(value.watermark, value=text.strip()))
            self.watermark_preview_changed.emit(draft)

    def _choose_font(self) -> None:
        value = self._value
        if not isinstance(value, Text):
            return
        initial = QFont(value.style.family)
        initial.setPointSize(max(1, round(value.font_size_px * .75)))
        accepted, font = QFontDialog.getFont(initial, self, "选择字体")
        if accepted:
            size = max(MIN_FONT_SIZE_PX, min(MAX_FONT_SIZE_PX, round(font.pointSizeF() / .75)))
            self._apply(replace(
                value, font_size_px=size, style=replace(value.style, family=font.family())
            ))

    def _load_templates(self) -> None:
        menu = self._controls["templates"].menu()
        menu.clear()
        templates = self._settings.value("watermarkTemplates", {})
        for name in sorted(templates):
            menu.addAction(name, lambda name=name: self._apply_template(templates[name]))
        if templates:
            menu.addSeparator()
        menu.addAction("保存当前模板…", self._save_template)
        if templates:
            remove = menu.addMenu("删除模板")
            for name in sorted(templates):
                remove.addAction(name, lambda name=name: self._remove_template(name))

    def _save_template(self) -> None:
        value = self._value
        if not isinstance(value, Text):
            return
        text = self._controls["watermark_text"].text()
        self._set("watermark_text", text)
        name, accepted = prompt_text(self, "保存水印模板", "模板名称")
        if not accepted or not name.strip():
            return
        templates = self._settings.value("watermarkTemplates", {})
        templates[name.strip()] = {
            "text": text, "angle": value.watermark.angle, "gap": value.watermark.gap_px,
            "opacity": value.watermark.opacity, "font_size": value.font_size_px,
            "family": value.style.family, "color": value.color,
        }
        self._settings.setValue("watermarkTemplates", templates)

    def _remove_template(self, name: str) -> None:
        templates = self._settings.value("watermarkTemplates", {})
        templates.pop(name, None)
        self._settings.setValue("watermarkTemplates", templates)

    def _apply_template(self, template: dict) -> None:
        value = self._value
        if isinstance(value, Text):
            self._apply(replace(
                value, color=template["color"], font_size_px=template["font_size"],
                style=replace(value.style, family=template["family"]),
                watermark=WatermarkStyle(
                    template["text"], template["angle"], template["gap"], template["opacity"]
                ),
            ))
