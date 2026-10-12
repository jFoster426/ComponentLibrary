#!/usr/bin/env python3
"""CSV Manager: a behaviour-for-behaviour Python port of ``CSVGuiApp.java``.

Swing is replaced by PySide6 (Qt 6, LGPL) and Apache Commons CSV by a small,
faithful port of its ``CSVFormat.DEFAULT`` lexer/printer, because Python's
``csv`` module parses and quotes differently (e.g. whitespace after a closing
quote, MINIMAL quoting rules, field-size limit).

Parity notes
------------
Known defects of the Java original are reproduced on purpose so the port is a
drop-in replacement; each is marked ``JAVA PARITY`` and listed in the review.
Deliberate deviations are marked ``FIX`` (Add Row selection; Add Row copies
modified input fields).
Uncaught exceptions are printed to stderr and the app keeps running, which is
what the Swing event-dispatch thread does (PyQt/PySide would otherwise abort).

Requires: Python >= 3.10, PySide6 >= 6.2.
"""

from __future__ import annotations

import enum
import functools
import math
import sys
import traceback
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, ParamSpec, TextIO, TypeVar

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QFileSystemWatcher,
    QItemSelectionModel,
    QKeyCombination,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    QStringListModel,
    Qt,
    QTimer,
)
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCompleter,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence
    from types import TracebackType

# =============================================================================
# Configuration: every literal used by the application lives here.
# =============================================================================

# --- Application / data -------------------------------------------------------
APP_WINDOW_TITLE: Final[str] = "CSV Manager"
DEFAULT_CSV_PATH: Final[str] = "../components.csv"  # resolved against the CWD, as in Java
COLUMN_NAMES: Final[tuple[str, ...]] = (
    "Part Name",
    "Library Ref",
    "Footprint Ref",
    "CreatedBy",
    "HelpURL",
    "Manufacturer 1",
    "Manufacturer 1 Part Number",
    "Vendor 1",
    "Vendor 1 Part Number",
    "Description",
    "Value",
    "Comment",
)

# --- Widget text ----------------------------------------------------------------
SEARCH_LABEL_TEXT: Final[str] = "Search: "
INPUT_LABEL_SUFFIX: Final[str] = ":"
ADD_ROW_BUTTON_TEXT: Final[str] = "Add Row"
UPDATE_ROW_BUTTON_TEXT: Final[str] = "Update Row"
FILE_MENU_TITLE: Final[str] = "File"
OPEN_MENU_ITEM_TEXT: Final[str] = "Open CSV"
SAVE_MENU_ITEM_TEXT: Final[str] = "Save CSV"
OPEN_DIALOG_TITLE: Final[str] = "Open CSV"
OPEN_DIALOG_START_DIR: Final[str] = ""  # "" = current working directory (AWT FileDialog default)
OPEN_DIALOG_FILTER: Final[str] = ""  # AWT FileDialog had no filter

# --- User-facing messages (texts identical to the Java app) --------------------
MESSAGE_DIALOG_TITLE: Final[str] = "Message"  # JOptionPane.showMessageDialog default title
MSG_FILE_NOT_FOUND: Final[str] = "File not found or invalid: {path}"
MSG_INVALID_FILE: Final[str] = "Invalid file selected."
MSG_NO_HEADERS: Final[str] = "No headers found in CSV file."
MSG_READ_ERROR: Final[str] = "Error reading file: {error}"
MSG_UNEXPECTED_ERROR: Final[str] = "Unexpected error: {error}"
MSG_SAVE_SUCCESS: Final[str] = "File saved successfully: {path}"
MSG_SAVE_ERROR: Final[str] = "Error saving file: {error}"
NO_ROW_SELECTED_TITLE: Final[str] = "No Row Selected"
MSG_NO_ROW_SELECTED: Final[str] = "Please select a row to update."
LOG_ROW_ERROR: Final[str] = "Error processing row: {record} - {error}"
JAVA_IO_ERROR_MESSAGE: Final[str] = "{path} ({reason})"  # FileNotFoundException.getMessage() shape

# --- Messages of the runtime errors the Java code throws (logged to stderr) ----
ERR_NULL_CELL: Final[str] = (
    'Cannot invoke "Object.toString()" because the return value of "DefaultTableModel.getValueAt(int, int)" is null'
)
ERR_EMPTY_SEARCH_TERMS: Final[str] = "Index 0 out of bounds for length 0"

# --- Keyboard bindings (Swing CTRL_DOWN_MASK is the physical Control key, which
#     Qt reports as MetaModifier on macOS) --------------------------------------
SHORTCUT_MODIFIER: Final[Qt.KeyboardModifier] = (
    Qt.KeyboardModifier.MetaModifier if sys.platform == "darwin" else Qt.KeyboardModifier.ControlModifier
)
KEY_OPEN_CSV: Final[Qt.Key] = Qt.Key.Key_O
KEY_SAVE_CSV: Final[Qt.Key] = Qt.Key.Key_S
KEY_ADD_ROW: Final[Qt.Key] = Qt.Key.Key_Q
KEY_UPDATE_ROW: Final[Qt.Key] = Qt.Key.Key_U

# --- Search / table behaviour -----------------------------------------------------
SEARCH_TERM_SEPARATOR: Final[str] = "*"
NO_SELECTION: Final[int] = -1
UNSORTED_COLUMN: Final[int] = -1
HEADER_WIDTH_PADDING_PX: Final[int] = 10
MIN_COLUMN_WIDTH_PX: Final[int] = 15  # javax.swing.table.TableColumn default minWidth
LAYOUT_MARGIN_PX: Final[int] = 0  # BorderLayout / GridLayout default gaps are 0
LAYOUT_SPACING_PX: Final[int] = 0
INPUT_LABEL_GRID_COLUMN: Final[int] = 0
INPUT_FIELD_GRID_COLUMN: Final[int] = 1
INPUT_GRID_COLUMN_STRETCH: Final[int] = 1  # equal stretch == GridLayout's equal cells
TABLE_STRETCH: Final[int] = 1

# --- Autocomplete (directories resolve against the CWD, like DEFAULT_CSV_PATH) -----
SYMBOLS_DIR: Final[str] = "../symbols"
FOOTPRINTS_DIR: Final[str] = "../footprints"
COMPLETION_SOURCES: Final[tuple[tuple[str, str], ...]] = (
    ("Library Ref", SYMBOLS_DIR),
    ("Footprint Ref", FOOTPRINTS_DIR),
)
COMPLETION_USE_FILE_STEM: Final[bool] = True  # "LM317.SchLib" completes as "LM317"
COMPLETION_CASE_SENSITIVITY: Final[Qt.CaseSensitivity] = Qt.CaseSensitivity.CaseInsensitive
COMPLETION_FILTER_MODE: Final[Qt.MatchFlag] = Qt.MatchFlag.MatchContains
COMPLETION_MODE: Final[QCompleter.CompletionMode] = QCompleter.CompletionMode.PopupCompletion
COMPLETION_MAX_VISIBLE_ITEMS: Final[int] = 15
LOG_COMPLETION_DIR_MISSING: Final[str] = "Autocomplete directory not found: {path}"
# Columns whose suggestions are the distinct values already present in that column.
COLUMN_VALUE_COMPLETION_COLUMNS: Final[tuple[str, ...]] = ("Manufacturer 1",)
COMPLETION_REFRESH_DELAY_MS: Final[int] = 0  # coalesce bursts of edits into one rebuild

# --- CSV I/O (Apache Commons CSV CSVFormat.DEFAULT semantics) ---------------------
CSV_ENCODING: Final[str] = "utf-8"  # Java 18+ FileReader/FileWriter default (JEP 400)
CSV_DECODE_ERRORS: Final[str] = "replace"  # Java decoders substitute U+FFFD
CSV_ENCODE_ERRORS: Final[str] = "replace"  # Java encoders substitute '?'
CSV_READ_CHUNK_CHARS: Final[int] = 64 * 1024
CSV_DELIMITER: Final[str] = ","
CSV_QUOTE: Final[str] = '"'
CSV_CR: Final[str] = "\r"
CSV_LF: Final[str] = "\n"
CSV_RECORD_SEPARATOR: Final[str] = CSV_CR + CSV_LF
CSV_MINIMAL_QUOTE_LEADING_MAX: Final[str] = "#"  # quote if first char <= '#'
CSV_MINIMAL_QUOTE_TRAILING_MAX: Final[str] = " "  # quote if last char <= ' '
CSV_ERR_INVALID_AFTER_QUOTE: Final[str] = "(line {line}) invalid char between encapsulated token and delimiter"
CSV_ERR_EOF_IN_QUOTE: Final[str] = "(startline {line}) EOF reached before encapsulated token finished"
CSV_ERR_MISSING_HEADER: Final[str] = "A header name is missing in {header}"
CSV_ERR_HEADER_INDEX: Final[str] = "Index for header '{name}' is {index} but CSVRecord only has {count} values!"
CSV_ERR_UNCHECKED: Final[str] = "IOException reading next record: java.io.IOException: {error}"
CSV_RECORD_REPR: Final[str] = "CSVRecord [comment='{comment}', recordNumber={number}, values={values}]"

# --- java.lang emulation ------------------------------------------------------------
JAVA_NULL_TEXT: Final[str] = "null"
JAVA_ARRAY_OPEN: Final[str] = "["
JAVA_ARRAY_CLOSE: Final[str] = "]"
JAVA_ARRAY_SEPARATOR: Final[str] = ", "
JAVA_TRIM_MAX: Final[str] = " "  # String.trim() strips every char <= U+0020
JAVA_ROUND_HALF: Final[float] = 0.5
JAVA_WHITESPACE_CONTROLS: Final[frozenset[str]] = frozenset("\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f")
JAVA_WHITESPACE_CATEGORIES: Final[frozenset[str]] = frozenset({"Zs", "Zl", "Zp"})
JAVA_NON_BREAKING_SPACES: Final[frozenset[str]] = frozenset({"\u00a0", "\u2007", "\u202f"})

# =============================================================================
# java.lang / Swing EDT emulation helpers
# =============================================================================

P = ParamSpec("P")
R = TypeVar("R")


class JavaParityError(RuntimeError):
    """A runtime exception the Java original throws at this point (logged, never shown)."""


def print_uncaught_exception(
    exc_type: type[BaseException], exc_value: BaseException, exc_traceback: TracebackType | None
) -> None:
    """``sys.excepthook`` mirroring the Swing EDT: print the stack trace and keep running."""
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)


def edt_guard(func: Callable[P, R]) -> Callable[P, R | None]:
    """Wrap a UI entry point so an exception is logged like an EDT crash instead of killing the app."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
        try:
            return func(*args, **kwargs)
        except Exception:  # noqa: BLE001 - deliberate: EDT semantics
            traceback.print_exc(file=sys.stderr)
            return None

    return wrapper


def java_split_literal(text: str, separator: str) -> list[str]:
    """``String.split`` for a single literal char: trailing empty strings are removed,
    and a string without the separator yields ``[text]`` (even when ``text`` is empty)."""
    if separator not in text:
        return [text]
    parts = text.split(separator)
    while parts and not parts[-1]:
        parts.pop()
    return parts


def java_is_blank(value: str) -> bool:
    """``value.trim().isEmpty()``."""
    return all(char <= JAVA_TRIM_MAX for char in value)


def java_is_whitespace(char: str) -> bool:
    """``Character.isWhitespace(char)``."""
    if char in JAVA_WHITESPACE_CONTROLS:
        return True
    return unicodedata.category(char) in JAVA_WHITESPACE_CATEGORIES and char not in JAVA_NON_BREAKING_SPACES


def java_array_to_string(values: Sequence[str]) -> str:
    """``Arrays.toString(String[])``."""
    return JAVA_ARRAY_OPEN + JAVA_ARRAY_SEPARATOR.join(values) + JAVA_ARRAY_CLOSE


def java_round(value: float) -> int:
    """``Math.round`` (half-up), unlike Python's banker's rounding."""
    return math.floor(value + JAVA_ROUND_HALF)


def java_io_message(error: OSError) -> str:
    """Approximate ``IOException.getMessage()`` for an ``OSError``."""
    if error.filename is not None and error.strerror:
        return JAVA_IO_ERROR_MESSAGE.format(path=error.filename, reason=error.strerror)
    return str(error)


# =============================================================================
# Apache Commons CSV (CSVFormat.DEFAULT) port: no Qt dependency, unit-testable
# =============================================================================


class CsvFormatError(OSError):
    """Lexer error; an ``IOException`` in Commons CSV."""


class CsvUncheckedIOError(RuntimeError):
    """Error while iterating records; an ``UncheckedIOException`` in Commons CSV."""


class _Sentinel(enum.Enum):
    END_OF_STREAM = enum.auto()
    UNDEFINED = enum.auto()


_Char = str | _Sentinel
_ReadChar = str | Literal[_Sentinel.END_OF_STREAM]


class _TokenType(enum.Enum):
    INVALID = enum.auto()
    TOKEN = enum.auto()
    EORECORD = enum.auto()
    EOF = enum.auto()


@dataclass
class _Token:
    type: _TokenType = _TokenType.INVALID
    content: list[str] = field(default_factory=list)
    is_ready: bool = False


class _ExtendedReader:
    """``ExtendedBufferedReader``: char reader with one-char look-ahead and line counting."""

    def __init__(self, source: TextIO, chunk_chars: int) -> None:
        self._source = source
        self._chunk_chars = chunk_chars
        self._buffer = ""
        self._position = 0
        self._eol_counter = 0
        self.last_char: _Char = _Sentinel.UNDEFINED

    def _has_data(self) -> bool:
        if self._position < len(self._buffer):
            return True
        self._buffer = self._source.read(self._chunk_chars)
        self._position = 0
        return bool(self._buffer)

    def look_ahead(self) -> _ReadChar:
        return self._buffer[self._position] if self._has_data() else _Sentinel.END_OF_STREAM

    def read(self) -> _ReadChar:
        current = self.look_ahead()
        if current is not _Sentinel.END_OF_STREAM:
            self._position += 1
        last = self.last_char
        if (
            current == CSV_CR
            or (current == CSV_LF and last != CSV_CR)
            or (current is _Sentinel.END_OF_STREAM and last not in (CSV_CR, CSV_LF, _Sentinel.END_OF_STREAM))
        ):
            self._eol_counter += 1
        self.last_char = current
        return current

    def current_line_number(self) -> int:
        if self.last_char in (CSV_CR, CSV_LF, _Sentinel.UNDEFINED, _Sentinel.END_OF_STREAM):
            return self._eol_counter
        return self._eol_counter + 1


class _DefaultFormatLexer:
    """Commons CSV ``Lexer`` specialised for DEFAULT: ',' delimiter, '"' quote,
    no escape, no comments, empty lines ignored, no trimming."""

    def __init__(self, reader: _ExtendedReader) -> None:
        self._reader = reader
        self._last_token_was_delimiter = False

    def _is_delimiter(self, char: _Char) -> bool:
        self._last_token_was_delimiter = char == CSV_DELIMITER
        return self._last_token_was_delimiter

    def _read_end_of_line(self, char: _Char) -> bool:
        if char == CSV_CR and self._reader.look_ahead() == CSV_LF:
            char = self._reader.read()
        return char in (CSV_CR, CSV_LF)

    @staticmethod
    def _is_start_of_line(char: _Char) -> bool:
        return char in (CSV_CR, CSV_LF, _Sentinel.UNDEFINED)

    def next_token(self) -> _Token:
        token = _Token()
        last_char = self._reader.last_char
        char = self._reader.read()
        eol = self._read_end_of_line(char)

        while eol and self._is_start_of_line(last_char):  # skip empty lines
            last_char = char
            char = self._reader.read()
            eol = self._read_end_of_line(char)
            if char is _Sentinel.END_OF_STREAM:
                token.type = _TokenType.EOF
                return token

        if last_char is _Sentinel.END_OF_STREAM or (
            not self._last_token_was_delimiter and char is _Sentinel.END_OF_STREAM
        ):
            token.type = _TokenType.EOF
            return token

        if self._is_delimiter(char):
            token.type = _TokenType.TOKEN
        elif eol:
            token.type = _TokenType.EORECORD
        elif char == CSV_QUOTE:
            self._parse_encapsulated_token(token)
        elif char is _Sentinel.END_OF_STREAM:
            token.type = _TokenType.EOF
            token.is_ready = True
        else:
            self._parse_simple_token(token, char)
        return token

    def _parse_simple_token(self, token: _Token, char: _ReadChar) -> None:
        while True:
            if self._read_end_of_line(char):
                token.type = _TokenType.EORECORD
                return
            if char is _Sentinel.END_OF_STREAM:
                token.type = _TokenType.EOF
                token.is_ready = True
                return
            if self._is_delimiter(char):
                token.type = _TokenType.TOKEN
                return
            token.content.append(char)
            char = self._reader.read()

    def _parse_encapsulated_token(self, token: _Token) -> None:
        start_line = self._reader.current_line_number()
        while True:
            char = self._reader.read()
            if char is _Sentinel.END_OF_STREAM:
                raise CsvFormatError(CSV_ERR_EOF_IN_QUOTE.format(line=start_line))
            if char != CSV_QUOTE:
                token.content.append(char)
                continue
            if self._reader.look_ahead() == CSV_QUOTE:  # escaped "" -> "
                token.content.append(CSV_QUOTE)
                self._reader.read()
                continue
            while True:  # closing quote: only whitespace may precede the delimiter
                char = self._reader.read()
                if self._is_delimiter(char):
                    token.type = _TokenType.TOKEN
                    return
                if char is _Sentinel.END_OF_STREAM:
                    token.type = _TokenType.EOF
                    token.is_ready = True
                    return
                if self._read_end_of_line(char):
                    token.type = _TokenType.EORECORD
                    return
                if not java_is_whitespace(char):
                    raise CsvFormatError(CSV_ERR_INVALID_AFTER_QUOTE.format(line=self._reader.current_line_number()))


@dataclass(frozen=True)
class CsvRecord:
    """``CSVRecord``: one parsed row plus its 1-based record number (the header is not counted)."""

    values: tuple[str, ...]
    record_number: int

    def get(self, name: str, header_map: Mapping[str, int]) -> str:
        """``CSVRecord.get(String)``; raises ``ValueError`` (IllegalArgumentException) on short rows."""
        index = header_map[name]
        if index >= len(self.values):
            raise ValueError(CSV_ERR_HEADER_INDEX.format(name=name, index=index, count=len(self.values)))
        return self.values[index]

    def __str__(self) -> str:
        return CSV_RECORD_REPR.format(
            comment=JAVA_NULL_TEXT, number=self.record_number, values=java_array_to_string(self.values)
        )


class CommonsCsvParser:
    """``new CSVParser(reader, DEFAULT.builder().setHeader().build())``.

    The constructor consumes the first record as the header (raising ``CsvFormatError``
    or ``ValueError`` exactly where Java's constructor throws); iteration yields data
    records and wraps lexer/IO failures in ``CsvUncheckedIOError``.
    """

    def __init__(self, source: TextIO, chunk_chars: int = CSV_READ_CHUNK_CHARS) -> None:
        self._lexer = _DefaultFormatLexer(_ExtendedReader(source, chunk_chars))
        self._record_number = 0
        self.header_map: dict[str, int] = self._create_header_map()
        self._record_number = 0  # the constructor restarts numbering: first data record is #1

    def _create_header_map(self) -> dict[str, int]:
        header_map: dict[str, int] = {}
        header = self._next_record()
        if header is None:
            return header_map
        for index, name in enumerate(header.values):
            if java_is_blank(name):
                raise ValueError(CSV_ERR_MISSING_HEADER.format(header=java_array_to_string(header.values)))
            header_map[name] = index  # duplicates: later index wins, first position kept (LinkedHashMap)
        return header_map

    def _next_record(self) -> CsvRecord | None:
        values: list[str] = []
        while True:
            token = self._lexer.next_token()
            if token.type is _TokenType.TOKEN:
                values.append("".join(token.content))
                continue
            if token.type is _TokenType.EORECORD or token.is_ready:
                values.append("".join(token.content))
            break
        if not values:
            return None
        self._record_number += 1
        return CsvRecord(tuple(values), self._record_number)

    def __iter__(self) -> Iterator[CsvRecord]:
        while True:
            try:
                record = self._next_record()
            except OSError as error:
                raise CsvUncheckedIOError(CSV_ERR_UNCHECKED.format(error=error)) from error
            if record is None:
                return
            yield record


def _requires_quotes(value: str, is_first_in_record: bool) -> bool:
    """``CSVFormat.printWithQuotes`` with ``QuoteMode.MINIMAL``."""
    if not value:
        return is_first_in_record
    if value[0] <= CSV_MINIMAL_QUOTE_LEADING_MAX:
        return True
    if any(char in (CSV_CR, CSV_LF, CSV_QUOTE, CSV_DELIMITER) for char in value):
        return True
    return value[-1] <= CSV_MINIMAL_QUOTE_TRAILING_MAX


def format_csv_record(values: Sequence[str]) -> str:
    """One ``CSVPrinter.printRecord`` line in ``CSVFormat.DEFAULT`` (CRLF-terminated)."""
    fields = (
        CSV_QUOTE + value.replace(CSV_QUOTE, CSV_QUOTE * 2) + CSV_QUOTE
        if _requires_quotes(value, index == 0)
        else value
        for index, value in enumerate(values)
    )
    return CSV_DELIMITER.join(fields) + CSV_RECORD_SEPARATOR


# =============================================================================
# Qt models (DefaultTableModel / TableRowSorter equivalents)
# =============================================================================

Cell = str | None  # None mirrors the nulls DefaultTableModel pads short rows with
_ModelIndex = QModelIndex | QPersistentModelIndex


class CsvTableModel(QAbstractTableModel):
    """``DefaultTableModel`` with a fixed column set; every cell is editable."""

    def __init__(self, column_names: Sequence[str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._column_names: tuple[str, ...] = tuple(column_names)
        self._rows: list[list[Cell]] = []

    # --- Qt interface -----------------------------------------------------------
    def rowCount(self, parent: _ModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: _ModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._column_names)

    def data(self, index: _ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        value = self._rows[index.row()][index.column()]
        return "" if value is None else value  # JTable renders null as an empty cell

    def setData(self, index: _ModelIndex, value: object, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        self.set_value_at(index.row(), index.column(), str(value))
        return True

    def flags(self, index: _ModelIndex) -> Qt.ItemFlag:
        return super().flags(index) | Qt.ItemFlag.ItemIsEditable

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._column_names[section]
        if role == Qt.ItemDataRole.InitialSortOrderRole:
            return Qt.SortOrder.AscendingOrder  # TableRowSorter's first click sorts ascending
        return None

    # --- DefaultTableModel-style API ----------------------------------------------
    @property
    def column_names(self) -> tuple[str, ...]:
        return self._column_names

    def clear(self) -> None:
        """``setRowCount(0)``."""
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()

    def append_rows(self, rows: Sequence[Sequence[Cell]]) -> None:
        """``addRow`` for each row: truncated / null-padded to the column count."""
        if not rows:
            return
        first = len(self._rows)
        width = len(self._column_names)
        self.beginInsertRows(QModelIndex(), first, first + len(rows) - 1)
        self._rows.extend([*row[:width], *([None] * (width - len(row)))] for row in rows)
        self.endInsertRows()

    def value_at(self, row: int, column: int) -> Cell:
        return self._rows[row][column]

    def set_value_at(self, row: int, column: int, value: str) -> None:
        self._rows[row][column] = value
        index = self.index(row, column)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])

    def column_values(self, column: int) -> Iterator[Cell]:
        return (row[column] for row in self._rows)

    def iter_rows(self) -> Iterator[tuple[Cell, ...]]:
        return (tuple(row) for row in self._rows)


class SearchFilterProxyModel(QSortFilterProxyModel):
    """``TableRowSorter`` + the anonymous ``RowFilter`` from ``searchDatabase``.

    Dynamic re-filtering is off: Swing's sorter does not re-filter on cell edits
    (``sortsOnUpdates == false``) but does a full re-sort/re-filter on insertions,
    which the window reproduces by calling ``invalidate()`` after appending rows.
    """

    def __init__(self, source: CsvTableModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._source = source
        self._terms: tuple[str, ...] = ("",)
        self._pinned_rows: set[int] = set()
        self.setSourceModel(source)
        source.modelReset.connect(self._pinned_rows.clear)  # a reload invalidates row numbers
        self.setDynamicSortFilter(False)
        self.setSortLocaleAware(True)  # TableRowSorter compares via java.text.Collator
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)

    def set_search_terms(self, terms: Sequence[str]) -> None:
        if not terms:
            raise ValueError(ERR_EMPTY_SEARCH_TERMS)
        self._terms = tuple(terms)
        self._pinned_rows.clear()  # a new search shows only real matches again
        self.invalidate()

    def pin_source_row(self, source_row: int) -> None:
        """Keep ``source_row`` visible under the current search until it changes."""
        self._pinned_rows.add(source_row)

    def filterAcceptsRow(self, source_row: int, _source_parent: _ModelIndex) -> bool:  # noqa: N802
        # JAVA PARITY: `searchText[0] == ""` is a reference comparison that is true
        # only for a leading '*' (split yields the interned ""), so "*foo" shows
        # every row. A completely empty query also shows every row, since every
        # cell contains "".
        if not self._terms[0] or source_row in self._pinned_rows:
            return True
        cells = [
            (self._source.value_at(source_row, column) or "").lower() for column in range(self._source.columnCount())
        ]
        return all(any(term in cell for cell in cells) for term in self._terms)


# =============================================================================
# Widgets / behaviour helpers
# =============================================================================


def distribute_column_widths(preferred: Sequence[int], available: int, minimum: int) -> list[int]:
    """Approximate ``JTable.AUTO_RESIZE_SUBSEQUENT_COLUMNS``: spread the difference between
    the viewport width and the preferred widths over all columns (equally when growing,
    because maxWidth is Integer.MAX_VALUE; proportionally to ``pref - minWidth`` when shrinking)."""
    total = sum(preferred)
    delta = available - total
    weights = [1] * len(preferred) if delta >= 0 else [max(width - minimum, 0) for width in preferred]
    remaining_weight = sum(weights)
    if remaining_weight == 0:
        return list(preferred)
    widths: list[int] = []
    for width, weight in zip(preferred, weights, strict=True):
        share = java_round(delta * weight / remaining_weight) if remaining_weight else 0
        widths.append(max(width + share, minimum))
        delta -= share
        remaining_weight -= weight
    return widths


class JTableColumnFitter(QObject):
    """Keeps columns filling the viewport like a JTable in its default auto-resize mode."""

    def __init__(self, table: QTableView, preferred_widths: Sequence[int], minimum_width: int) -> None:
        super().__init__(table)
        self._table = table
        self._preferred = list(preferred_widths)
        self._minimum = minimum_width
        self._applying = False
        table.viewport().installEventFilter(self)
        table.horizontalHeader().sectionResized.connect(self._on_section_resized)

    def eventFilter(self, _watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Resize:
            self.fit()
        return False

    def _on_section_resized(self, index: int, _old_size: int, new_size: int) -> None:
        if not self._applying:  # a user drag becomes the new preferred width, as in Swing
            self._preferred[index] = new_size

    def fit(self) -> None:
        widths = distribute_column_widths(self._preferred, self._table.viewport().width(), self._minimum)
        header = self._table.horizontalHeader()
        self._applying = True
        try:
            for index, width in enumerate(widths):
                header.resizeSection(index, width)
        finally:
            self._applying = False


class WindowKeyBindings(QObject):
    """Swing ``WHEN_IN_FOCUSED_WINDOW`` bindings for one window.

    Implemented as an application event filter rather than ``QShortcut`` because the
    Swing bindings take priority over the focused component, whereas Qt lets e.g. a
    ``QLineEdit`` claim Ctrl+U (delete line on X11) before a shortcut fires.
    """

    def __init__(self, window: QWidget, bindings: Mapping[QKeyCombination, Callable[[], object]]) -> None:
        super().__init__(window)
        self._window = window
        self._bindings: dict[int, Callable[[], object]] = {
            combination.toCombined(): action for combination, action in bindings.items()
        }

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        event_type = event.type()
        if event_type not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            return False
        if not isinstance(watched, QWidget) or watched.window() is not self._window:
            return False
        if not isinstance(event, QKeyEvent):
            return False
        action = self._bindings.get(event.keyCombination().toCombined())
        if action is None:
            return False
        if event_type == QEvent.Type.ShortcutOverride:
            event.accept()  # deliver as a key press so it reaches this filter, not a widget shortcut
            return True
        action()
        return True


class CompletionSource(QObject):
    """A live list of suggestions shared by every completer created from it."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.model = QStringListModel(self)

    def create_completer(self, parent: QObject) -> QCompleter:
        completer = QCompleter(self.model, parent)
        completer.setCaseSensitivity(COMPLETION_CASE_SENSITIVITY)
        completer.setFilterMode(COMPLETION_FILTER_MODE)
        completer.setCompletionMode(COMPLETION_MODE)
        completer.setMaxVisibleItems(COMPLETION_MAX_VISIBLE_ITEMS)
        return completer

    def _set_suggestions(self, values: set[str]) -> None:
        suggestions = sorted(values, key=str.casefold)
        if suggestions != self.model.stringList():
            self.model.setStringList(suggestions)


class FileNameCompletionSource(CompletionSource):
    """Completion list built from the file names in one directory, kept current with a
    ``QFileSystemWatcher`` so newly added symbol/footprint files show up without a restart."""

    def __init__(self, directory: Path, use_file_stem: bool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._directory = directory
        self._use_file_stem = use_file_stem
        self._missing_reported = False
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self.refresh()

    def _on_directory_changed(self, _path: str) -> None:
        self.refresh()

    def refresh(self) -> None:
        if not self._directory.is_dir():
            if not self._missing_reported:
                print(LOG_COMPLETION_DIR_MISSING.format(path=self._directory), file=sys.stderr)
                self._missing_reported = True
            self._set_suggestions(set())
            return
        self._missing_reported = False
        directory_key = str(self._directory)
        if directory_key not in self._watcher.directories():
            self._watcher.addPath(directory_key)
        names = {
            entry.stem if self._use_file_stem else entry.name for entry in self._directory.iterdir() if entry.is_file()
        }
        self._set_suggestions(names)


class ColumnValuesCompletionSource(CompletionSource):
    """Suggests the distinct non-blank values already present in one table column
    (all rows, including ones hidden by the search). Rebuilt after loads, added rows
    and edits; a burst of changes such as Update Row's 12 cell writes is coalesced."""

    def __init__(self, table_model: CsvTableModel, column: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._table_model = table_model
        self._column = column
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(COMPLETION_REFRESH_DELAY_MS)
        self._refresh_timer.timeout.connect(self.refresh)
        table_model.modelReset.connect(self._schedule_refresh)
        table_model.rowsInserted.connect(self._schedule_refresh)
        table_model.rowsRemoved.connect(self._schedule_refresh)
        table_model.dataChanged.connect(self._on_data_changed)
        self.refresh()

    def _schedule_refresh(self, *_signal_args: object) -> None:
        self._refresh_timer.start()

    def _on_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, *_signal_args: object) -> None:
        if top_left.column() <= self._column <= bottom_right.column():
            self._schedule_refresh()

    def refresh(self) -> None:
        self._set_suggestions(
            {value for value in self._table_model.column_values(self._column) if value is not None and value.strip()}
        )


class CompletingItemDelegate(QStyledItemDelegate):
    """Attaches the matching completer to in-table cell editors, so editing a cell
    directly offers the same suggestions as the input fields."""

    def __init__(self, sources: Mapping[int, CompletionSource], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sources = dict(sources)

    def createEditor(  # noqa: N802
        self, parent: QWidget, option: QStyleOptionViewItem, index: _ModelIndex
    ) -> QWidget:
        editor = super().createEditor(parent, option, index)
        source = self._sources.get(index.column())
        if source is not None and isinstance(editor, QLineEdit):
            editor.setCompleter(source.create_completer(editor))
        return editor


# =============================================================================
# Main window (CSVGuiApp)
# =============================================================================


class CsvGuiApp(QMainWindow):
    """The CSV Manager window."""

    def __init__(self, column_names: Sequence[str] = COLUMN_NAMES, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._column_names: tuple[str, ...] = tuple(column_names)
        self._current_file_name: str = ""
        self.setWindowTitle(APP_WINDOW_TITLE)

        self._model = CsvTableModel(self._column_names, self)
        self._proxy = SearchFilterProxyModel(self._model, self)
        self._table = self._build_table()
        self._search_field = QLineEdit()
        self._input_fields: list[QLineEdit] = [QLineEdit() for _ in self._column_names]
        self._add_button = QPushButton(ADD_ROW_BUTTON_TEXT)
        self._update_button = QPushButton(UPDATE_ROW_BUTTON_TEXT)
        self._column_fitter: JTableColumnFitter | None = None
        # Input-field contents as last loaded from a row (or empty at startup); the
        # fields count as "modified" when they differ from this snapshot.
        self._field_snapshot: tuple[str, ...] = self._input_texts()

        self._completion_sources = self._build_completion_sources()
        self._table.setItemDelegate(CompletingItemDelegate(self._completion_sources, self._table))

        self._build_layout()
        self._build_menu()
        self._key_bindings = WindowKeyBindings(
            self,
            {
                QKeyCombination(SHORTCUT_MODIFIER, KEY_OPEN_CSV): self._on_open_csv,
                QKeyCombination(SHORTCUT_MODIFIER, KEY_SAVE_CSV): self._on_save_csv,
                QKeyCombination(SHORTCUT_MODIFIER, KEY_ADD_ROW): self._on_add_row,
                QKeyCombination(SHORTCUT_MODIFIER, KEY_UPDATE_ROW): self._on_update_row,
            },
        )
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._key_bindings)

        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._search_field.textChanged.connect(self._on_search_text_changed)
        self._add_button.clicked.connect(self._on_add_row)
        self._update_button.clicked.connect(self._on_update_row)

    # --- construction -------------------------------------------------------------
    def _build_table(self) -> QTableView:
        table = QTableView()
        table.setModel(self._proxy)
        table.verticalHeader().hide()  # JTable has no row header
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # "JTable.autoStartsEdit" = false: typing never starts an edit; double-click / F2 still do.
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(MIN_COLUMN_WIDTH_PX)
        header.setSortIndicator(UNSORTED_COLUMN, Qt.SortOrder.AscendingOrder)
        table.setSortingEnabled(True)  # header clicks sort, as with a TableRowSorter
        return table

    def _build_completion_sources(self) -> dict[int, CompletionSource]:
        sources: dict[int, CompletionSource] = {}
        for column_name, directory in COMPLETION_SOURCES:
            if column_name in self._column_names:
                column = self._column_names.index(column_name)
                sources[column] = FileNameCompletionSource(Path(directory), COMPLETION_USE_FILE_STEM, self)
        for column_name in COLUMN_VALUE_COMPLETION_COLUMNS:
            if column_name in self._column_names:
                column = self._column_names.index(column_name)
                sources[column] = ColumnValuesCompletionSource(self._model, column, self)
        for column, source in sources.items():
            line_edit = self._input_fields[column]
            line_edit.setCompleter(source.create_completer(line_edit))
        return sources

    def _build_layout(self) -> None:
        search_panel = QHBoxLayout()
        search_panel.setContentsMargins(LAYOUT_MARGIN_PX, LAYOUT_MARGIN_PX, LAYOUT_MARGIN_PX, LAYOUT_MARGIN_PX)
        search_panel.setSpacing(LAYOUT_SPACING_PX)
        search_panel.addWidget(QLabel(SEARCH_LABEL_TEXT))
        search_panel.addWidget(self._search_field)

        input_panel = QGridLayout()
        input_panel.setContentsMargins(LAYOUT_MARGIN_PX, LAYOUT_MARGIN_PX, LAYOUT_MARGIN_PX, LAYOUT_MARGIN_PX)
        input_panel.setSpacing(LAYOUT_SPACING_PX)
        cells: list[tuple[QWidget, QWidget]] = [
            (QLabel(name + INPUT_LABEL_SUFFIX), line_edit)
            for name, line_edit in zip(self._column_names, self._input_fields, strict=True)
        ]
        cells.append((self._add_button, self._update_button))
        for row, (left, right) in enumerate(cells):
            for widget, column in ((left, INPUT_LABEL_GRID_COLUMN), (right, INPUT_FIELD_GRID_COLUMN)):
                policy = widget.sizePolicy()
                policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)  # equal-width cells like GridLayout
                widget.setSizePolicy(policy)
                input_panel.addWidget(widget, row, column)
        input_panel.setColumnStretch(INPUT_LABEL_GRID_COLUMN, INPUT_GRID_COLUMN_STRETCH)
        input_panel.setColumnStretch(INPUT_FIELD_GRID_COLUMN, INPUT_GRID_COLUMN_STRETCH)

        root = QVBoxLayout()
        root.setContentsMargins(LAYOUT_MARGIN_PX, LAYOUT_MARGIN_PX, LAYOUT_MARGIN_PX, LAYOUT_MARGIN_PX)
        root.setSpacing(LAYOUT_SPACING_PX)
        root.addLayout(search_panel)
        root.addWidget(self._table, TABLE_STRETCH)
        root.addLayout(input_panel)

        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu(FILE_MENU_TITLE)
        open_action = QAction(OPEN_MENU_ITEM_TEXT, self)
        save_action = QAction(SAVE_MENU_ITEM_TEXT, self)
        open_action.triggered.connect(self._on_open_csv)
        save_action.triggered.connect(self._on_save_csv)
        file_menu.addAction(open_action)
        file_menu.addAction(save_action)

    def initialize_after_show(self, startup_csv_path: str = DEFAULT_CSV_PATH) -> None:
        """Tail of the Java constructor, run once the window is visible."""
        self.open_csv_path(startup_csv_path)
        self.adjust_column_widths()
        self.search_database()

    # --- UI entry points (exceptions are logged, as on the Swing EDT) ------------------
    @edt_guard
    def _on_open_csv(self, *_signal_args: object) -> None:
        self.open_csv_with_dialog()

    @edt_guard
    def _on_save_csv(self, *_signal_args: object) -> None:
        self.save_csv()

    @edt_guard
    def _on_add_row(self, *_signal_args: object) -> None:
        self.add_row()

    @edt_guard
    def _on_update_row(self, *_signal_args: object) -> None:
        self.update_row()

    @edt_guard
    def _on_search_text_changed(self, *_signal_args: object) -> None:
        self.search_database()

    @edt_guard
    def _on_selection_changed(self, *_signal_args: object) -> None:
        self.update_text_fields()

    # --- helpers -----------------------------------------------------------------------
    def _show_message(self, text: str) -> None:
        QMessageBox.information(self, MESSAGE_DIALOG_TITLE, text)

    def _selected_view_row(self) -> int:
        """``JTable.getSelectedRow()``: lowest selected view row, or -1."""
        selection = self._table.selectionModel().selection()
        return min((selection.at(i).top() for i in range(selection.count())), default=NO_SELECTION)

    def _view_to_model_row(self, view_row: int) -> int:
        return self._proxy.mapToSource(self._proxy.index(view_row, 0)).row()

    # --- behaviour (method names follow the Java original) ---------------------------------
    def adjust_column_widths(self) -> None:
        header = self._table.horizontalHeader()
        metrics = header.fontMetrics()
        preferred = [metrics.horizontalAdvance(name) + HEADER_WIDTH_PADDING_PX for name in self._column_names]
        if self._column_fitter is None:
            self._column_fitter = JTableColumnFitter(self._table, preferred, MIN_COLUMN_WIDTH_PX)
        self._column_fitter.fit()

    def _input_texts(self) -> tuple[str, ...]:
        return tuple(line_edit.text() for line_edit in self._input_fields)

    def _fields_modified(self) -> bool:
        """True when the user has changed the input fields since they were last loaded."""
        return self._input_texts() != self._field_snapshot

    def _mark_fields_clean(self) -> None:
        self._field_snapshot = self._input_texts()

    def update_text_fields(self) -> None:
        view_row = self._selected_view_row()
        if view_row == NO_SELECTION:
            return
        model_row = self._view_to_model_row(view_row)
        try:
            for column, line_edit in enumerate(self._input_fields):
                value = self._model.value_at(model_row, column)
                if value is None:  # JAVA PARITY: null.toString() -> NPE, remaining fields untouched
                    raise JavaParityError(ERR_NULL_CELL)
                line_edit.setText(value)
        finally:
            self._mark_fields_clean()

    def open_csv_with_dialog(self) -> bool:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, OPEN_DIALOG_TITLE, OPEN_DIALOG_START_DIR, OPEN_DIALOG_FILTER
        )
        if not path:
            return False  # user cancelled
        # JAVA PARITY: the dialog path does NOT update the current file name, so a later
        # save still overwrites the startup file. See review item 1.
        return self._load_csv_file(path)

    def open_csv_path(self, file_name: str) -> bool:
        if not Path(file_name).is_file():
            self._show_message(MSG_FILE_NOT_FOUND.format(path=file_name))
            return False
        if self._load_csv_file(file_name):
            self._current_file_name = file_name
            return True
        return False

    def _load_csv_file(self, path: str) -> bool:
        if not Path(path).is_file():
            self._show_message(MSG_INVALID_FILE)
            return False

        self._model.clear()  # JAVA PARITY: cleared before parsing, so a failed load empties the table
        loaded: list[list[Cell]] = []
        try:
            try:
                with Path(path).open(encoding=CSV_ENCODING, errors=CSV_DECODE_ERRORS, newline="") as handle:
                    parser = CommonsCsvParser(handle)
                    header_map = parser.header_map
                    if not header_map:
                        self._show_message(MSG_NO_HEADERS)
                        return False
                    for record in parser:
                        try:
                            loaded.append([record.get(name, header_map) for name in header_map])
                        except ValueError as row_error:
                            print(LOG_ROW_ERROR.format(record=record, error=row_error), file=sys.stderr)
            finally:
                # Rows parsed before a failure stay in the table, as with Java's per-row addRow.
                self._model.append_rows(loaded)
                self._proxy.invalidate()
        except OSError as error:
            self._show_message(MSG_READ_ERROR.format(error=java_io_message(error)))
            return False
        except Exception as error:  # noqa: BLE001 - mirrors Java's catch (Exception e)
            self._show_message(MSG_UNEXPECTED_ERROR.format(error=error))
            return False
        return True

    def save_csv(self) -> None:
        path = self._current_file_name
        if not Path(path).is_file():
            self._show_message(MSG_FILE_NOT_FOUND.format(path=path))
            return
        try:
            with Path(path).open("w", encoding=CSV_ENCODING, errors=CSV_ENCODE_ERRORS, newline="") as handle:
                handle.write(format_csv_record(self._model.column_names))
                handle.writelines(  # model order: hidden/filtered rows are saved too
                    format_csv_record(["" if cell is None else cell for cell in row]) for row in self._model.iter_rows()
                )
                # JAVA PARITY: success is reported before the writer is flushed/closed.
                self._show_message(MSG_SAVE_SUCCESS.format(path=path))
        except OSError as error:
            self._show_message(MSG_SAVE_ERROR.format(error=java_io_message(error)))

    def search_database(self) -> None:
        terms = java_split_literal(self._search_field.text().lower(), SEARCH_TERM_SEPARATOR)
        if not terms:
            # JAVA PARITY: "*" / "**" make split() return an empty array and the filter
            # throws ArrayIndexOutOfBoundsException; the previous filter stays active.
            raise JavaParityError(ERR_EMPTY_SEARCH_TERMS)
        # Java installs a brand-new TableRowSorter: selection cleared, sort order reset.
        self._table.selectionModel().clear()
        self._table.horizontalHeader().setSortIndicator(UNSORTED_COLUMN, Qt.SortOrder.AscendingOrder)
        self._proxy.sort(UNSORTED_COLUMN)
        self._proxy.set_search_terms(terms)

    def add_row(self) -> None:
        """FIX (deviates from Java, which always added an empty row): if the input fields
        were modified since they were last loaded, the new row is created from them."""
        self._add_row(duplicate=self._fields_modified())

    def duplicate_row(self) -> None:
        """Add a row copied from the input fields regardless of whether they changed."""
        self._add_row(duplicate=True)

    def _add_row(self, duplicate: bool) -> None:
        row: list[Cell] = [line_edit.text() if duplicate else "" for line_edit in self._input_fields]
        self._model.append_rows([row])
        new_model_row = self._model.rowCount() - 1
        # FIX (deviates from Java, which used the model index as a view index and threw
        # "Row index out of range" whenever a search hid rows): pin the new row so the
        # active search cannot hide it, then map model -> view before selecting.
        self._proxy.pin_source_row(new_model_row)
        self._proxy.invalidate()  # DefaultRowSorter.rowsInserted -> full re-sort / re-filter
        index = self._proxy.mapFromSource(self._model.index(new_model_row, 0))
        # Explicit ClearAndSelect: QTableView.selectRow() would toggle while Ctrl is held (Ctrl+Q).
        self._table.selectionModel().setCurrentIndex(
            index, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
        )
        self._table.scrollTo(index)
        self._mark_fields_clean()  # the fields now mirror the newly selected row

    def update_row(self) -> None:
        view_row = self._selected_view_row()
        if view_row == NO_SELECTION:
            QMessageBox.warning(None, NO_ROW_SELECTED_TITLE, MSG_NO_ROW_SELECTED)  # parent null, as in Java
            return
        model_row = self._view_to_model_row(view_row)
        for column, line_edit in enumerate(self._input_fields):
            self._model.set_value_at(model_row, column, line_edit.text())
        self._mark_fields_clean()  # fields and row now agree


def main(argv: Sequence[str] | None = None) -> int:
    sys.excepthook = print_uncaught_exception
    app = QApplication(list(argv) if argv is not None else sys.argv)
    window = CsvGuiApp()
    window.showMaximized()
    window.initialize_after_show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())