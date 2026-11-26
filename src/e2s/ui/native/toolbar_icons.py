from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "select": "M7 3H4Q3 3 3 4v3m7-4h4m3 0h3q1 0 1 1v3M3 10v4m0 3v3q0 1 1 1h3"
              "m4-10 10 4-4 2 4 4m-4-4-2 4z",
    "move": "M12 3v18M3 12h18M9 6l3-3 3 3m-6 12 3 3 3-3M6 9l-3 3 3 3m12-6 3 3-3 3",
    "rectangle": "M2.5 4.5h19v15h-19z",
    "ellipse": "M2.5 12a9.5 8 0 1 0 19 0 9.5 8 0 1 0-19 0",
    "arrow": "M4 20 20 4m-8 0h8v8",
    "arrow_curve": "M3 20C5 9 12 5 21 5m-6-3 6 3-4 6",
    "arrow_elbow": "M3 20h9V7h9m-5-5 5 5-5 5",
    "pen": "M3 16 16 3a2 2 0 0 1 3 0l2 2a2 2 0 0 1 0 3L8 21l-5 1zM13 6l5 5M4 16l4 4",
    "brush_pressure": "M3 18Q10 2 19 9Q22 12 17 15Q13 9 3 18Z",
    "highlight": "m8 10 8-8 6 6-8 8zM9 12l-3 3 4 4 3-3m-6 0-4 4h5l2-2M2 22h20",
    "rect_highlight": "M3 4h18v14H3zM3 21h18M6 14l6-7m0 8 6-7",
    "text": "M5 7H2v10h3m14-10h3v10h-3M8 4h8m-4 0v16m-4 0h8",
    "eraser": "m3 13 10-10 8 8-9 9H9zM8 8l8 8m-4 4h9",
    "brush_eraser": "M3 20h18M6 16l-1-4 9-9 5 5-8 8zM10 7l5 5",
    "rect_eraser": "M3 4h18v16H3zM9 12l4-4 4 4-4 4h-2z",
    "watermark": "M3 4h18v16H3zM6 8l2 8 4-6 4 6 2-8",
    "undo": "M7 19a9 9 0 1 1 11 0m-11-4v5H2",
    "redo": "M17 19a9 9 0 1 0-11 0m11-4v5h5",
    "delete": "M3 6h18M8 6V3h8v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
    "copy": "M8 8h12v13H8zM16 4H4v13",
    "save": "M3 3h15l3 3v15H3zM7 3v6h10V3M7 21v-7h10v7",
    "pin": "m15 3 6 6-4 4q1 4-2 7L4 9q3-3 7-2zm-5 12-7 7",
    "accept": "m4 12 5 5L20 6",
    "cancel": "M5 5l14 14M19 5 5 19",
    "barcode_marker": "M3 8V3h5m8 0h5v5m0 8v5h-5m-8 0H3v-5m4-9h3v3H7zm7 0h3v3h-3zm-7 7h3v3H7zm7 0h3v3h-3z",
    "barcode": "M3 8V3h5m8 0h5v5m0 8v5h-5m-8 0H3v-5m4-9h3v3H7zm7 0h3v3h-3z"
               "m-7 7h3v3H7zm7 0h2v2h-2zm4 2v2m-4 0h2",
    "record": "M3 5h12v14H3zM15 9l6-4v14l-6-4",
    "record_start": "M12 3a9 9 0 1 0 0 18 9 9 0 1 0 0-18m-2 5 6 4-6 4z",
    "record_stop": "M12 3a9 9 0 1 0 0 18 9 9 0 1 0 0-18m-3 6h6v6H9z",
    "record_pause": "M9 5H6v14h3zM18 5h-3v14h3z",
    "record_folder": "M3 6h7l2 3h9v10H3z",
    "speaker": "M3 9h4l5-4v14l-5-4H3zM15 9a4 4 0 0 1 0 6m2-8a7 7 0 0 1 0 10",
    "microphone": "M12 3a3 3 0 0 0-3 3v5a3 3 0 1 0 6 0V6a3 3 0 0 0-3-3"
                  "M6 11a6 6 0 1 0 12 0M12 17v4m-3 0h6M3 3l18 18",
    "microphone_on": "M12 3a3 3 0 0 0-3 3v5a3 3 0 1 0 6 0V6a3 3 0 0 0-3-3"
                     "M6 11a6 6 0 1 0 12 0M12 17v4m-3 0h6",
    "scroll": "M9 2h13v14l-6 6H9zM16 22v-6h6M12 7h7m-7 4h5M4 3v7m-2-5 2-2 2 2m-2 9v7m-2-2 2 2 2-2",
    "fill": "m4 12 7-7 7 7-7 7zM4 12h14m3 3c-3 3-2 6 0 6s3-3 0-6z",
    "stroke_width": "M3 5h18M3 11h18M3 18h18",
    "font_size": "m2 19 6-14 6 14m-10-4h8m2 4 3-8 4 8m-6-2h5",
    "eyedropper": "m13 7 4-4a2.7 2.7 0 0 1 4 4l-4 4m-6-6 8 8m-6-4-8 8-1 4 4-1 8-8",
    "eyedropper_light": "m13 7 4-4a2.7 2.7 0 0 1 4 4l-4 4m-6-6 8 8m-6-4-8 8-1 4 4-1 8-8",
    "opacity": "M12 2c5 7 8 11 8 15a8 8 0 0 1-16 0c0-4 3-8 8-15zM6 16h12m-10 3h8",
    "arrow_tapered": "m3 20 11-12-2-2 9-3-3 9-2-2z",
    "head_none": "M3 12h18",
    "head_open": "M3 12h18m-6-5 6 5-6 5",
    "head_bar": "M3 12h17m0-5v10",
    "head_dot": "M3 12h14m1.5-1.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 1 0 0-3z",
    "head_circle": "M3 12h10m0 0a4 4 0 1 0 8 0 4 4 0 1 0-8 0m2 0h4",
    "head_circle_outline": "M3 12h10m0 0a4 4 0 1 0 8 0 4 4 0 1 0-8 0",
    "head_indented_triangle": "M3 12h12m-2-5 8 5-8 5 2-5z",
    "head_triangle": "M3 12h11m0-5 7 5-7 5zM15 12h3",
    "head_triangle_outline": "M3 12h11m0-5 7 5-7 5z",
    "head_diamond": "M3 12h8m0 0 5-5 5 5-5 5zM14 12h4",
    "head_diamond_outline": "M3 12h8m0 0 5-5 5 5-5 5z",
    "head_crowfoot_one": "M3 12h16m0-5v10",
    "head_crowfoot_many": "M3 12h18m-8 0 8-5m-8 5 8 5",
    "head_crowfoot_one_or_many": "M3 12h18m-8 0 8-5m-8 5 8 5M10 7v10",
    "objects_left": "M4 3v18m3-15h13v4H7zm0 8h8v4H7z",
    "objects_center_x": "M12 3v3m0 4v4m0 4v3M4 6h16v4H4zm4 8h8v4H8z",
    "objects_right": "M20 3v18m-16-15h13v4H4zm5 8h8v4H9z",
    "objects_distribute_x": "M3 3v18M21 3v18M9 5h6v14H9z",
    "objects_top": "M3 4h18M6 7v13h4V7zm8 0v8h4V7z",
    "objects_center_y": "M3 12h3m4 0h4m4 0h3M6 4v16h4V4zm8 4v8h4V8z",
    "objects_bottom": "M3 20h18M6 4v13h4V4zm8 5v8h4V9z",
    "objects_distribute_y": "M3 3h18M3 21h18M5 9h14v6H5z",
    "size_s": "M16 6H9a3 3 0 0 0 0 6h4a3 3 0 0 1 0 6H6",
    "size_m": "M5 18V6l7 8 7-8v12",
    "size_l": "M7 6v12h11",
    "size_xl": "m3 7 7 10m0-10-7 10m11-10v10h7",
    "bold": "M7 4h6a4 4 0 0 1 0 8H7h7a4 4 0 0 1 0 8H7z",
    "italic": "M11 4h8m-7 16H4m10-16-5 16",
    "underline": "M6 4v8a6 6 0 0 0 12 0V4M5 21h14",
    "strikethrough": "M17 6a7 7 0 0 0-9-1c-4 3 1 5 4 6 3 1 8 3 4 7a7 7 0 0 1-10-1M3 12h18",
    "scroll_vertical": "M5 3h14v18H5zM12 6v12m-3-9 3-3 3 3m-6 6 3 3 3-3",
    "scroll_horizontal": "M3 5h18v14H3zM6 12h12m-9-3-3 3 3 3m6-6 3 3-3 3",
    "move_horizontal": "M2 7h20v10H2zM5 12h14m-11-3-3 3 3 3m8-6 3 3-3 3",
    "move_vertical": "M7 2h10v20H7zM12 5v14m-3-11 3-3 3 3m-6 8 3 3 3-3",
    "auto_scroll": "M12 3a9 9 0 1 0 9 9M12 2v4m0 6 5-4M18 3v5h5",
    "interval": "M12 5a8 8 0 1 0 8 8m-8-4v5h4m-7-12h6m4 3 2 2",
    "drag_handle": "M9 5h.1m5.9 0h.1M9 12h.1m5.9 0h.1M9 19h.1m5.9 0h.1",
    "drag_sidebar": "M3 5h.1m3.9 0h.1m3.9 0h.1m3.9 0h.1m3.9 0h.1m3.9 0h.1"
                    "M3 10h.1m3.9 0h.1m3.9 0h.1m3.9 0h.1m3.9 0h.1m3.9 0h.1",
    "width_thin": "M6 12h12",
    "width_medium": "M6 11.6h12m0 .8H6",
    "width_thick": "M6 11h12m0 1H6m0 1h12",
    "line_solid": "M5 12h14",
    "line_dash": "M5 12h2m3 0h3m3 0h3",
    "line_dot": "M4 12h.1m3.9 0h.1m3.9 0h.1m3.9 0h.1m3.9 0h.1",
    "line_precise": "M4 15l8-5v4l8-4",
    "line_architect": "M4 15l8-5q2 0 1 3t7-2",
    "line_artist": "M4 15q6-6 9-5l-1 4 8-4m-15 7q4-5 9-5l-1 4 7-4",
    "corner_square": "M5 11V5h7m3 0h.1m3 0h.1m0 4h.1m0 4h.1m0 5h.1m-4 0h.1m-4 0h.1m-5 0h.1m0-4h.1",
    "corner_round": "M5 11V9q0-4 4-4h3m3 0h.1m3 0h.1m0 4h.1m0 4h.1m0 5h.1m-4 0h.1m-4 0h.1m-5 0h.1m0-4h.1",
    "align_left": "M4 5h16M4 10h10M4 15h16M4 20h10",
    "align_center": "M4 5h16M7 10h10M4 15h16M7 20h10",
    "align_right": "M4 5h16M10 10h10M4 15h16M10 20h10",
    "layer_bottom": "M5 20h14m-7-3V5m-4 8 4 4 4-4",
    "layer_lower": "M12 19V5m-4 10 4 4 4-4",
    "layer_raise": "M12 5v14m-4-10 4-4 4 4",
    "layer_top": "M5 4h14m-7 3v12m-4-8 4-4 4 4",
}



@lru_cache
def toolbar_icon(name: str, *, primary: bool = False) -> QIcon:
    foreground = {
        "copy": "#1677ff", "cancel": "#ff4d4f", "drag_handle": "#bfbfbf",
        "drag_sidebar": "#bfbfbf", "barcode_marker": "#ffffff", "eyedropper_light": "#ffffff",
    }.get(name, "#262626")
    icon = QIcon()
    for mode, state, color in (
        (QIcon.Mode.Normal, QIcon.State.Off, foreground),
        (QIcon.Mode.Normal, QIcon.State.On, "#ffffff" if primary else "#1677ff"),
        (QIcon.Mode.Disabled, QIcon.State.Off, "#bfbfbf"),
    ):
        paint = (
            f'fill="none" stroke="{color}" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"'
        )
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            f'<path d="{_PATHS[name]}" {paint}/></svg>'
        )
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        for scale in (1, 2, 3):
            pixmap = QPixmap(24 * scale, 24 * scale)
            pixmap.fill(Qt.GlobalColor.transparent)
            with QPainter(pixmap) as painter:
                renderer.render(painter, QRectF(pixmap.rect()))
            pixmap.setDevicePixelRatio(scale)
            icon.addPixmap(pixmap, mode, state)
    return icon
