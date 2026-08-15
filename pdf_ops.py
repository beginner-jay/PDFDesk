from __future__ import annotations

import errno
import os
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from pypdf import PdfReader, PdfWriter

Progress = Callable[[int, int], None]
Cancelled = Callable[[], bool]


class PdfError(Exception):
    """사용자에게 보여 줄 수 있는 PDF 작업 오류."""


class PdfCancelled(PdfError):
    pass


def get_pdf_info(path: str | Path) -> tuple[int, int]:
    reader = _open_reader(path)
    try:
        return len(reader.pages), Path(path).stat().st_size
    finally:
        reader.close()


def plan_fixed(total_pages: int, pages_per_file: int) -> list[tuple[int, int]]:
    if not isinstance(pages_per_file, int) or isinstance(pages_per_file, bool):
        raise PdfError("나눌 페이지 수는 숫자로 입력해 주세요.")
    if not 1 <= pages_per_file <= total_pages:
        raise PdfError(f"페이지 수는 1부터 {total_pages}까지 입력해 주세요.")
    return [
        (start, min(total_pages, start + pages_per_file - 1))
        for start in range(1, total_pages + 1, pages_per_file)
    ]


def validate_ranges(
    total_pages: int, ranges: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    if not ranges:
        raise PdfError("페이지 범위를 하나 이상 지정해 주세요.")

    checked: list[tuple[int, int]] = []
    for index, pair in enumerate(ranges, 1):
        if len(pair) != 2:
            raise PdfError(f"범위 {index}의 시작과 끝을 확인해 주세요.")
        start, end = pair
        if any(not isinstance(value, int) or isinstance(value, bool) for value in pair):
            raise PdfError(f"범위 {index}에는 페이지 번호를 입력해 주세요.")
        if not 1 <= start <= end <= total_pages:
            raise PdfError(
                f"범위 {index}은 1~{total_pages}쪽 안에서 시작과 끝을 확인해 주세요."
            )
        checked.append((start, end))

    ordered = sorted(checked)
    if any(start <= ordered[index - 1][1] for index, (start, _) in enumerate(ordered[1:], 1)):
        raise PdfError("겹치는 페이지 범위가 있습니다.")
    return checked


def missing_page_count(total_pages: int, ranges: Sequence[tuple[int, int]]) -> int:
    checked = validate_ranges(total_pages, ranges)
    return total_pages - sum(end - start + 1 for start, end in checked)


def merge_pdfs(
    inputs: Sequence[str | Path],
    output: str | Path,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> Path:
    if len(inputs) < 2:
        raise PdfError("합칠 PDF를 두 개 이상 선택해 주세요.")

    readers: list[PdfReader] = []
    temp_path: Path | None = None
    try:
        readers = [_open_reader(path) for path in inputs]
        total_pages = sum(len(reader.pages) for reader in readers)
        total_steps = total_pages + 1
        done = 0
        writer = PdfWriter()
        for reader in readers:
            for page in reader.pages:
                _check_cancelled(cancelled)
                writer.add_page(page)
                done += 1
                _report(progress, done, total_steps)

        _check_cancelled(cancelled)
        desired = _pdf_path(output)
        temp_path = _write_temp(writer, desired.parent)
        _verify_pdf(temp_path, total_pages)
        _report(progress, total_steps, total_steps)
        return _commit_without_overwrite(temp_path, desired)
    except (PdfError, PdfCancelled):
        raise
    except Exception as exc:
        raise PdfError(f"PDF를 합치지 못했습니다: {exc}") from exc
    finally:
        for reader in readers:
            reader.close()
        _remove(temp_path)


def split_fixed(
    source: str | Path,
    pages_per_file: int,
    output_dir: str | Path,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> list[Path]:
    reader = _open_reader(source)
    try:
        ranges = plan_fixed(len(reader.pages), pages_per_file)
    finally:
        reader.close()
    return split_ranges(source, ranges, output_dir, progress, cancelled)


def split_ranges(
    source: str | Path,
    ranges: Sequence[tuple[int, int]],
    output_dir: str | Path,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> list[Path]:
    reader = _open_reader(source)
    temporary: list[tuple[Path, Path]] = []
    committed: list[Path] = []
    try:
        total_pages = len(reader.pages)
        checked = validate_ranges(total_pages, ranges)
        directory = Path(output_dir)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PdfError(f"저장 폴더를 만들 수 없습니다: {exc}") from exc

        width = max(3, len(str(total_pages)))
        stem = Path(source).stem
        total_steps = sum(end - start + 1 for start, end in checked) + len(checked)
        done = 0

        for start, end in checked:
            writer = PdfWriter()
            for page_number in range(start - 1, end):
                _check_cancelled(cancelled)
                writer.add_page(reader.pages[page_number])
                done += 1
                _report(progress, done, total_steps)

            desired = directory / f"{stem}_{start:0{width}d}-{end:0{width}d}.pdf"
            temp = _write_temp(writer, directory)
            temporary.append((temp, desired))
            _verify_pdf(temp, end - start + 1)
            done += 1
            _report(progress, done, total_steps)

        _check_cancelled(cancelled)
        for temp, desired in temporary:
            committed.append(_commit_without_overwrite(temp, desired))
        return committed
    except (PdfError, PdfCancelled):
        for path in committed:
            _remove(path)
        raise
    except Exception as exc:
        for path in committed:
            _remove(path)
        raise PdfError(f"PDF를 나누지 못했습니다: {exc}") from exc
    finally:
        reader.close()
        for temp, _ in temporary:
            _remove(temp)


def _open_reader(path: str | Path) -> PdfReader:
    pdf = Path(path)
    if pdf.suffix.lower() != ".pdf" or not pdf.is_file():
        raise PdfError(f"PDF 파일을 찾을 수 없습니다: {pdf.name}")
    try:
        reader = PdfReader(pdf)
        if reader.is_encrypted:
            reader.close()
            raise PdfError(
                f"암호가 설정된 PDF입니다: {pdf.name}\n암호가 없는 사본을 준비해 주세요."
            )
        if len(reader.pages) < 1:
            reader.close()
            raise PdfError(f"페이지가 없는 PDF입니다: {pdf.name}")
        return reader
    except PdfError:
        raise
    except Exception as exc:
        raise PdfError(f"PDF를 열 수 없습니다: {pdf.name}\n{exc}") from exc


def _write_temp(writer: PdfWriter, directory: Path) -> Path:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".pdfdesk-", suffix=".tmp", dir=directory)
        os.close(descriptor)
        temp = Path(name)
        with temp.open("wb") as output:
            writer.write(output)
        writer.close()
        return temp
    except Exception:
        if "temp" in locals():
            _remove(temp)
        raise


def _verify_pdf(path: Path, expected_pages: int) -> None:
    try:
        reader = PdfReader(path)
        actual_pages = len(reader.pages)
        reader.close()
    except Exception as exc:
        raise PdfError(f"저장된 PDF를 확인할 수 없습니다: {exc}") from exc
    if actual_pages != expected_pages:
        raise PdfError(
            f"저장 결과의 페이지 수가 다릅니다. 예상 {expected_pages}쪽, 실제 {actual_pages}쪽"
        )


def _commit_without_overwrite(temp: Path, desired: Path) -> Path:
    desired = _pdf_path(desired)
    for number in range(10_000):
        candidate = (
            desired
            if number == 0
            else desired.with_name(f"{desired.stem} ({number}){desired.suffix}")
        )
        try:
            os.link(temp, candidate)
        except FileExistsError:
            continue
        except OSError as exc:
            if exc.errno not in {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV}:
                raise
            try:
                descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
                os.close(descriptor)
            except FileExistsError:
                continue
            try:
                os.replace(temp, candidate)
            except Exception:
                _remove(candidate)
                raise
            return candidate
        else:
            temp.unlink()
            return candidate
    raise PdfError("같은 이름의 파일이 너무 많아 결과를 저장하지 못했습니다.")


def _pdf_path(path: str | Path) -> Path:
    output = Path(path)
    return output if output.suffix.lower() == ".pdf" else output.with_suffix(".pdf")


def _check_cancelled(cancelled: Cancelled | None) -> None:
    if cancelled and cancelled():
        raise PdfCancelled("작업이 취소되었습니다.")


def _report(progress: Progress | None, done: int, total: int) -> None:
    if progress:
        progress(done, total)


def _remove(path: Path | None) -> None:
    if path:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
