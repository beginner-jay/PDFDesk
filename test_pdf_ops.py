import tempfile
import unittest
import os
from functools import partial
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter

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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from PySide6.QtCore import QMimeData, Qt, QUrl  # noqa: E402
from PySide6.QtTest import QSignalSpy, QTest  # noqa: E402
from main import (  # noqa: E402
    DragHandle,
    MainWindow,
    PdfWorker,
    configure_app,
    safe_pdf_name,
)


def make_pdf(path: Path, widths: list[int]) -> None:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=100)
    with path.open("wb") as output:
        writer.write(output)
    writer.close()


class FakeDropEvent:
    def __init__(self, paths: list[Path]) -> None:
        self.mime = QMimeData()
        self.mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        self.accepted = False

    def mimeData(self) -> QMimeData:
        return self.mime

    def acceptProposedAction(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.accepted = False

    def isAccepted(self) -> bool:
        return self.accepted


def make_drop_event(paths: list[Path]) -> FakeDropEvent:
    return FakeDropEvent(paths)


class PdfOpsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_merge_preserves_order_and_sources(self) -> None:
        first = self.root / "공문.pdf"
        second = self.root / "붙임.pdf"
        make_pdf(first, [101, 102])
        make_pdf(second, [201])
        original = first.read_bytes()
        progress: list[tuple[int, int]] = []

        result = merge_pdfs(
            [first, second], self.root / "합친파일.pdf", lambda done, total: progress.append((done, total))
        )

        reader = PdfReader(result)
        self.assertEqual([int(page.mediabox.width) for page in reader.pages], [101, 102, 201])
        reader.close()
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(progress[-1][0], progress[-1][1])

    def test_fixed_and_range_split(self) -> None:
        source = self.root / "회의자료.pdf"
        make_pdf(source, [100, 101, 102, 103, 104])

        fixed = split_fixed(source, 2, self.root / "고정")
        ranged = split_ranges(source, [(2, 3), (5, 5)], self.root / "범위")

        self.assertEqual([len(PdfReader(path).pages) for path in fixed], [2, 2, 1])
        self.assertEqual([path.name for path in ranged], ["회의자료_002-003.pdf", "회의자료_005-005.pdf"])
        self.assertEqual(missing_page_count(5, [(2, 3), (5, 5)]), 2)

    def test_validation_rejects_invalid_or_overlapping_ranges(self) -> None:
        self.assertEqual(plan_fixed(5, 2), [(1, 2), (3, 4), (5, 5)])
        with self.assertRaises(PdfError):
            plan_fixed(5, 0)
        with self.assertRaisesRegex(PdfError, "겹치는"):
            validate_ranges(10, [(1, 5), (5, 8)])
        with self.assertRaisesRegex(PdfError, "1~10"):
            validate_ranges(10, [(0, 3)])

    def test_existing_result_is_not_overwritten(self) -> None:
        source = self.root / "문서.pdf"
        output_dir = self.root / "결과"
        output_dir.mkdir()
        make_pdf(source, [100, 101])
        existing = output_dir / "문서_001-002.pdf"
        existing.write_bytes(b"keep me")

        result = split_fixed(source, 2, output_dir)

        self.assertEqual(existing.read_bytes(), b"keep me")
        self.assertEqual(result[0].name, "문서_001-002 (1).pdf")

    def test_cancel_removes_temporary_outputs(self) -> None:
        source = self.root / "취소.pdf"
        output_dir = self.root / "결과"
        make_pdf(source, list(range(100, 110)))
        calls = 0

        def cancelled() -> bool:
            nonlocal calls
            calls += 1
            return calls > 2

        with self.assertRaises(PdfCancelled):
            split_fixed(source, 2, output_dir, cancelled=cancelled)
        self.assertEqual(list(output_dir.iterdir()), [])

    def test_encrypted_pdf_is_rejected(self) -> None:
        encrypted = self.root / "보안문서.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("secret")
        with encrypted.open("wb") as output:
            writer.write(output)
        writer.close()

        with self.assertRaisesRegex(PdfError, "암호"):
            get_pdf_info(encrypted)

    def test_info_reports_pages_and_size(self) -> None:
        source = self.root / "정보.pdf"
        make_pdf(source, [100, 101, 102])
        pages, size = get_pdf_info(source)
        self.assertEqual(pages, 3)
        self.assertGreater(size, 0)


class GuiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        configure_app(cls.app)

    def test_window_and_default_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "회의자료.pdf"
            make_pdf(source, list(range(100, 130)))
            window = MainWindow()
            window.set_split_source(str(source))

            self.assertEqual(window.tabs.count(), 2)
            self.assertEqual(len(window.range_rows), 1)
            self.assertEqual(window.current_ranges(), [(1, 20)])
            self.assertEqual(window.pages_per_file.suffix(), "")
            window.pages_per_file.setFocus()
            window.pages_per_file.selectAll()
            QTest.keyClicks(window.pages_per_file, "abc25")
            self.assertEqual(window.pages_per_file.value(), 25)
            self.assertEqual(window.pages_per_file.text(), "25")
            self.assertTrue(window.merge_list.dragEnabled())
            window.add_range_row()
            self.assertEqual(window.current_ranges(), [(1, 20), (21, 30)])
            window.close()

    def test_cross_platform_file_name_validation(self) -> None:
        self.assertEqual(safe_pdf_name("결과"), "결과.pdf")
        with self.assertRaises(PdfError):
            safe_pdf_name("CON.pdf")
        with self.assertRaises(PdfError):
            safe_pdf_name("폴더/결과.pdf")

    def test_drag_handle_reorders_merge_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / f"{name}.pdf" for name in ("첫째", "둘째", "셋째")]
            for path in paths:
                make_pdf(path, [100])
            window = MainWindow()
            window.add_merge_paths([str(path) for path in paths])
            window.show()
            self.app.processEvents()

            first_item = window.merge_list.item(0)
            handle = window.merge_list.itemWidget(first_item).findChild(DragHandle)
            destination = window.merge_list.viewport().mapToGlobal(
                window.merge_list.visualItemRect(window.merge_list.item(2)).center()
            )
            QTest.mousePress(handle, Qt.MouseButton.LeftButton)
            QTest.mouseRelease(
                handle,
                Qt.MouseButton.LeftButton,
                pos=handle.mapFromGlobal(destination),
            )
            self.app.processEvents()

            self.assertEqual(
                Path(window.merge_list.item(2).data(Qt.ItemDataRole.UserRole)[0]).name,
                "첫째.pdf",
            )
            window.close()

    def test_file_drop_selects_merge_and_split_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "첫째.pdf"
            second = root / "둘째.pdf"
            make_pdf(first, [100])
            make_pdf(second, [100, 101])
            window = MainWindow()

            merge_drop = make_drop_event([first, second])
            window.merge_drop_zone.dropEvent(merge_drop)
            self.assertTrue(merge_drop.isAccepted())
            self.assertEqual(window.merge_list.count(), 2)

            split_drop = make_drop_event([second])
            window.split_drop_zone.dropEvent(split_drop)
            self.assertTrue(split_drop.isAccepted())
            self.assertEqual(window.split_source, second.resolve())
            self.assertFalse(window.split_source_group.isHidden())

            window.clear_split_source()
            with patch.object(QMessageBox, "warning") as warning:
                window.split_drop_zone.dropEvent(make_drop_event([first, second]))
            warning.assert_called_once()
            self.assertIsNone(window.split_source)
            window.close()

    def test_background_worker_completes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "첫째.pdf"
            second = root / "둘째.pdf"
            output = root / "결과.pdf"
            make_pdf(first, [100])
            make_pdf(second, [200])
            worker = PdfWorker(partial(merge_pdfs, [first, second], output))
            succeeded = QSignalSpy(worker.succeeded)
            failed = QSignalSpy(worker.failed)

            worker.start()
            self.assertTrue(worker.wait(3000))
            self.app.processEvents()

            self.assertEqual(failed.count(), 0)
            self.assertEqual(succeeded.count(), 1)
            self.assertEqual(len(PdfReader(output).pages), 2)


if __name__ == "__main__":
    unittest.main()
