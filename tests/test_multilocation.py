from unittest import mock

import marshmallow as ma
import pytest
from werkzeug.datastructures import MultiDict

from webargs import fields
from webargs.core import Parser, ValidationError


class MultiLocationParser(Parser):
    def load_querystring(self, req, schema):
        req.query_loads += 1
        return self._makeproxy(MultiDict(req.query), schema)

    def load_headers(self, req, schema):
        req.header_loads += 1
        return self._makeproxy(MultiDict(req.headers), schema)

    def load_json(self, req, schema):
        req.json_loads += 1
        return req.json


class Request:
    def __init__(self, *, query=None, headers=None, json=None):
        self.query = query or []
        self.headers = headers or []
        self.json = {} if json is None else json
        self.query_loads = 0
        self.header_loads = 0
        self.json_loads = 0


class VersionSchema(ma.Schema):
    query_version = fields.Int(
        required=True, location="query", data_key="version"
    )
    header_version = fields.Int(
        required=True, location="headers", data_key="X-Version"
    )
    body_version = fields.Int(required=True, location="json", data_key="version")
    tags = fields.List(fields.Str(), location="query")

    @ma.validates_schema
    def validate_matching_versions(self, data, **kwargs):
        values = [
            data["query_version"],
            data["header_version"],
            data["body_version"],
        ]
        if len(set(values)) != 1:
            raise ma.ValidationError("Versions must match.")


@pytest.fixture
def parser():
    return MultiLocationParser()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["parse", "async_parse"])
async def test_parse_combines_fields_from_multiple_locations(parser, method):
    request = Request(
        query=[("version", "1"), ("tags", "a"), ("tags", "b")],
        headers=[("X-Version", "1")],
        json={"version": 1},
    )

    if method == "parse":
        result = parser.parse(VersionSchema(), request)
    else:
        result = await parser.async_parse(VersionSchema(), request)

    assert result == {
        "query_version": 1,
        "header_version": 1,
        "body_version": 1,
        "tags": ["a", "b"],
    }
    assert (request.query_loads, request.header_loads, request.json_loads) == (
        1,
        1,
        1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["parse", "async_parse"])
@pytest.mark.parametrize(
    ("missing", "request_factory", "expected"),
    [
        (
            "query",
            lambda: Request(headers=[("X-Version", "1")], json={"version": 1}),
            {"query": {"version": ["Missing data for required field."]}},
        ),
        (
            "headers",
            lambda: Request(query=[("version", "1")], json={"version": 1}),
            {"headers": {"X-Version": ["Missing data for required field."]}},
        ),
        (
            "body",
            lambda: Request(query=[("version", "1")], headers=[("X-Version", "1")]),
            {"json": {"version": ["Missing data for required field."]}},
        ),
    ],
)
async def test_missing_field_errors_identify_source_and_original_key(
    parser, method, missing, request_factory, expected
):
    request = request_factory()

    with pytest.raises(ValidationError) as excinfo:
        if method == "parse":
            parser.parse(VersionSchema(), request)
        else:
            await parser.async_parse(VersionSchema(), request)

    assert excinfo.value.messages == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["parse", "async_parse"])
async def test_schema_level_error_is_not_assigned_to_one_location(parser, method):
    request = Request(
        query=[("version", "1")],
        headers=[("X-Version", "2")],
        json={"version": 1},
    )

    with pytest.raises(ValidationError) as excinfo:
        if method == "parse":
            parser.parse(VersionSchema(), request)
        else:
            await parser.async_parse(VersionSchema(), request)

    assert excinfo.value.messages == {"_schema": ["Versions must match."]}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["parse", "async_parse"])
async def test_field_error_identifies_original_source_and_key(parser, method):
    request = Request(
        query=[("version", "not-an-int")],
        headers=[("X-Version", "1")],
        json={"version": 1},
    )

    with pytest.raises(ValidationError) as excinfo:
        if method == "parse":
            parser.parse(VersionSchema(), request)
        else:
            await parser.async_parse(VersionSchema(), request)

    assert excinfo.value.messages == {
        "query": {"version": ["Not a valid integer."]}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["parse", "async_parse"])
async def test_nested_field_error_keeps_location_namespace(parser, method):
    class NestedVersionSchema(ma.Schema):
        release = fields.Nested(
            {"version": fields.Int(required=True)},
            location="json",
            data_key="release",
        )
        header_version = fields.Int(
            location="headers", data_key="X-Version"
        )

    request = Request(
        headers=[("X-Version", "1")],
        json={"release": {}},
    )

    with pytest.raises(ValidationError) as excinfo:
        if method == "parse":
            parser.parse(NestedVersionSchema(), request)
        else:
            await parser.async_parse(NestedVersionSchema(), request)

    assert excinfo.value.messages == {
        "json": {"release": {"version": ["Missing data for required field."]}}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["parse", "async_parse"])
async def test_same_named_unknown_inputs_are_not_implicitly_overwritten(
    parser, method
):
    class SharedNameSchema(ma.Schema):
        query_value = fields.Str(location="query")
        header_value = fields.Str(location="headers")

    request = Request(
        query=[("query_value", "query"), ("shared", "query")],
        headers=[("header_value", "header"), ("shared", "header")],
    )

    with pytest.raises(ValidationError) as excinfo:
        if method == "parse":
            parser.parse(SharedNameSchema(), request, unknown=ma.INCLUDE)
        else:
            await parser.async_parse(
                SharedNameSchema(), request, unknown=ma.INCLUDE
            )

    assert excinfo.value.messages == {
        "_schema": ["Ambiguous value for 'shared' from 'query' and 'headers'."]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["parse", "async_parse"])
async def test_invalid_field_location_is_rejected_before_loading(parser, method):
    request = Request(json={"version": 1})
    argmap = {"version": fields.Int(location="invalid")}

    with (
        mock.patch.object(parser, "load_json") as load_json,
        pytest.raises(ValueError, match="Invalid location argument: invalid"),
    ):
        if method == "parse":
            parser.parse(argmap, request)
        else:
            await parser.async_parse(argmap, request)

    load_json.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["parse", "async_parse"])
async def test_unknown_strategy_is_applied_per_location(parser, method):
    request = Request(
        query=[("version", "1"), ("ignored_query", "x")],
        headers=[("X-Version", "1")],
        json={"version": 1, "unexpected_body": "x"},
    )

    with pytest.raises(ValidationError) as excinfo:
        if method == "parse":
            parser.parse(VersionSchema(), request)
        else:
            await parser.async_parse(VersionSchema(), request)

    assert excinfo.value.messages == {
        "json": {"unexpected_body": ["Unknown field."]}
    }

    request = Request(
        query=[("version", "1"), ("ignored_query", "x")],
        headers=[("X-Version", "1")],
        json={"version": 1, "included_body": "x"},
    )

    if method == "parse":
        result = parser.parse(VersionSchema(), request, unknown=ma.INCLUDE)
    else:
        result = await parser.async_parse(VersionSchema(), request, unknown=ma.INCLUDE)

    assert result["included_body"] == "x"
    assert result["ignored_query"] == "x"

    request = Request(
        query=[("version", "1"), ("ignored_query", "x")],
        headers=[("X-Version", "1")],
        json={"version": 1, "included_body": "x"},
    )
    class PerLocationParser(MultiLocationParser):
        DEFAULT_UNKNOWN_BY_LOCATION = {
            **Parser.DEFAULT_UNKNOWN_BY_LOCATION,
            "json": ma.INCLUDE,
        }

    schema = VersionSchema()
    parser = PerLocationParser()

    if method == "parse":
        result = parser.parse(schema, request)
    else:
        result = await parser.async_parse(schema, request)

    assert result["included_body"] == "x"
    assert "ignored_query" not in result
