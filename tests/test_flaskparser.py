from unittest import mock

import marshmallow as ma
import pytest
from flask import Flask
from marshmallow import Schema
from werkzeug.exceptions import BadRequest, HTTPException

from webargs import ParameterCardinality, ValidationError, fields, missing
from webargs.core import json
from webargs.flaskparser import FlaskParser, abort, parser
from webargs.testing import CommonTestCase

from .apps.flask_app import app


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


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (ParameterCardinality.FIRST, 1),
        ("first", 1),
        (ParameterCardinality.LAST, 2),
        ("last", 2),
    ],
)
def test_repeated_query_scalar_uses_explicit_cardinality(policy, expected):
    cardinality_parser = FlaskParser(parameter_cardinality=policy)
    schema = Schema.from_dict(
        {
            "value": fields.Int(),
            "items": fields.List(fields.Int()),
            "missing": fields.Str(load_default="default"),
            "mapped": fields.Int(data_key="X-Field"),
        }
    )()
    app = Flask(__name__)

    with app.test_request_context(
        "/?value=1&value=2&items=3&items=4&X-Field=5"
    ):
        result = cardinality_parser.parse(schema, location="query")

    assert result == {
        "value": expected,
        "items": [3, 4],
        "missing": "default",
        "mapped": 5,
    }


def test_repeated_form_scalar_rejects_identical_values_before_deserialization():
    cardinality_parser = FlaskParser(
        parameter_cardinality=ParameterCardinality.REJECT
    )
    schema = Schema.from_dict(
        {"value": fields.Int(validate=lambda value: value < 0)}
    )()
    app = Flask(__name__)

    with app.test_request_context(
        "/",
        method="POST",
        data="value=1&value=1",
        content_type="application/x-www-form-urlencoded",
    ):
        with pytest.raises(HTTPException) as excinfo:
            cardinality_parser.parse(schema, location="form")

    messages = excinfo.value.data["messages"]["form"]
    assert messages["value"] == [
        "Duplicate form parameter at value: "
        "2 occurrences found at positions 1, 2."
    ]


@pytest.mark.parametrize(
    "policy", [ParameterCardinality.FIRST, ParameterCardinality.LAST]
)
def test_repeated_form_scalar_can_take_first_or_last(policy):
    cardinality_parser = FlaskParser(parameter_cardinality=policy)
    schema = Schema.from_dict({"value": fields.Int()})()
    app = Flask(__name__)

    with app.test_request_context(
        "/",
        method="POST",
        data="value=1&value=2",
        content_type="application/x-www-form-urlencoded",
    ):
        result = cardinality_parser.parse(schema, location="form")

    expected = 1 if policy is ParameterCardinality.FIRST else 2
    assert result == {"value": expected}


@pytest.mark.parametrize(
    "policy",
    [
        ParameterCardinality.REJECT,
        ParameterCardinality.FIRST,
        ParameterCardinality.LAST,
    ],
)
def test_explicit_cardinality_never_pretends_folded_input_was_checked(policy):
    cardinality_parser = FlaskParser(parameter_cardinality=policy)
    schema = Schema.from_dict({"value": fields.Int()})()
    app = Flask(__name__)

    with app.test_request_context():
        cardinality_parser.load_json = lambda req, schema: {"value": 1}
        with pytest.raises(HTTPException) as excinfo:
            cardinality_parser.parse(schema)

    assert (
        "raw occurrences are unavailable"
        in excinfo.value.data["messages"]["json"]["_schema"][0]
    )


def test_repeated_json_keys_are_rejected_with_paths_and_occurrences():
    cardinality_parser = FlaskParser(
        parameter_cardinality=ParameterCardinality.REJECT
    )
    schema = Schema.from_dict(
        {
            "value": fields.Int(),
            "items": fields.List(fields.Int()),
            "nested": fields.Nested(
                {
                    "value": fields.Int(),
                    "list": fields.List(fields.Int()),
                    "deep": fields.Nested({"value": fields.Int()}),
                }
            ),
            "rows": fields.List(fields.Nested({"value": fields.Int()})),
            "escaped": fields.Int(),
        }
    )()
    body = (
        '{"value":1,"value":1,'
        '"items":[1],"items":[2,3],'
        '"nested":{"value":1,"value":2,"list":[1],"list":[2],'
        '"deep":{"value":1,"value":2}},'
        '"rows":[{"value":1,"value":2}],'
        '"esc\\u0061ped":1,"esca\\u0070ed":2}'
    )
    app = Flask(__name__)

    with app.test_request_context(
        "/",
        method="POST",
        data=body.encode(),
        content_type="application/json",
    ):
        with pytest.raises(HTTPException) as excinfo:
            cardinality_parser.parse(schema, unknown=ma.EXCLUDE)

    messages = excinfo.value.data["messages"]["json"]
    assert messages["value"] == [
        "Duplicate json parameter at value: "
        "2 occurrences found at positions 1, 2."
    ]
    assert messages["nested"]["value"] == [
        "Duplicate json parameter at nested.value: "
        "2 occurrences found at positions 1, 2."
    ]
    assert messages["nested"]["deep"]["value"] == [
        "Duplicate json parameter at nested.deep.value: "
        "2 occurrences found at positions 1, 2."
    ]
    assert messages["rows"][0]["value"] == [
        "Duplicate json parameter at rows.0.value: "
        "2 occurrences found at positions 1, 2."
    ]
    assert messages["escaped"] == [
        "Duplicate json parameter at escaped: "
        "2 occurrences found at positions 7, 8."
    ]
    assert "items" not in messages
    assert "list" not in messages["nested"]


def test_repeated_json_keys_first_last_and_lists():
    body = (
        '{"value":1,"value":2,"items":[1],"items":[2,3],'
        '"nested":{"value":1,"value":2,"list":[1],"list":[2]}}'
    )
    schema = Schema.from_dict(
        {
            "value": fields.Int(),
            "items": fields.List(fields.Int()),
            "nested": fields.Nested(
                {"value": fields.Int(), "list": fields.List(fields.Int())}
            ),
        }
    )()
    app = Flask(__name__)
    expected = {
        ParameterCardinality.FIRST: {
            "value": 1,
            "items": [1, 2, 3],
            "nested": {"value": 1, "list": [1, 2]},
        },
        ParameterCardinality.LAST: {
            "value": 2,
            "items": [1, 2, 3],
            "nested": {"value": 2, "list": [1, 2]},
        },
    }

    for policy, want in expected.items():
        cardinality_parser = FlaskParser(parameter_cardinality=policy)
        with app.test_request_context(
            "/",
            method="POST",
            data=body.encode(),
            content_type="application/json",
        ):
            assert cardinality_parser.parse(schema) == want


def test_custom_multiple_field_preserves_single_json_value_shape():
    class Multiple(fields.Field):
        is_multiple = True

        def _deserialize(self, value, attr, data, **kwargs):
            return value

    cardinality_parser = FlaskParser(
        parameter_cardinality=ParameterCardinality.FIRST
    )
    schema = Schema.from_dict({"custom": Multiple()})()
    app = Flask(__name__)

    with app.test_request_context(
        "/",
        method="POST",
        data=b'{"custom":"single"}',
        content_type="application/json",
    ):
        assert cardinality_parser.parse(schema) == {"custom": "single"}


def test_repeated_json_unknown_key_is_not_masked_by_unknown_exclude():
    cardinality_parser = FlaskParser(
        parameter_cardinality=ParameterCardinality.REJECT
    )
    schema = Schema.from_dict({"value": fields.Int()})()
    app = Flask(__name__)

    with app.test_request_context(
        "/",
        method="POST",
        data=b'{"unknown":1,"unknown":2}',
        content_type="application/json",
    ):
        with pytest.raises(HTTPException) as excinfo:
            cardinality_parser.parse(schema, unknown=ma.EXCLUDE)

    assert "unknown" in excinfo.value.data["messages"]["json"]


def test_default_cardinality_preserves_existing_json_and_query_behavior():
    default_parser = FlaskParser()
    schema = Schema.from_dict({"value": fields.Int()})()
    app = Flask(__name__)

    with app.test_request_context(
        "/",
        method="POST",
        data=b'{"value":1,"value":2}',
        content_type="application/json",
    ):
        assert default_parser.parse(schema) == {"value": 2}

    with app.test_request_context("/?value=1&value=2"):
        assert default_parser.parse(schema, location="query") == {"value": 1}


def test_use_args_parameter_cardinality_option_is_supported():
    cardinality_parser = FlaskParser()
    app = Flask(__name__)

    @app.route("/")
    @cardinality_parser.use_args(
        Schema.from_dict({"value": fields.Int()})(),
        location="query",
        parameter_cardinality=ParameterCardinality.LAST,
    )
    def view(args):
        return args

    client = app.test_client()
    response = client.get("/?value=1&value=2")

    assert response.get_json() == {"value": 2}


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
