import contextlib
import json

import pytest
from marshmallow import Schema

from webargs import fields
from webargs.core import Parser
from webargs.ndjson import NDJSONError, NDJSONResult


class RecordSchema(Schema):
    name = fields.Str(required=True)
    age = fields.Int(required=True)


class ChunkedStream:
    """A binary stream which serves the body in small chunks and records
    every read call, so tests can assert on how much was consumed."""

    def __init__(self, body, chunk_size=8):
        self.body = body
        self.chunk_size = chunk_size
        self.read_calls = []
        self.closed = False
        self.offset = 0

    def read(self, size=-1):
        self.read_calls.append(size)
        if self.offset >= len(self.body):
            return b""
        end = min(self.offset + self.chunk_size, len(self.body))
        chunk = self.body[self.offset : end]
        self.offset = end
        return chunk

    def close(self):
        self.closed = True


class DisconnectingStream(ChunkedStream):
    """A stream which simulates a client disconnect after a number of reads."""

    def __init__(self, body, chunk_size=8, fail_after=2):
        super().__init__(body, chunk_size)
        self.fail_after = fail_after

    def read(self, size=-1):
        if len(self.read_calls) >= self.fail_after:
            raise ConnectionError("client disconnected")
        return super().read(size)


@pytest.fixture()
def parser():
    return Parser()


def make_body(*records, trailing_newline=True):
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    body = "\n".join(lines)
    if trailing_newline:
        body += "\n"
    return body.encode("utf-8")


GOOD_BODY = make_body(
    {"name": "alice", "age": 30},
    {"name": "bob", "age": 40},
    {"name": "carol", "age": 50},
)

# the second line fails validation, the third is valid again
MIXED_BODY = make_body(
    {"name": "alice", "age": 30},
    {"name": "bob", "age": "notanint"},
    {"name": "carol", "age": 50},
)


class TestLaziness:
    def test_creating_iterator_does_not_read(self, parser):
        stream = ChunkedStream(GOOD_BODY)
        parser.iter_ndjson(RecordSchema(), req=object(), stream=stream)
        assert stream.read_calls == []
        assert not stream.closed

    def test_records_are_consumed_lazily(self, parser):
        stream = ChunkedStream(GOOD_BODY, chunk_size=4)
        iterator = parser.iter_ndjson(RecordSchema(), req=object(), stream=stream)
        first = next(iterator)
        assert first == {"name": "alice", "age": 30}
        # only enough reads to complete the first line, not the whole body
        first_line_length = len(GOOD_BODY.split(b"\n")[0]) + 1
        expected_reads = -(-first_line_length // 4)  # ceil division
        assert len(stream.read_calls) == expected_reads
        assert stream.offset < len(stream.body)
        iterator.close()

    def test_short_reads_are_handled(self, parser):
        # the stream returns fewer bytes per read than requested
        stream = ChunkedStream(GOOD_BODY, chunk_size=3)
        iterator = parser.iter_ndjson(
            RecordSchema(), req=object(), stream=stream, chunk_size=8192
        )
        assert list(iterator) == [
            {"name": "alice", "age": 30},
            {"name": "bob", "age": 40},
            {"name": "carol", "age": 50},
        ]


class TestErrorStrategies:
    def test_on_error_raise_stops_at_first_error(self, parser):
        stream = ChunkedStream(MIXED_BODY)
        iterator = parser.iter_ndjson(
            RecordSchema(), req=object(), stream=stream, on_error="raise"
        )
        records = []
        with pytest.raises(NDJSONError) as excinfo:
            for record in iterator:
                records.append(record)
        # the record consumed before the error is not lost
        assert records == [{"name": "alice", "age": 30}]
        # the error carries the line number and the original field paths
        assert excinfo.value.line == 2
        assert excinfo.value.messages == {"age": ["Not a valid integer."]}
        # the third line was never consumed and the stream was released
        assert stream.closed

    def test_on_error_yield_returns_per_record_results(self, parser):
        stream = ChunkedStream(MIXED_BODY)
        results = list(
            parser.iter_ndjson(
                RecordSchema(), req=object(), stream=stream, on_error="yield"
            )
        )
        assert [result.line for result in results] == [1, 2, 3]
        assert results[0].ok
        assert results[0].data == {"name": "alice", "age": 30}
        assert results[0].error is None
        assert not results[1].ok
        assert results[1].data is None
        assert results[1].error.line == 2
        assert results[1].error.messages == {"age": ["Not a valid integer."]}
        assert results[2].ok
        assert results[2].data == {"name": "carol", "age": 50}
        assert stream.closed

    def test_invalid_on_error_value(self, parser):
        with pytest.raises(ValueError, match="on_error"):
            parser.iter_ndjson(
                RecordSchema(), req=object(), stream=ChunkedStream(b""),
                on_error="bogus",
            )

    def test_invalid_json_line(self, parser):
        body = b'{"name": "alice", "age": 30}\nnot json\n'
        results = list(
            parser.iter_ndjson(
                RecordSchema(), req=object(), stream=ChunkedStream(body),
                on_error="yield",
            )
        )
        assert results[0].ok
        assert not results[1].ok
        assert results[1].line == 2
        assert "Invalid JSON" in str(results[1].error)


class TestLineFraming:
    @pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 7])
    def test_multibyte_characters_and_newlines_spanning_chunks(
        self, parser, chunk_size
    ):
        body = make_body(
            {"name": "héllo ☃", "age": 1},
            {"name": "wörld", "age": 2},
        )
        stream = ChunkedStream(body, chunk_size=chunk_size)
        results = list(parser.iter_ndjson(RecordSchema(), req=object(), stream=stream))
        assert results == [
            {"name": "héllo ☃", "age": 1},
            {"name": "wörld", "age": 2},
        ]

    def test_empty_lines_are_skipped(self, parser):
        body = b'{"name": "alice", "age": 30}\n\n   \n{"name": "bob", "age": 40}\n'
        results = list(
            parser.iter_ndjson(RecordSchema(), req=object(), stream=ChunkedStream(body))
        )
        assert results == [
            {"name": "alice", "age": 30},
            {"name": "bob", "age": 40},
        ]

    def test_final_line_without_newline(self, parser):
        body = make_body(
            {"name": "alice", "age": 30},
            {"name": "bob", "age": 40},
            trailing_newline=False,
        )
        results = list(
            parser.iter_ndjson(RecordSchema(), req=object(), stream=ChunkedStream(body))
        )
        assert results == [
            {"name": "alice", "age": 30},
            {"name": "bob", "age": 40},
        ]

    def test_crlf_line_endings(self, parser):
        body = b'{"name": "alice", "age": 30}\r\n{"name": "bob", "age": 40}\r\n'
        results = list(
            parser.iter_ndjson(RecordSchema(), req=object(), stream=ChunkedStream(body))
        )
        assert results == [
            {"name": "alice", "age": 30},
            {"name": "bob", "age": 40},
        ]

    def test_max_line_length_raise(self, parser):
        body = b'{"name": "alice", "age": 30}\n' + b"x" * 100 + b"\n"
        iterator = parser.iter_ndjson(
            RecordSchema(), req=object(), stream=ChunkedStream(body),
            max_line_length=40,
        )
        records = []
        with pytest.raises(NDJSONError) as excinfo:
            for record in iterator:
                records.append(record)
        assert records == [{"name": "alice", "age": 30}]
        assert excinfo.value.line == 2
        assert "maximum length" in str(excinfo.value)

    def test_max_line_length_yield_continues_with_next_line(self, parser):
        body = (
            b'{"name": "alice", "age": 30}\n'
            + b"x" * 100 + b"\n"
            + b'{"name": "bob", "age": 40}\n'
        )
        results = list(
            parser.iter_ndjson(
                RecordSchema(), req=object(), stream=ChunkedStream(body, chunk_size=8),
                on_error="yield", max_line_length=40,
            )
        )
        assert [result.line for result in results] == [1, 2, 3]
        assert results[0].ok
        assert not results[1].ok
        assert "maximum length" in str(results[1].error)
        assert results[2].ok
        assert results[2].data == {"name": "bob", "age": 40}


class TestStreamCleanup:
    def test_closing_iterator_releases_stream(self, parser):
        stream = ChunkedStream(GOOD_BODY)
        iterator = parser.iter_ndjson(RecordSchema(), req=object(), stream=stream)
        next(iterator)
        iterator.close()
        assert stream.closed

    def test_view_exception_releases_stream(self, parser):
        stream = ChunkedStream(GOOD_BODY)
        iterator = parser.iter_ndjson(RecordSchema(), req=object(), stream=stream)
        with pytest.raises(RuntimeError, match="view exploded"):
            with contextlib.closing(iterator):
                for _record in iterator:
                    raise RuntimeError("view exploded")
        assert stream.closed

    def test_disconnect_releases_stream(self, parser):
        stream = DisconnectingStream(GOOD_BODY, chunk_size=4, fail_after=2)
        iterator = parser.iter_ndjson(RecordSchema(), req=object(), stream=stream)
        with pytest.raises(ConnectionError, match="client disconnected"):
            list(iterator)
        assert stream.closed

    def test_fully_consumed_stream_is_closed(self, parser):
        stream = ChunkedStream(GOOD_BODY)
        list(parser.iter_ndjson(RecordSchema(), req=object(), stream=stream))
        assert stream.closed


class TestSchemaHandling:
    def test_schema_is_reused_for_every_line(self, parser):
        schema = RecordSchema()
        body = make_body({"name": "alice", "age": 30}, {"name": "bob", "age": 40})
        results = list(
            parser.iter_ndjson(schema, req=object(), stream=ChunkedStream(body))
        )
        assert results == [
            {"name": "alice", "age": 30},
            {"name": "bob", "age": 40},
        ]

    def test_unknown_fields_are_passed_to_schema_load(self, parser):
        body = b'{"name": "alice", "age": 30, "extra": 1}\n'
        results = list(
            parser.iter_ndjson(
                RecordSchema(), req=object(), stream=ChunkedStream(body),
                unknown="exclude",
            )
        )
        assert results == [{"name": "alice", "age": 30}]

    def test_validate_callable_applies_to_each_record(self, parser):
        body = make_body({"name": "alice", "age": 30}, {"name": "bob", "age": 1})
        results = list(
            parser.iter_ndjson(
                RecordSchema(), req=object(), stream=ChunkedStream(body),
                on_error="yield",
                validate=lambda record: record["age"] >= 18,
            )
        )
        assert results[0].ok
        assert not results[1].ok
        assert results[1].error.line == 2

    def test_no_stream_available(self, parser):
        with pytest.raises(ValueError, match="stream"):
            parser.iter_ndjson(RecordSchema(), req=object())
