"""Utilities for parsing newline-delimited JSON (NDJSON) request bodies.

NDJSON payloads contain one JSON document per line. Parsing them line by line
allows request bodies to be consumed lazily, so memory usage stays constant
regardless of how many records the body contains.
"""

from __future__ import annotations

import codecs
import typing

from marshmallow import ValidationError

__all__ = [
    "NDJSONError",
    "NDJSONResult",
    "iter_lines",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_MAX_LINE_LENGTH",
]

#: Default number of bytes requested from the stream per read
DEFAULT_CHUNK_SIZE: int = 8192
#: Default maximum length of a single line, in characters
DEFAULT_MAX_LINE_LENGTH: int = 1024 * 1024


class NDJSONError(ValidationError):
    """A `marshmallow.ValidationError` tied to a single line of an NDJSON payload.

    Carries the 1-based ``line`` number where the error occurred, in addition
    to the usual ``messages`` (which preserve field paths for schema
    validation errors).
    """

    def __init__(
        self,
        message: str | list | dict,
        *,
        line: int,
        **kwargs: typing.Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.line = line


class NDJSONResult(typing.NamedTuple):
    """The outcome of parsing a single line of an NDJSON payload."""

    #: 1-based number of the line which was parsed
    line: int
    #: the validated data, or `None` if the line failed to parse
    data: typing.Any
    #: the error for the line, or `None` if the line parsed successfully
    error: NDJSONError | None

    @property
    def ok(self) -> bool:
        """Whether the line parsed and validated successfully."""
        return self.error is None


def iter_lines(
    stream: typing.IO[bytes],
    *,
    max_line_length: int = DEFAULT_MAX_LINE_LENGTH,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> typing.Iterator[tuple[int, str | None, NDJSONError | None]]:
    """Lazily yield ``(line_number, text, error)`` triples from a binary stream.

    Reads at most ``chunk_size`` bytes at a time and decodes UTF-8
    incrementally, so multi-byte characters and newlines may span read
    chunks. Blank lines are skipped. A final line without a trailing newline
    is still yielded. Lines longer than ``max_line_length`` characters yield
    an `NDJSONError` in place of text and are discarded up to the next
    newline, so iteration can continue with the following line.
    """
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    line_number = 0
    # True while skipping the remainder of an over-long line
    discarding = False

    def take_lines() -> typing.Iterator[tuple[int, str | None, NDJSONError | None]]:
        nonlocal buffer, line_number, discarding
        while True:
            index = buffer.find("\n")
            if index == -1:
                break
            line, buffer = buffer[:index], buffer[index + 1 :]
            if discarding:
                # the over-long line was already counted when its error
                # was yielded; just skip to the next line
                discarding = False
                continue
            line_number += 1
            if line.endswith("\r"):
                line = line[:-1]
            if not line.strip():
                continue
            yield line_number, line, None
        if not discarding and len(buffer) > max_line_length:
            line_number += 1
            discarding = True
            buffer = ""
            yield line_number, None, NDJSONError(
                f"Line exceeds maximum length of {max_line_length} characters.",
                line=line_number,
            )

    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        try:
            buffer += decoder.decode(chunk)
        except UnicodeDecodeError as exc:
            line_number += 1
            yield line_number, None, NDJSONError(
                f"Bytes decoding error: {exc.reason}", line=line_number
            )
            return
        yield from take_lines()
    # flush any partial multi-byte character held by the incremental decoder
    try:
        buffer += decoder.decode(b"", final=True)
    except UnicodeDecodeError as exc:
        line_number += 1
        yield line_number, None, NDJSONError(
            f"Bytes decoding error: {exc.reason}", line=line_number
        )
        return
    yield from take_lines()
    if not discarding:
        line = buffer
        if line.endswith("\r"):
            line = line[:-1]
        if line.strip():
            line_number += 1
            yield line_number, line, None
