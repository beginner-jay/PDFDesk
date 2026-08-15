from __future__ import annotations

import sys
from datetime import date
from functools import partial
from pathlib import Path
from threading import Event
from typing import Any

from PySide6.QtCore import QSize, QThread, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pdf_ops import (
    PdfCancelled,
    PdfError,
    get_pdf_info,
    merge_pdfs,
    missing_page_count,
    plan_fixed,
    split_fixed,
    split_ranges,
    validate_ranges,
)


class DragHandle(QLabel):
    def __init__(
        self,
        item: QListWidgetItem,
        file_list: QListWidget,
        move_item: Any,
    ) -> None:
        super().__init__("⠿")
        self.item = item
        self.file_list = file_list
        self.move_item = move_item
        self.dragging = False
        self.setObjectName("dragHandle")
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.grabMouse()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if self.dragging:
            position = self.file_list.viewport().mapFromGlobal(
                event.globalPosition().toPoint()
            )
            target = self.file_list.itemAt(position)
            target_row = (
                self.file_list.row(target)
                if target
                else self.file_list.count() - 1
            )
            self.dragging = False
            self.releaseMouse()
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            if target_row >= 0:
                self.move_item(self.item, target_row)
        super().mouseReleaseEvent(event)


class ModeCard(QFrame):
    def __init__(self, radio: QRadioButton) -> None:
        super().__init__()
        self.radio = radio
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.radio.setChecked(True)
        super().mousePressEvent(event)


def local_drop_paths(event: Any) -> list[str]:
    return [
        url.toLocalFile()
        for url in event.mimeData().urls()
        if url.isLocalFile()
    ]


class PdfDropFrame(QFrame):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: Any) -> None:
        if local_drop_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: Any) -> None:
        if local_drop_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = local_drop_paths(event)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class DropListWidget(QListWidget):
    files_dropped = Signal(list)
    order_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, event: Any) -> None:
        if local_drop_paths(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: Any) -> None:
        if local_drop_paths(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = local_drop_paths(event)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
            QTimer.singleShot(0, self.order_changed.emit)


class PdfWorker(QThread):
    progressed = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, operation: Any) -> None:
        super().__init__()
        self.operation = operation
        self.stop_requested = Event()

    def cancel(self) -> None:
        self.stop_requested.set()

    def run(self) -> None:
        try:
            result = self.operation(
                progress=self.progressed.emit,
                cancelled=self.stop_requested.is_set,
            )
        except PdfCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDF 정리")
        self.setMinimumSize(900, 720)
        self.resize(1080, 900)

        self.worker: PdfWorker | None = None
        self.progress_dialog: QProgressDialog | None = None
        self.success_handler: Any = None
        self.split_source: Path | None = None
        self.split_total_pages = 0
        self.range_rows: list[dict[str, Any]] = []

        central = QWidget()
        central.setObjectName("root")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header_frame = QFrame()
        header_frame.setObjectName("headerBar")
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(28, 14, 28, 14)
        logo = QLabel("PDF")
        logo.setObjectName("logo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(42, 42)
        title = QLabel("PDF 정리")
        title.setObjectName("appTitle")
        help_button = QPushButton("사용 방법")
        help_button.clicked.connect(self.show_help)
        header.addWidget(logo)
        header.addSpacing(10)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(help_button)
        root.addWidget(header_frame)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._scroll_page(self._build_merge_page()), "PDF 합치기")
        self.tabs.addTab(self._scroll_page(self._build_split_page()), "PDF 나누기")
        root.addWidget(self.tabs)
        self.setCentralWidget(central)

    def _scroll_page(self, page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

    def _build_merge_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(16)

        heading = QLabel("PDF 합치기")
        heading.setObjectName("pageTitle")
        guide = QLabel("파일을 마우스로 끌거나 아래 버튼을 눌러 합칠 순서를 바꿀 수 있습니다.")
        guide.setObjectName("muted")
        layout.addWidget(heading)
        layout.addWidget(guide)

        self.merge_drop_zone, _ = self._build_drop_zone(
            "PDF 파일을 여기에 끌어 놓으세요",
            "여러 파일을 한 번에 선택할 수도 있습니다.",
            self.choose_merge_files,
            self.add_merge_paths,
        )
        layout.addWidget(self.merge_drop_zone)

        self.merge_list = DropListWidget()
        self.merge_list.setObjectName("mergeList")
        self.merge_list.setMinimumHeight(240)
        self.merge_list.files_dropped.connect(self.add_merge_paths)
        self.merge_list.order_changed.connect(self.update_merge_view)
        layout.addWidget(self.merge_list, 1)

        self.merge_summary = QLabel("총 0개 파일 · 0쪽")
        self.merge_summary.setObjectName("summary")
        layout.addWidget(self.merge_summary)

        save_group = QFrame()
        save_group.setObjectName("card")
        save_form = QFormLayout(save_group)
        save_form.setContentsMargins(24, 18, 24, 18)
        save_form.setHorizontalSpacing(18)
        save_form.setVerticalSpacing(12)
        folder_row = QHBoxLayout()
        self.merge_folder = QLineEdit()
        self.merge_folder.setReadOnly(True)
        merge_folder_button = QPushButton("변경")
        merge_folder_button.clicked.connect(self.choose_merge_folder)
        folder_row.addWidget(self.merge_folder, 1)
        folder_row.addWidget(merge_folder_button)
        self.merge_name = QLineEdit(f"합친파일_{date.today():%Y%m%d}.pdf")
        save_form.addRow("저장 위치", folder_row)
        save_form.addRow("파일 이름", self.merge_name)
        layout.addWidget(save_group)

        footer = QHBoxLayout()
        safety = QLabel(
            "원본 파일은 변경되지 않습니다.\n전자서명은 결과 파일에서 유효하지 않을 수 있습니다."
        )
        safety.setObjectName("muted")
        self.merge_run_button = QPushButton("PDF 합치기")
        self.merge_run_button.setObjectName("primary")
        self.merge_run_button.clicked.connect(self.run_merge)
        footer.addWidget(safety, 1)
        footer.addWidget(self.merge_run_button)
        layout.addLayout(footer)
        self.update_merge_view()
        return page

    def _build_split_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(16)

        heading = QLabel("PDF 나누기")
        heading.setObjectName("pageTitle")
        guide = QLabel("일정한 쪽 수 또는 직접 지정한 범위마다 새 PDF를 만듭니다.")
        guide.setObjectName("muted")
        layout.addWidget(heading)
        layout.addWidget(guide)

        self.split_drop_zone, self.split_source_button = self._build_drop_zone(
            "나눌 PDF 파일을 여기에 끌어 놓으세요",
            "한 개의 PDF 파일을 선택할 수 있습니다.",
            self.choose_split_source,
            self.drop_split_paths,
        )
        layout.addWidget(self.split_drop_zone)

        self.split_source_group = QFrame()
        self.split_source_group.setObjectName("card")
        source_row = QHBoxLayout(self.split_source_group)
        source_row.setContentsMargins(24, 18, 24, 18)
        self.split_source_label = QLabel("PDF를 선택해 주세요.")
        self.split_source_label.setObjectName("sourceLabel")
        self.split_source_label.setWordWrap(True)
        split_remove_button = QPushButton("삭제")
        split_remove_button.setObjectName("rowButton")
        split_remove_button.clicked.connect(self.clear_split_source)
        source_row.addWidget(self.split_source_label, 1)
        source_row.addWidget(split_remove_button)
        self.split_source_group.hide()
        layout.addWidget(self.split_source_group)

        mode_row = QHBoxLayout()
        self.fixed_radio = QRadioButton("일정한 쪽 수로 나누기")
        self.range_radio = QRadioButton("범위를 직접 지정하기")
        modes = QButtonGroup(self)
        modes.addButton(self.fixed_radio, 0)
        modes.addButton(self.range_radio, 1)
        self.fixed_card = self._build_mode_card(
            self.fixed_radio, "예: 50쪽씩 여러 파일로 저장"
        )
        self.range_card = self._build_mode_card(
            self.range_radio, "예: 1~20쪽, 21~80쪽을 각각 저장"
        )
        self.fixed_radio.setChecked(True)
        self.fixed_radio.toggled.connect(self.update_split_mode)
        mode_row.addWidget(self.fixed_card, 1)
        mode_row.addWidget(self.range_card, 1)
        layout.addLayout(mode_row)

        middle = QHBoxLayout()
        self.split_settings = QStackedWidget()
        self.split_settings.addWidget(self._build_fixed_settings())
        self.split_settings.addWidget(self._build_range_settings())
        self.split_settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        middle.addWidget(self.split_settings, 3)

        preview_group = QGroupBox("예상 결과")
        preview_group.setObjectName("cardGroup")
        preview_layout = QVBoxLayout(preview_group)
        self.result_count = QLabel("PDF를 먼저 선택해 주세요.")
        self.result_count.setObjectName("resultCount")
        self.result_list = QListWidget()
        self.result_list.setMinimumWidth(280)
        self.result_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.range_warning = QLabel("")
        self.range_warning.setWordWrap(True)
        self.range_warning.setObjectName("warning")
        preview_layout.addWidget(self.result_count)
        preview_layout.addWidget(self.result_list, 1)
        preview_layout.addWidget(self.range_warning)
        middle.addWidget(preview_group, 2)
        layout.addLayout(middle, 1)

        split_folder_group = QFrame()
        split_folder_group.setObjectName("card")
        split_folder_row = QHBoxLayout(split_folder_group)
        split_folder_row.setContentsMargins(24, 18, 24, 18)
        split_folder_row.addWidget(QLabel("저장 위치"))
        self.split_folder = QLineEdit()
        self.split_folder.setReadOnly(True)
        split_folder_button = QPushButton("변경")
        split_folder_button.clicked.connect(self.choose_split_folder)
        split_folder_row.addWidget(self.split_folder, 1)
        split_folder_row.addWidget(split_folder_button)
        layout.addWidget(split_folder_group)

        footer = QHBoxLayout()
        safety = QLabel(
            "원본 파일은 변경되지 않습니다.\n범위에서 빠진 페이지는 결과에 포함되지 않습니다."
        )
        safety.setObjectName("muted")
        self.split_run_button = QPushButton("PDF 나누기")
        self.split_run_button.setObjectName("primary")
        self.split_run_button.clicked.connect(self.run_split)
        footer.addWidget(safety, 1)
        footer.addWidget(self.split_run_button)
        layout.addLayout(footer)
        self.update_split_mode()
        return page

    def _build_drop_zone(
        self,
        title: str,
        detail: str,
        choose_action: Any,
        drop_action: Any,
    ) -> tuple[PdfDropFrame, QPushButton]:
        frame = PdfDropFrame()
        frame.setObjectName("dropZone")
        row = QHBoxLayout(frame)
        row.setContentsMargins(24, 18, 24, 18)
        copy = QVBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("dropTitle")
        text = QLabel(detail)
        text.setObjectName("muted")
        copy.addWidget(heading)
        copy.addWidget(text)
        button = QPushButton("PDF 파일 선택")
        button.setObjectName("primary")
        button.clicked.connect(choose_action)
        frame.files_dropped.connect(drop_action)
        row.addLayout(copy, 1)
        row.addWidget(button)
        return frame, button

    def _build_fixed_settings(self) -> QWidget:
        group = QGroupBox("나누기 설정")
        group.setObjectName("cardGroup")
        group_layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self.pages_per_file = QSpinBox()
        self.pages_per_file.setRange(1, 1)
        self.pages_per_file.setValue(1)
        self.pages_per_file.setMinimumWidth(120)
        self.pages_per_file.valueChanged.connect(self.update_split_preview)
        row.addWidget(self.pages_per_file)
        row.addWidget(QLabel("쪽씩 나누기"))
        row.addStretch()
        group_layout.addLayout(row)
        group_layout.addStretch()
        return group

    def _build_range_settings(self) -> QWidget:
        group = QGroupBox("나누기 설정")
        group.setObjectName("cardGroup")
        group_layout = QVBoxLayout(group)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        self.ranges_layout = QVBoxLayout(container)
        self.ranges_layout.setContentsMargins(0, 0, 0, 0)
        self.ranges_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(container)
        add_button = QPushButton("범위 추가")
        add_button.clicked.connect(self.add_range_row)
        group_layout.addWidget(scroll, 1)
        group_layout.addWidget(add_button, 0, Qt.AlignmentFlag.AlignLeft)
        return group

    def _build_mode_card(self, radio: QRadioButton, description: str) -> QFrame:
        card = ModeCard(radio)
        card.setObjectName("modeCard")
        card.setProperty("active", False)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 16, 22, 16)
        layout.setSpacing(4)
        layout.addWidget(radio)
        detail = QLabel(description)
        detail.setObjectName("muted")
        layout.addWidget(detail)
        return card

    def choose_merge_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "합칠 PDF 선택", "", "PDF 파일 (*.pdf)")
        self.add_merge_paths(paths)

    def add_merge_paths(self, paths: list[str]) -> None:
        # ponytail: metadata scan is synchronous; move it to PdfWorker only if real large files stall the UI.
        existing = {self.merge_list.item(index).data(Qt.ItemDataRole.UserRole)[0] for index in range(self.merge_list.count())}
        errors: list[str] = []
        first_added: Path | None = None
        for value in paths:
            path = Path(value).expanduser().resolve()
            key = str(path)
            if key in existing:
                continue
            try:
                pages, size = get_pdf_info(path)
            except PdfError as exc:
                errors.append(str(exc))
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, (key, pages, size))
            item.setToolTip(key)
            self.merge_list.addItem(item)
            existing.add(key)
            first_added = first_added or path

        if first_added and not self.merge_folder.text():
            self.merge_folder.setText(str(first_added.parent))
        self.update_merge_view()
        if errors:
            QMessageBox.warning(self, "추가하지 못한 파일", "\n\n".join(errors))

    def update_merge_view(self) -> None:
        total_pages = 0
        count = self.merge_list.count()
        for index in range(self.merge_list.count()):
            item = self.merge_list.item(index)
            path, pages, _ = item.data(Qt.ItemDataRole.UserRole)
            old_widget = self.merge_list.itemWidget(item)
            if old_widget:
                old_widget.deleteLater()
            item.setText("")
            item.setSizeHint(QSize(0, 68))
            row = QWidget()
            row.setObjectName("mergeRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(14, 7, 12, 7)
            row_layout.setSpacing(10)
            drag_handle = DragHandle(item, self.merge_list, self.move_merge_item_to)
            order = QLabel(str(index + 1))
            order.setObjectName("orderBadge")
            order.setAlignment(Qt.AlignmentFlag.AlignCenter)
            order.setFixedSize(34, 34)
            name = QLabel(Path(path).name)
            name.setObjectName("fileName")
            name.setToolTip(path)
            page_count = QLabel(f"{pages}쪽")
            page_count.setObjectName("muted")
            up = QPushButton("위")
            down = QPushButton("아래")
            remove = QPushButton("삭제")
            for button in (up, down, remove):
                button.setObjectName("rowButton")
            up.setEnabled(index > 0)
            down.setEnabled(index < count - 1)
            up.clicked.connect(
                lambda checked=False, current=item: self.move_merge_list_item(current, -1)
            )
            down.clicked.connect(
                lambda checked=False, current=item: self.move_merge_list_item(current, 1)
            )
            remove.clicked.connect(
                lambda checked=False, current=item: self.remove_merge_list_item(current)
            )
            row_layout.addWidget(drag_handle)
            row_layout.addWidget(order)
            row_layout.addWidget(name, 1)
            row_layout.addWidget(page_count)
            row_layout.addWidget(up)
            row_layout.addWidget(down)
            row_layout.addWidget(remove)
            self.merge_list.setItemWidget(item, row)
            total_pages += pages
        self.merge_summary.setText(f"총 {count}개 파일 · {total_pages}쪽")
        self.merge_run_button.setText(f"{count}개 파일 합치기" if count else "PDF 합치기")
        self.merge_run_button.setEnabled(count >= 2 and not self.worker)

    def move_merge_list_item(self, item: QListWidgetItem, offset: int) -> None:
        row = self.merge_list.row(item)
        target = row + offset
        if row < 0 or not 0 <= target < self.merge_list.count():
            return
        self.merge_list.takeItem(row)
        self.merge_list.insertItem(target, item)
        self.merge_list.setCurrentRow(target)
        self.update_merge_view()

    def move_merge_item_to(self, item: QListWidgetItem, target: int) -> None:
        row = self.merge_list.row(item)
        if row < 0 or row == target or not 0 <= target < self.merge_list.count():
            return
        self.merge_list.takeItem(row)
        self.merge_list.insertItem(target, item)
        self.merge_list.setCurrentRow(target)
        self.update_merge_view()

    def remove_merge_list_item(self, item: QListWidgetItem) -> None:
        row = self.merge_list.row(item)
        if row >= 0:
            self.merge_list.takeItem(row)
            self.update_merge_view()

    def choose_merge_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "합친 PDF 저장 위치", self.merge_folder.text())
        if folder:
            self.merge_folder.setText(folder)

    def run_merge(self) -> None:
        if self.merge_list.count() < 2:
            return
        try:
            name = safe_pdf_name(self.merge_name.text())
            folder = required_folder(self.merge_folder.text())
        except PdfError as exc:
            QMessageBox.warning(self, "저장 설정 확인", str(exc))
            return
        paths = [self.merge_list.item(index).data(Qt.ItemDataRole.UserRole)[0] for index in range(self.merge_list.count())]
        operation = partial(merge_pdfs, paths, folder / name)
        self.start_task(operation, self.merge_completed, "PDF를 합치고 있습니다.")

    def choose_split_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "나눌 PDF 선택", "", "PDF 파일 (*.pdf)")
        if path:
            self.set_split_source(path)

    def drop_split_paths(self, paths: list[str]) -> None:
        if len(paths) != 1:
            QMessageBox.warning(
                self,
                "PDF 파일 선택",
                "나눌 PDF 파일은 한 개만 끌어 놓아 주세요.",
            )
            return
        self.set_split_source(paths[0])

    def set_split_source(self, value: str) -> None:
        path = Path(value).expanduser().resolve()
        try:
            pages, size = get_pdf_info(path)
        except PdfError as exc:
            QMessageBox.warning(self, "PDF를 열 수 없음", str(exc))
            return
        self.split_source = path
        self.split_total_pages = pages
        self.split_source_label.setText(f"{path.name}\n{pages}쪽 · {format_size(size)}")
        self.split_source_group.show()
        self.pages_per_file.setRange(1, pages)
        self.pages_per_file.setValue(min(50, pages))
        self.split_folder.setText(str(path.parent / f"{path.stem}_분할"))
        self.reset_range_rows()
        self.update_split_preview()

    def clear_split_source(self) -> None:
        self.split_source = None
        self.split_total_pages = 0
        self.split_source_label.setText("PDF를 선택해 주세요.")
        self.split_source_group.hide()
        self.pages_per_file.setRange(1, 1)
        self.pages_per_file.setValue(1)
        self.split_folder.clear()
        self.reset_range_rows()
        self.update_split_preview()

    def update_split_mode(self) -> None:
        self.split_settings.setCurrentIndex(0 if self.fixed_radio.isChecked() else 1)
        for card, active in (
            (self.fixed_card, self.fixed_radio.isChecked()),
            (self.range_card, self.range_radio.isChecked()),
        ):
            card.setProperty("active", active)
            card.style().unpolish(card)
            card.style().polish(card)
        self.update_split_preview()

    def reset_range_rows(self) -> None:
        for row in self.range_rows:
            row["widget"].deleteLater()
        self.range_rows.clear()
        if self.split_total_pages:
            self.add_range_row(1, min(20, self.split_total_pages))

    def add_range_row(self, start: int | None = None, end: int | None = None) -> None:
        if not self.split_total_pages:
            return
        if start is None:
            previous_end = self.range_rows[-1]["end"].value() if self.range_rows else 0
            if previous_end >= self.split_total_pages:
                QMessageBox.information(self, "범위 추가", "이미 마지막 페이지까지 지정했습니다.")
                return
            start = previous_end + 1
            end = min(self.split_total_pages, start + 19)

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 2)
        label = QLabel()
        start_input = QSpinBox()
        end_input = QSpinBox()
        delete_button = QPushButton("삭제")
        for field in (start_input, end_input):
            field.setRange(1, self.split_total_pages)
            field.setMinimumWidth(80)
            field.valueChanged.connect(self.update_split_preview)
        start_input.setValue(start)
        end_input.setValue(end if end is not None else start)
        layout.addWidget(label)
        layout.addWidget(start_input)
        layout.addWidget(QLabel("쪽부터"))
        layout.addWidget(end_input)
        layout.addWidget(QLabel("쪽까지"))
        layout.addWidget(delete_button)
        layout.addStretch()
        state = {
            "widget": widget,
            "label": label,
            "start": start_input,
            "end": end_input,
            "delete": delete_button,
        }
        delete_button.clicked.connect(lambda: self.delete_range_row(state))
        self.range_rows.append(state)
        self.ranges_layout.addWidget(widget)
        self.refresh_range_rows()

    def delete_range_row(self, row: dict[str, Any]) -> None:
        if len(self.range_rows) == 1:
            return
        self.range_rows.remove(row)
        row["widget"].deleteLater()
        self.refresh_range_rows()

    def refresh_range_rows(self) -> None:
        for index, row in enumerate(self.range_rows, 1):
            row["label"].setText(f"범위 {index}")
            row["delete"].setEnabled(len(self.range_rows) > 1)
        self.update_split_preview()

    def current_ranges(self) -> list[tuple[int, int]]:
        return [(row["start"].value(), row["end"].value()) for row in self.range_rows]

    def update_split_preview(self) -> None:
        self.result_list.clear()
        if not self.split_source:
            self.result_count.setText("PDF를 먼저 선택해 주세요.")
            self.range_warning.clear()
            self.split_run_button.setText("PDF 나누기")
            self.split_run_button.setEnabled(False)
            return

        try:
            if self.fixed_radio.isChecked():
                ranges = plan_fixed(self.split_total_pages, self.pages_per_file.value())
                warning = ""
            else:
                ranges = validate_ranges(self.split_total_pages, self.current_ranges())
                missing = missing_page_count(self.split_total_pages, ranges)
                selected = self.split_total_pages - missing
                warning = (
                    f"전체 {self.split_total_pages}쪽 중 {selected}쪽 지정 · "
                    f"나머지 {missing}쪽은 결과에 포함되지 않습니다."
                    if missing
                    else f"전체 {self.split_total_pages}쪽이 결과에 포함됩니다."
                )
        except PdfError as exc:
            self.result_count.setText("범위를 확인해 주세요.")
            self.range_warning.setText(str(exc))
            self.split_run_button.setText("범위를 확인해 주세요")
            self.split_run_button.setEnabled(False)
            return

        width = max(3, len(str(self.split_total_pages)))
        for start, end in ranges[:12]:
            self.result_list.addItem(
                f"{self.split_source.stem}_{start:0{width}d}-{end:0{width}d}.pdf"
            )
        if len(ranges) > 12:
            self.result_list.addItem(f"외 {len(ranges) - 12}개")
        self.result_count.setText(f"{len(ranges)}개 파일")
        self.range_warning.setText(warning)
        self.split_run_button.setText(f"{len(ranges)}개 파일로 나누기")
        self.split_run_button.setEnabled(not self.worker)

    def choose_split_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "나눈 PDF 저장 위치", self.split_folder.text())
        if folder:
            self.split_folder.setText(folder)

    def run_split(self) -> None:
        if not self.split_source:
            return
        try:
            folder = required_folder(self.split_folder.text())
            if self.fixed_radio.isChecked():
                plan_fixed(self.split_total_pages, self.pages_per_file.value())
                operation = partial(
                    split_fixed,
                    self.split_source,
                    self.pages_per_file.value(),
                    folder,
                )
            else:
                ranges = validate_ranges(self.split_total_pages, self.current_ranges())
                operation = partial(split_ranges, self.split_source, ranges, folder)
        except PdfError as exc:
            QMessageBox.warning(self, "나누기 설정 확인", str(exc))
            return
        self.start_task(operation, self.split_completed, "PDF를 나누고 있습니다.")

    def start_task(self, operation: Any, on_success: Any, text: str) -> None:
        if self.worker:
            return
        self.success_handler = on_success
        self.progress_dialog = QProgressDialog(text, "취소", 0, 0, self)
        self.progress_dialog.setWindowTitle("PDF 작업")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)
        self.progress_dialog.setMinimumDuration(0)

        self.worker = PdfWorker(operation)
        self.worker.progressed.connect(self.update_progress)
        self.worker.succeeded.connect(self.task_succeeded)
        self.worker.failed.connect(self.task_failed)
        self.worker.cancelled.connect(self.task_cancelled)
        self.worker.finished.connect(self.task_finished)
        self.progress_dialog.canceled.connect(self.cancel_task)
        self.merge_run_button.setEnabled(False)
        self.split_run_button.setEnabled(False)
        self.worker.start()

    def update_progress(self, done: int, total: int) -> None:
        if not self.progress_dialog:
            return
        self.progress_dialog.setRange(0, total)
        self.progress_dialog.setValue(done)
        self.progress_dialog.setLabelText(f"PDF를 처리하고 있습니다.  {done} / {total}")

    def cancel_task(self) -> None:
        if self.worker:
            self.worker.cancel()
        if self.progress_dialog:
            self.progress_dialog.setLabelText("작업을 취소하고 임시 파일을 정리하고 있습니다.")
            self.progress_dialog.setCancelButton(None)

    def task_succeeded(self, result: object) -> None:
        self.close_progress()
        if self.success_handler:
            self.success_handler(result)

    def task_failed(self, message: str) -> None:
        self.close_progress()
        QMessageBox.critical(self, "작업을 완료하지 못했습니다", message)

    def task_cancelled(self) -> None:
        self.close_progress()
        QMessageBox.information(self, "작업 취소", "작업을 취소했습니다. 원본 파일은 변경되지 않았습니다.")

    def task_finished(self) -> None:
        if self.worker:
            self.worker.deleteLater()
        self.worker = None
        self.success_handler = None
        self.update_merge_view()
        self.update_split_preview()

    def close_progress(self) -> None:
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None

    def merge_completed(self, result: object) -> None:
        path = Path(str(result))
        self.show_complete("PDF 합치기 완료", path.name, path)

    def split_completed(self, result: object) -> None:
        paths = [Path(str(path)) for path in result]  # type: ignore[union-attr]
        if paths:
            self.show_complete("PDF 나누기 완료", f"{len(paths)}개 파일을 저장했습니다.", paths[0].parent)

    def show_complete(self, title: str, text: str, target: Path) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("저장이 완료되었습니다.")
        box.setInformativeText(text)
        open_button = box.addButton(
            "파일 열기" if target.is_file() else "폴더 열기", QMessageBox.ButtonRole.ActionRole
        )
        folder_button = None
        if target.is_file():
            folder_button = box.addButton("폴더 열기", QMessageBox.ButtonRole.ActionRole)
        box.addButton("닫기", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        elif folder_button and box.clickedButton() is folder_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

    def show_help(self) -> None:
        QMessageBox.information(
            self,
            "사용 방법",
            "1. PDF 파일을 선택합니다.\n"
            "2. 합칠 순서나 나눌 범위를 확인합니다.\n"
            "3. 파란색 실행 버튼을 누릅니다.\n\n"
            "모든 결과는 새 파일로 저장되며 원본은 변경되지 않습니다.",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "작업 진행 중", "진행 중인 작업을 취소한 후 프로그램을 닫아 주세요.")
            event.ignore()
            return
        event.accept()


def safe_pdf_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise PdfError("파일 이름을 입력해 주세요.")
    if Path(name).name != name or any(character in name for character in '<>:"/\\|?*'):
        raise PdfError("파일 이름에 경로 문자나 사용할 수 없는 문자가 있습니다.")
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    stem = Path(name).stem
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if stem.upper() in reserved or stem.endswith((" ", ".")):
        raise PdfError("Windows에서 사용할 수 없는 파일 이름입니다.")
    return name


def required_folder(value: str) -> Path:
    if not value.strip():
        raise PdfError("저장 위치를 선택해 주세요.")
    return Path(value).expanduser()


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def configure_app(app: QApplication) -> None:
    app.setApplicationName("PDF 정리")
    app.setStyle("Fusion")
    app.setStyleSheet(
        """
        * {
            color: #eef1f5;
            font-family: "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
            font-size: 14px;
        }
        QMainWindow, QWidget#root, QWidget#page { background: #1d2026; }
        QFrame#headerBar {
            background: #282d35;
            border-bottom: 1px solid #424955;
        }
        QLabel#logo {
            background: #2d6cdf;
            color: white;
            border-radius: 11px;
            font-size: 17px;
            font-weight: 700;
        }
        QLabel#appTitle { font-size: 21px; font-weight: 700; }
        QLabel#pageTitle { font-size: 27px; font-weight: 600; }
        QLabel#muted { color: #b9c0ca; }
        QLabel#dropTitle { font-size: 16px; font-weight: 600; }
        QLabel#sourceLabel { font-size: 16px; font-weight: 600; }
        QLabel#fileName { font-size: 15px; font-weight: 600; }
        QLabel#dragHandle { color: #9ca5b3; font-size: 20px; }
        QLabel#orderBadge {
            color: #9fc0ff;
            background: #344969;
            border-radius: 17px;
            font-weight: 700;
        }
        QLabel#summary {
            background: #252a32;
            border: 1px solid #444c58;
            border-radius: 9px;
            padding: 12px 18px;
            font-size: 16px;
            font-weight: 700;
        }
        QLabel#resultCount {
            color: #77a7ff;
            font-size: 26px;
            font-weight: 700;
        }
        QLabel#warning { color: #ffb84d; }
        QTabWidget::pane { border: 0; background: #1d2026; }
        QTabBar { background: #282d35; border-bottom: 1px solid #424955; }
        QTabBar::tab {
            background: #282d35;
            color: #b9c0ca;
            min-width: 190px;
            min-height: 58px;
            padding: 0 16px;
            border: 0;
            border-bottom: 3px solid transparent;
            font-size: 17px;
            font-weight: 600;
        }
        QTabBar::tab:selected {
            color: #73a7ff;
            border-bottom: 3px solid #2d6cdf;
        }
        QFrame#dropZone {
            background: #252a32;
            border: 2px dashed #5a6371;
            border-radius: 12px;
        }
        QFrame#card, QFrame#modeCard, QGroupBox#cardGroup {
            background: #252a32;
            border: 1px solid #454d59;
            border-radius: 11px;
        }
        QFrame#modeCard[active="true"] {
            background: #29364b;
            border: 2px solid #2d6cdf;
        }
        QGroupBox#cardGroup {
            margin-top: 12px;
            padding: 18px 14px 14px 14px;
            font-size: 16px;
            font-weight: 600;
        }
        QGroupBox#cardGroup::title {
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 5px;
            color: #eef1f5;
        }
        QWidget#mergeRow { background: #252a32; }
        QPushButton {
            min-height: 34px;
            padding: 4px 14px;
            background: #2c3139;
            color: #eef1f5;
            border: 1px solid #555e6c;
            border-radius: 8px;
            font-weight: 600;
        }
        QPushButton:hover { background: #353b45; border-color: #6a7586; }
        QPushButton:pressed { background: #242931; }
        QPushButton:disabled { color: #6f7782; background: #252a31; border-color: #353b45; }
        QPushButton#primary {
            min-height: 44px;
            padding: 5px 20px;
            background: #2d6cdf;
            color: white;
            border: 1px solid #2459b8;
            border-radius: 9px;
            font-size: 16px;
            font-weight: 700;
        }
        QPushButton#primary:hover { background: #3978e7; }
        QPushButton#primary:disabled { background: #344052; color: #798493; border-color: #3c4654; }
        QPushButton#rowButton { min-width: 44px; padding: 2px 9px; }
        QLineEdit, QSpinBox {
            min-height: 36px;
            padding: 2px 10px;
            color: #eef1f5;
            background: #1d2229;
            border: 1px solid #555e6c;
            border-radius: 7px;
            selection-background-color: #2d6cdf;
        }
        QLineEdit:focus, QSpinBox:focus { border: 1px solid #4d87ee; }
        QSpinBox::up-button, QSpinBox::down-button { width: 18px; background: #303640; }
        QListWidget {
            color: #eef1f5;
            background: #252a32;
            border: 1px solid #454d59;
            border-radius: 10px;
            outline: 0;
            padding: 0;
        }
        QListWidget::item { border-bottom: 1px solid #3e4651; }
        QListWidget::item:selected { background: #2e3744; }
        QListWidget#mergeList::item { min-height: 68px; }
        QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: 0; }
        QScrollArea#pageScroll { background: #1d2026; }
        QRadioButton { font-size: 16px; font-weight: 600; spacing: 10px; }
        QRadioButton::indicator {
            width: 17px;
            height: 17px;
            border: 2px solid #9ca5b3;
            border-radius: 10px;
            background: transparent;
        }
        QRadioButton::indicator:checked {
            background: #2d6cdf;
            border: 3px solid #8ab3ff;
        }
        QProgressDialog, QMessageBox { background: #252a32; }
        QToolTip {
            color: #eef1f5;
            background: #303640;
            border: 1px solid #596373;
            padding: 5px;
        }
        QScrollBar:vertical { width: 10px; background: #20242a; }
        QScrollBar::handle:vertical { background: #4b5360; border-radius: 5px; min-height: 28px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """
    )


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    configure_app(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
