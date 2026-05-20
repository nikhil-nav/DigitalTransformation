"""Cheap workbook inspection: sheet names + per-sheet row/column counts.

Uses openpyxl in read_only mode so we never load full sheets into memory.
Row and column counts are computed by streaming through cells rather than
relying on `max_row` / `max_column`, which are approximate in read_only mode
and can include trailing empty rows. Counts here are the number of rows that
contain at least one non-None cell and the maximum cell-count across those
rows. They are precise enough for upload-time metadata; per-column dtype
analysis happens in Part 3.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

# Bump this string any time the inspection logic changes in a way that
# alters its output. Persisted alongside each dataset row so we can detect
# stale metadata.
INSPECTOR_VERSION = "1.0.0"


class WorkbookError(Exception):
    """Base class for inspection failures we expect to report to the user."""


class PasswordProtectedError(WorkbookError):
    """The workbook is encrypted; we can't open it without a password."""


class BadWorkbookError(WorkbookError):
    """The file is not a valid .xlsx (corrupt, wrong format, etc)."""


@dataclass(frozen=True)
class SheetSummary:
    name: str
    row_count: int
    column_count: int


@dataclass(frozen=True)
class WorkbookSummary:
    sheets: list[SheetSummary]


def _is_encrypted_xlsx(path: Path) -> bool:
    """An encrypted .xlsx is a CFB (compound) file, not a zip. Cheap probe."""
    try:
        with path.open("rb") as fp:
            head = fp.read(8)
    except OSError:
        return False
    # CFB header signature
    return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")


def inspect_workbook(path: Path) -> WorkbookSummary:
    """Open an .xlsx and return per-sheet name + row/column counts.

    Raises:
        PasswordProtectedError: workbook is encrypted.
        BadWorkbookError: file is corrupt, missing, or not a real xlsx.
    """
    if not path.exists():
        raise BadWorkbookError(f"File missing: {path}")

    # Probe for encryption before openpyxl, which raises a non-specific
    # InvalidFileException for both encryption and malformed files.
    if _is_encrypted_xlsx(path):
        raise PasswordProtectedError(
            "Workbook is password-protected; remove the password and re-upload."
        )

    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except InvalidFileException as e:
        raise BadWorkbookError(f"Not a valid .xlsx file: {e}") from e
    except zipfile.BadZipFile as e:
        raise BadWorkbookError(f"File is not a valid Excel workbook: {e}") from e
    except Exception as e:  # noqa: BLE001 - openpyxl raises broad errors here
        raise BadWorkbookError(f"Failed to open workbook: {e}") from e

    try:
        sheets: list[SheetSummary] = []
        for name in wb.sheetnames:
            ws = wb[name]
            row_count = 0
            column_count = 0
            for row in ws.iter_rows(values_only=True):
                has_value = False
                width = 0
                for i, cell in enumerate(row, start=1):
                    if cell is not None and cell != "":
                        has_value = True
                        width = i
                if has_value:
                    row_count += 1
                    if width > column_count:
                        column_count = width
            sheets.append(
                SheetSummary(name=name, row_count=row_count, column_count=column_count)
            )
        return WorkbookSummary(sheets=sheets)
    finally:
        wb.close()
