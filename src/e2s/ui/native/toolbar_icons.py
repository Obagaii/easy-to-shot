from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Material icons: https://github.com/google/material-design-icons (Apache-2.0).
_PATHS = {
    "select": "M5,19v2q-0.83,0-1.41-0.59T3,19H5ZM3,17V15H5v2H3Zm0-4V11H5v2H3ZM3,9V7H5V9"
        "H3ZM5,5H3Q3,4.17 3.59,3.59T5,3V5ZM7,21V19H9v2H7ZM7,5V3H9V5H7Zm4,16V19h2v"
        "2H11ZM11,5V3h2V5H11Zm4,16V19h2v2H15ZM15,5V3h2V5H15Zm4,14h2q0,0.82-0.59,1"
        ".41T19,21V19Zm0-2V15h2v2H19Zm0-4V11h2v2H19Zm0-4V7h2V9H19Zm0-4V3q0.83,0 1"
        ".41,0.59T21,5H19Z",
    "move": "M10 9h4V6h3l-5-5-5 5h3v3zm-1 1H6V7l-5 5 5 5v-3h3v-4zm14 2l-5-5v3h-3v4h3v"
        "3l5-5zm-9 3h-4v3H7l5 5 5-5h-3v-3z",
    "rectangle": "M18 4H6c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V6c0-1.1-.9-2-"
        "2-2zm0 14H6V6h12v12z",
    "ellipse": "M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2zm0 18c"
        "-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z",
    "arrow": "M9,5v2h6.59L4,18.59L5.41,20L17,8.41V15h2V5H9z",
    "arrow_curve": "M3 20C5 9 12 5 21 5m-6-3 6 3-4 6",
    "arrow_elbow": "M3 20h9V7h9m-5-5 5 5-5 5",
    "pen": "M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM5.92 19H5v-.92l9.06-9.06"
        ".92.92L5.92 19zM20.71 5.63l-2.34-2.34c-.2-.2-.45-.29-.71-.29s-.51.1-.7.2"
        "9l-1.83 1.83 3.75 3.75 1.83-1.83c.39-.39.39-1.02 0-1.41z",
    "brush_pressure": "M3 18Q10 2 19 9Q22 12 17 15Q13 9 3 18Z",
    "highlight": "M5.65,8L3.5,5.9L4.9,4.45L7.05,6.6L5.65,8ZM11,5V2h2V5H11Zm7.4,3L16.95,6.6"
        "L19.1,4.5l1.4,1.4L18.4,8ZM9,22V17L6,14V9H18v5l-3,3v5H9Zm2-2h2V16.18l3-3V"
        "11H8v2.17l3,3V20Zm1-4.5Z",
    "rect_highlight": "M5.65,8L3.5,5.9L4.9,4.45L7.05,6.6L5.65,8ZM11,5V2h2V5H11Zm7.4,3L16.95,6.6"
        "L19.1,4.5l1.4,1.4L18.4,8ZM9,22V17L6,14V9H18v5l-3,3v5H9Zm2-2h2V16.18l3-3V"
        "11H8v2.17l3,3V20Zm1-4.5Z",
    "text": "M2.5 4v3h5v12h3V7h5V4h-13zm19 5h-9v3h3v7h3v-7h3V9z",
    "eraser": "M17.25,18H22v2H15.25l2-2ZM4.75,20L2.63,17.88Q2.05,17.3 2.04,16.45T2.6,15"
        "l11-11.4Q14.18,3 15.01,3t1.41,0.57L21.4,8.55q0.57,0.58 0.57,1.43T21.4,11"
        ".4L13,20H4.75Zm7.4-2L20,9.95L15.05,5L4,16.4L5.6,18h6.55ZM12,12Z",
    "brush_eraser": "M3 20h18M6 16l-1-4 9-9 5 5-8 8zM10 7l5 5",
    "rect_eraser": "M3 4h18v16H3zM9 12l4-4 4 4-4 4h-2z",
    "watermark": "M21 3H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-"
        "2-2zm0 16H3V5h18v14zm-10-7h9v6h-9z",
    "undo": "M12.5 8c-2.65 0-5.05.99-6.9 2.6L2 7v9h9l-3.62-3.62c1.39-1.16 3.16-1.88 5"
        ".12-1.88 3.54 0 6.55 2.31 7.6 5.5l2.37-.78C21.08 11.03 17.15 8 12.5 8z",
    "redo": "M18.4 10.6C16.55 8.99 14.15 8 11.5 8c-4.65 0-8.58 3.03-9.96 7.22L3.9 16c"
        "1.05-3.19 4.05-5.5 7.6-5.5 1.95 0 3.73.72 5.12 1.88L13 16h9V7l-3.6 3.6z",
    "delete": "M3 6h18M8 6V3h8v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
    "copy": "M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 "
        "2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z",
    "save": "M17 3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V7l-4-4zm2 1"
        "6H5V5h11.17L19 7.83V19zm-7-7c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1."
        "34-3-3-3zM6 6h9v4H6z",
    "pin": "M14,4v5c0,1.12,0.37,2.16,1,3H9c0.65-0.86,1-1.9,1-3V4H14 M17,2H7C6.45,2,6"
        ",2.45,6,3c0,0.55,0.45,1,1,1c0,0,0,0,0,0l1,0v5 c0,1.66-1.34,3-3,3v2h5.97v"
        "7l1,1l1-1v-7H19v-2c0,0,0,0,0,0c-1.66,0-3-1.34-3-3V4l1,0c0,0,0,0,0,0c0.55"
        ",0,1-0.45,1-1 C18,2.45,17.55,2,17,2L17,2z",
    "accept": "m4 12 5 5L20 6",
    "cancel": "M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.4"
        "1 17.59 19 19 17.59 13.41 12 19 6.41z",
    "ocr": "M3 3h6v2H5v4H3V3zm12 0h6v6h-2V5h-4V3zM3 15h2v4h4v2H3v-6zm16 0h2v6h-6v-2h"
        "4v-4zM7 7h10v2H7V7zm0 4h10v2H7v-2zm0 4h7v2H7v-2z",
    "barcode_marker": "M3 8V3h5m8 0h5v5m0 8v5h-5m-8 0H3v-5m4-9h3v3H7zm7 0h3v3h-3zm-7 7h3v3H7zm7 0h3v3h-3z",
    "barcode": "M2,7V2H7V4H4V7H2ZM2,22V17H4v3H7v2H2Zm15,0V20h3V17h2v5H17ZM20,7V4H17V2h5V"
        "7H20ZM17.5,17.5H19V19H17.5V17.5Zm0-3H19V16H17.5V14.5ZM16,16h1.5v1.5H16V1"
        "6Zm-1.5,1.5H16V19H14.5V17.5ZM13,16h1.5v1.5H13V16Zm3-3h1.5v1.5H16V13Zm-1."
        "5,1.5H16V16H14.5V14.5ZM13,13h1.5v1.5H13V13Zm6-8v6H13V5h6Zm-8,8v6H5V13h6Z"
        "m0-8v6H5V5h6ZM9.5,17.5v-3h-3v3h3Zm0-8v-3h-3v3h3Zm8,0v-3h-3v3h3Z",
    "record": "M15 8v8H5V8h10m1-2H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1"
        "-1v-3.5l4 4v-11l-4 4V7c0-.55-.45-1-1-1z",
    "record_start": "M10 16.5l6-4.5-6-4.5zM12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-1"
        "0S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8"
        "z",
    "record_stop": "M12,2C6.48,2,2,6.48,2,12c0,5.52,4.48,10,10,10s10-4.48,10-10C22,6.48,17.5"
        "2,2,12,2z M12,20c-4.42,0-8-3.58-8-8s3.58-8,8-8 s8,3.58,8,8S16.42,20,12,2"
        "0z M16,16H8V8h8V16z",
    "record_pause": "M9 16h2V8H9v8zm3-14C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52"
        " 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm1-4h2"
        "V8h-2v8z",
    "record_folder": "M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-"
        "2V8c0-1.1-.9-2-2-2zm0 12H4V8h16v10z",
    "speaker": "M3 9v6h4l5 5V4L7 9H3zm7-.17v6.34L7.83 13H5v-2h2.83L10 8.83zM16.5 12c0-1."
        "77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89"
        ".86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77 0-4.28-2"
        ".99-7.86-7-8.77z",
    "microphone": "M10.8 4.9c0-.66.54-1.2 1.2-1.2s1.2.54 1.2 1.2l-.01 3.91L15 10.6V5c0-1.66"
        "-1.34-3-3-3-1.54 0-2.79 1.16-2.96 2.65l1.76 1.76V4.9zM19 11h-1.7c0 .58-."
        "1 1.13-.27 1.64l1.27 1.27c.44-.88.7-1.87.7-2.91zM4.41 2.86L3 4.27l6 6V11"
        "c0 1.66 1.34 3 3 3 .23 0 .44-.03.65-.08l1.66 1.66c-.71.33-1.5.52-2.31.52"
        "-2.76 0-5.3-2.1-5.3-5.1H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c.91-.13 1.7"
        "7-.45 2.55-.9l4.2 4.2 1.41-1.41L4.41 2.86z",
    "microphone_on": "M12,14c1.66,0,3-1.34,3-3V5c0-1.66-1.34-3-3-3S9,3.34,9,5v6C9,12.66,10.34,"
        "14,12,14z M17,11c0,2.76-2.24,5-5,5s-5-2.24-5-5H5c0,3.53,2.61,6.43,6,6.92"
        "V21h2v-3.08c3.39-0.49,6-3.39,6-6.92H17z",
    "scroll": "M8 2h11a2 2 0 0 1 2 2v12l-6 6H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm0 2v16h6v"
        "-5h5V4H8zm2 3h7v2h-7V7zm0 4h7v2h-7v-2zM3 6l2 2H4v8h1l-2 2-2-2h1V8H1l2-2z",
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



_FILLED_ICONS = {
    "arrow", "barcode", "cancel", "copy", "ellipse", "eraser", "highlight", "move", "ocr",
    "pen", "pin", "record", "rect_highlight", "rectangle", "redo", "save", "scroll", "select",
    "text", "undo", "watermark", "record_start", "record_stop", "record_pause",
    "record_folder", "speaker", "microphone", "microphone_on",
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
            f'fill="{color}"' if name in _FILLED_ICONS else
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
