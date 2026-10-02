from unittest import mock

import marshmallow as ma
import pytest
from flask import Flask, jsonify
from marshmallow import Schema
from werkzeug.exceptions import BadRequest, HTTPException

from webargs import ValidationError, fields, missing
from webargs.core import json
from webargs.flaskparser import abort, parser
from webargs.testing import CommonTestCase

from .apps.flask_app import app


def create_multilocation_app():
    from webargs.flaskparser import parser

    multilocation_app = Flask(__name__)

    class ReleaseSchema(ma.Schema):
        query_version = fields.Int(
            required=True, location="query", data_key="version"
        )
        header_version = fields.Int(
            required=True, location="headers", data_key="X-Version"
        )
        body_version = fields.Int(required=True, location="json", data_key="version")

        @ma.validates_schema
        def validate_release(self, data, **kwargs):
            versions = [
                data["query_version"],
                data["header_version"],
                data["body_version"],
            ]
            if len(set(versions)) != 1:
                raise ma.ValidationError("All versions must match.")

    @multilocation_app.post("/release")
    def release():
        args = parser.parse(ReleaseSchema())
        return jsonify(args)

    @multilocation_app.post("/release-async")
    async def release_async():
        args = await parser.async_parse(ReleaseSchema())
        return jsonify(args)

    @multilocation_app.errorhandler(422)
    def handle_validation_error(error: HTTPException):
        return jsonify(error.data["messages"]), error.code

    return multilocation_app


class TestFlaskParser(CommonTestCase):
    def create_app(self):
        return app

    def test_parsing_view_args(self, testapp):
        res = testapp.get("/echo_view_arg/42")
        assert res.json == {"view_arg": 42}

    def test_parsing_invalid_view_arg(self, testapp):
        res = testapp.get("/echo_view_arg/foo", expect_errors=True)
        assert res.status_code == 422
        assert res.json == {"view_args": {"view_arg": ["Not a valid integer."]}}

    def test_use_args_with_view_args_parsing(self, testapp):
        res = testapp.get("/echo_view_arg_use_args/42")
        assert res.json == {"view_arg": 42}

    def test_use_args_on_a_method_view(self, testapp):
        res = testapp.post_json("/echo_method_view_use_args", {"val": 42})
        assert res.json == {"val": 42}

    def test_use_kwargs_on_a_method_view(self, testapp):
        res = testapp.post_json("/echo_method_view_use_kwargs", {"val": 42})
        assert res.json == {"val": 42}

    def test_use_kwargs_with_missing_data(self, testapp):
        res = testapp.post_json("/echo_use_kwargs_missing", {"username": "foo"})
        assert res.json == {"username": "foo"}

    # regression test for https://github.com/marshmallow-code/webargs/issues/145
    def test_nested_many_with_data_key(self, testapp):
        post_with_raw_fieldname_args = (
            "/echo_nested_many_data_key",
            {"x_field": [{"id": 42}]},
        )
        res = testapp.post_json(*post_with_raw_fieldname_args, expect_errors=True)
        assert res.status_code == 422

        res = testapp.post_json("/echo_nested_many_data_key", {"X-Field": [{"id": 24}]})
        assert res.json == {"x_field": [{"id": 24}]}

        res = testapp.post_json("/echo_nested_many_data_key", {})
        assert res.json == {}

    # regression test for https://github.com/marshmallow-code/webargs/issues/500
    def test_parsing_unexpected_headers_when_raising(self, testapp):
        res = testapp.get(
            "/echo_headers_raising", expect_errors=True, headers={"X-Unexpected": "foo"}
        )
        assert res.status_code == 422
        assert "headers" in res.json
        assert "X-Unexpected" in set(res.json["headers"].keys())


class TestFlaskAsyncParser(CommonTestCase):
    def create_app(self):
        return app

    def test_parsing_view_args_async(self, testapp):
        res = testapp.get("/echo_view_arg_async/42")
        assert res.json == {"view_arg": 42}

    def test_parsing_invalid_view_arg_async(self, testapp):
        res = testapp.get("/echo_view_arg_async/foo", expect_errors=True)
        assert res.status_code == 422
        assert res.json == {"view_args": {"view_arg": ["Not a valid integer."]}}

    def test_use_args_with_view_args_parsing_async(self, testapp):
        res = testapp.get("/echo_view_arg_use_args_async/42")
        assert res.json == {"view_arg": 42}

    def test_use_args_on_a_method_view_async(self, testapp):
        res = testapp.post_json("/echo_method_view_use_args_async", {"val": 42})
        assert res.json == {"val": 42}

    def test_use_kwargs_on_a_method_view_async(self, testapp):
        res = testapp.post_json("/echo_method_view_use_kwargs_async", {"val": 42})
        assert res.json == {"val": 42}

    def test_use_kwargs_with_missing_data_async(self, testapp):
        res = testapp.post_json("/echo_use_kwargs_missing_async", {"username": "foo"})
        assert res.json == {"username": "foo"}

    # regression test for https://github.com/marshmallow-code/webargs/issues/145
    def test_nested_many_with_data_key_async(self, testapp):
        post_with_raw_fieldname_args = (
            "/echo_nested_many_data_key_async",
            {"x_field": [{"id": 42}]},
        )
        res = testapp.post_json(*post_with_raw_fieldname_args, expect_errors=True)
        assert res.status_code == 422

        res = testapp.post_json(
            "/echo_nested_many_data_key_async", {"X-Field": [{"id": 24}]}
        )
        assert res.json == {"x_field": [{"id": 24}]}

        res = testapp.post_json("/echo_nested_many_data_key_async", {})
        assert res.json == {}

    # regression test for https://github.com/marshmallow-code/webargs/issues/500
    def test_parsing_unexpected_headers_when_raising_async(self, testapp):
        res = testapp.get(
            "/echo_headers_raising_async",
            expect_errors=True,
            headers={"X-Unexpected": "foo"},
        )
        assert res.status_code == 422
        assert "headers" in res.json
        assert "X-Unexpected" in set(res.json["headers"].keys())


@mock.patch("webargs.flaskparser.abort")
def test_abort_called_on_validation_error(mock_abort):
    # error handling must raise an error to be valid
    mock_abort.side_effect = BadRequest("foo")

    app = Flask("testapp")

    def validate(x):
        if x != 42:
            raise ValidationError("Invalid value.")

    argmap = {"value": fields.Raw(validate=validate)}
    with app.test_request_context(
        "/foo",
        method="post",
        data=json.dumps({"value": 41}),
        content_type="application/json",
    ):
        with pytest.raises(HTTPException):
            parser.parse(argmap)
    mock_abort.assert_called()
    abort_args, abort_kwargs = mock_abort.call_args
    assert abort_args[0] == 422
    expected_msg = "Invalid value."
    assert abort_kwargs["messages"]["json"]["value"] == [expected_msg]
    assert type(abort_kwargs["exc"]) is ValidationError


@pytest.mark.parametrize("path", ["/release", "/release-async"])
@pytest.mark.parametrize(
    ("query", "headers", "json_body", "expected"),
    [
        (
            "",
            {"X-Version": "1"},
            {"version": 1},
            {"query": {"version": ["Missing data for required field."]}},
        ),
        (
            "?version=1",
            {},
            {"version": 1},
            {"headers": {"X-Version": ["Missing data for required field."]}},
        ),
        (
            "?version=1",
            {"X-Version": "1"},
            {},
            {"json": {"version": ["Missing data for required field."]}},
        ),
    ],
)
def test_multilocation_missing_inputs_are_distinguishable(
    path, query, headers, json_body, expected
):
    client = create_multilocation_app().test_client()

    response = client.post(
        f"{path}{query}",
        json=json_body,
        headers=headers,
    )

    assert response.status_code == 422
    assert response.get_json() == expected


@pytest.mark.parametrize("path", ["/release", "/release-async"])
def test_multilocation_schema_validation_runs_after_combining_sources(path):
    client = create_multilocation_app().test_client()

    response = client.post(
        f"{path}?version=1",
        json={"version": 1},
        headers={"X-Version": "2"},
    )

    assert response.status_code == 422
    assert response.get_json() == {"_schema": ["All versions must match."]}

    response = client.post(
        f"{path}?version=1",
        json={"version": 1},
        headers={"X-Version": "1"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "query_version": 1,
        "header_version": 1,
        "body_version": 1,
    }


def test_multilocation_request_body_is_read_once():
    client = create_multilocation_app().test_client()

    with mock.patch(
        "webargs.flaskparser.FlaskParser._raw_load_json",
        wraps=parser._raw_load_json,
    ) as load_json:
        response = client.post(
            "/release?version=1",
            json={"version": 1},
            headers={"X-Version": "1"},
        )

    assert response.status_code == 200
    assert load_json.call_count == 1


@pytest.mark.asyncio
async def test_abort_called_on_validation_error_async():
    with mock.patch("webargs.flaskparser.abort") as mock_abort:
        # error handling must raise an error to be valid
        mock_abort.side_effect = BadRequest("foo")

        app = Flask("testapp")

        def validate(x):
            if x != 42:
                raise ValidationError("Invalid value.")

        argmap = {"value": fields.Raw(validate=validate)}
        with app.test_request_context(
            "/foo",
            method="post",
            data=json.dumps({"value": 41}),
            content_type="application/json",
        ):
            with pytest.raises(HTTPException):
                await parser.async_parse(argmap)
        mock_abort.assert_called()
        abort_args, abort_kwargs = mock_abort.call_args
        assert abort_args[0] == 422
        expected_msg = "Invalid value."
        assert abort_kwargs["messages"]["json"]["value"] == [expected_msg]
        assert type(abort_kwargs["exc"]) is ValidationError


@pytest.mark.parametrize("mimetype", [None, "application/json"])
def test_load_json_returns_missing_if_no_data(mimetype):
    req = mock.Mock()
    req.mimetype = mimetype
    req.get_data.return_value = ""
    schema = Schema.from_dict({"foo": fields.Raw()})()
    assert parser.load_json(req, schema) is missing


def test_abort_with_message():
    with pytest.raises(HTTPException) as excinfo:
        abort(400, message="custom error message")
    assert excinfo.value.data["message"] == "custom error message"


def test_abort_has_serializable_data():
    with pytest.raises(HTTPException) as excinfo:
        abort(400, message="custom error message")
    serialized_error = json.dumps(excinfo.value.data)
    error = json.loads(serialized_error)
    assert isinstance(error, dict)
    assert error["message"] == "custom error message"

    with pytest.raises(HTTPException) as excinfo:
        abort(
            400,
            message="custom error message",
            exc=ValidationError("custom error message"),
        )
    serialized_error = json.dumps(excinfo.value.data)
    error = json.loads(serialized_error)
    assert isinstance(error, dict)
    assert error["message"] == "custom error message"
