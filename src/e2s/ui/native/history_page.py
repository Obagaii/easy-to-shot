from datetime import datetime
import json
import subprocess
import sys

from PySide6.QtCore import QDate, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QDateEdit, QHBoxLayout, QLabel, QMenu, QMessageBox, QScrollArea,
    QVBoxLayout, QWidget,
)
from qfluentwidgets import CardWidget, CheckBox, ComboBox, PushButton

from e2s.storage.history import HistoryService, HistoryStatus


_SOURCE_LABELS = {"copy": "复制到剪贴板", "save": "保存为文件", "pin": "固定到屏幕"}
_PAGE_SIZE = 8


class HistoryPage(QWidget):
    edit_requested = Signal(object)

    def __init__(self, history: HistoryService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._history = history
        self._selected: set[str] = set()
        self._entries = ()
        self._page = 0
        self._cards = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        self._source = ComboBox()
        self._source.addItem("全部类型", userData="")
        for source, label in _SOURCE_LABELS.items():
            self._source.addItem(label, userData=source)
        self._source.currentIndexChanged.connect(self._filters_changed)
        filters.addWidget(self._source)
        filters.addStretch()
        refresh = PushButton("刷新")
        refresh.clicked.connect(self.refresh)
        filters.addWidget(refresh)
        clear = PushButton("清空历史")
        clear.clicked.connect(self._clear)
        filters.addWidget(clear)
        layout.addLayout(filters)

        dates = QHBoxLayout()
        self._date_filter = CheckBox("按时间筛选")
        self._date_filter.toggled.connect(self._filters_changed)
        dates.addWidget(self._date_filter)
        self._start = QDateEdit(QDate.currentDate().addDays(-30))
        self._end = QDateEdit(QDate.currentDate())
        for date in (self._start, self._end):
            date.setCalendarPopup(True)
            date.setDisplayFormat("yyyy-MM-dd")
            date.dateChanged.connect(self._filters_changed)
            dates.addWidget(date)
        dates.addStretch()
        layout.addLayout(dates)

        selection = QHBoxLayout()
        select_all = PushButton("全选")
        select_all.clicked.connect(self._select_all)
        selection.addWidget(select_all)
        deselect = PushButton("取消选择")
        deselect.clicked.connect(self._deselect_all)
        selection.addWidget(deselect)
        remove = PushButton("删除选中")
        remove.clicked.connect(self._delete_selected)
        selection.addWidget(remove)
        self._count = QLabel()
        selection.addWidget(self._count)
        selection.addStretch()
        layout.addLayout(selection)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._content = QWidget()
        self._content.setStyleSheet("QWidget#historyContent { background: transparent; }")
        self._content.setObjectName("historyContent")
        self._rows = QVBoxLayout(self._content)
        self._rows.setContentsMargins(0, 0, 4, 0)
        self._rows.setSpacing(10)
        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll, 1)
        pagination = QHBoxLayout()
        self._previous = PushButton("上一页")
        self._previous.clicked.connect(lambda: self._move_page(-1))
        self._next = PushButton("下一页")
        self._next.clicked.connect(lambda: self._move_page(1))
        self._page_label = QLabel()
        pagination.addStretch()
        pagination.addWidget(self._previous)
        pagination.addWidget(self._page_label)
        pagination.addWidget(self._next)
        layout.addLayout(pagination)
        self.refresh()

    def _filters_changed(self, *_args) -> None:
        self._page = 0
        self.refresh()

    def refresh(self) -> None:
        entries = self._history.store.list_recent(limit=1_000_000)
        source = self._source.currentData()
        filtered = []
        for entry in entries:
            if source and entry.source != source:
                continue
            if self._date_filter.isChecked():
                try:
                    date = datetime.fromisoformat(entry.created_at_utc).astimezone().date()
                except ValueError:
                    continue
                if not (self._start.date().toPython() <= date <= self._end.date().toPython()):
                    continue
            filtered.append(entry)
        self._entries = tuple(filtered)
        existing = {entry.history_item_id for entry in entries}
        self._selected.intersection_update(existing)
        self._render()

    def _render(self) -> None:
        while self._rows.count():
            child = self._rows.takeAt(0)
            if child.widget():
                child.widget().hide()
                child.widget().deleteLater()
        self._cards = {}
        pages = max(1, (len(self._entries) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self._page = max(0, min(self._page, pages - 1))
        for entry in self._entries[self._page * _PAGE_SIZE:(self._page + 1) * _PAGE_SIZE]:
            self._add_card(entry)
        if not self._entries:
            self._rows.addWidget(QLabel("没有符合条件的截图历史", alignment=Qt.AlignmentFlag.AlignCenter))
        self._rows.addStretch()
        self._count.setText(f"共 {len(self._entries)} 条 · 已选择 {len(self._selected)} 条")
        self._page_label.setText(f"第 {self._page + 1} / {pages} 页")
        self._previous.setEnabled(self._page > 0)
        self._next.setEnabled(self._page + 1 < pages)

    def _add_card(self, entry) -> None:
        card = CardWidget()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 14, 16, 14)
        preview = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        preview.setFixedSize(160, 100)
        image = QPixmap(str(self._history.store.image_path(entry)))
        if image.isNull():
            preview.setText("图片不可用")
        else:
            preview.setPixmap(image.scaled(QSize(160, 100), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        row.addWidget(preview)
        details = QVBoxLayout()
        try:
            stamp = datetime.fromisoformat(entry.created_at_utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            stamp = entry.created_at_utc
        checked = CheckBox(stamp)
        checked.setChecked(entry.history_item_id in self._selected)
        checked.toggled.connect(lambda value, key=entry.history_item_id: self._set_selected(key, value))
        details.addWidget(checked)
        details.addWidget(QLabel(_SOURCE_LABELS.get(entry.source, entry.source)))
        details.addWidget(QLabel(f"{entry.width_px} × {entry.height_px}  ·  {entry.byte_count / 1024:.1f} KB"))
        actions = QHBoxLayout()
        copy = PushButton("复制")
        copy.clicked.connect(lambda: self._copy(entry))
        actions.addWidget(copy)
        edit = PushButton("编辑")
        edit.setEnabled(self._history.store.session_path(entry).is_file())
        if not edit.isEnabled():
            edit.setToolTip("此记录没有原始屏幕和编辑数据")
        edit.clicked.connect(lambda: self._edit(entry))
        actions.addWidget(edit)
        more = PushButton("更多")
        menu = QMenu(more)
        menu.addAction("在资源管理器中打开", lambda: self._open_file(entry))
        menu.addAction("删除", lambda: self._delete_entries((entry.history_item_id,)))
        more.setMenu(menu)
        actions.addWidget(more)
        actions.addStretch()
        details.addLayout(actions)
        row.addLayout(details, 1)
        self._rows.addWidget(card)
        self._cards[entry.history_item_id] = checked

    def _set_selected(self, key: str, value: bool) -> None:
        if value:
            self._selected.add(key)
        else:
            self._selected.discard(key)
        self._count.setText(f"共 {len(self._entries)} 条 · 已选择 {len(self._selected)} 条")

    def _select_all(self) -> None:
        self._selected.update(entry.history_item_id for entry in self._entries)
        self._render()

    def _deselect_all(self) -> None:
        self._selected.clear()
        self._render()

    def _move_page(self, offset: int) -> None:
        self._page += offset
        self._render()
        self._scroll.verticalScrollBar().setValue(0)

    def _copy(self, entry) -> None:
        image = QPixmap(str(self._history.store.image_path(entry)))
        if image.isNull():
            QMessageBox.warning(self, "截图历史", "图片文件不可用。")
        else:
            QApplication.clipboard().setPixmap(image)

    def _edit(self, entry) -> None:
        try:
            payload = self._history.store.session_path(entry).read_bytes()
            screen_id = json.loads(payload)["screen_id"]
        except (OSError, ValueError, KeyError, TypeError):
            QMessageBox.warning(self, "截图历史", "无法读取这条截图的编辑数据。")
            return
        self.edit_requested.emit({"payload": payload, "screen_id": screen_id,
                                  "history_item_id": entry.history_item_id})

    def _open_file(self, entry) -> None:
        path = self._history.store.image_path(entry)
        if not path.is_file():
            QMessageBox.warning(self, "截图历史", "图片文件不可用。")
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])

    def _delete_selected(self) -> None:
        self._delete_entries(tuple(self._selected))

    def _delete_entries(self, keys: tuple[str, ...]) -> None:
        if not keys:
            return
        if QMessageBox.question(self, "删除截图历史", f"确定删除选中的 {len(keys)} 条记录吗？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        failed = False
        for key in keys:
            if self._history.delete(key) != HistoryStatus.DELETED:
                failed = True
            else:
                self._selected.discard(key)
        if failed:
            QMessageBox.warning(self, "截图历史", "部分记录删除失败，请重试。")
        self.refresh()

    def _clear(self) -> None:
        if QMessageBox.question(self, "清空截图历史", "确定删除所有截图历史吗？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        if self._history.clear() != HistoryStatus.DELETED:
            QMessageBox.warning(self, "截图历史", "清空失败，请重试。")
        else:
            self._selected.clear()
        self.refresh()
