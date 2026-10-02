"""Tests for the duplicate-parameter (cardinality) policy.

Covers query strings, forms, and JSON bodies -- including nested objects,
arrays, and escape-equivalent keys -- using real Flask requests.
"""

import marshmallow as ma
import pytest
import webtest
from flask import Flask, jsonify

from webargs import DuplicateParameterError, fields, missing
from webargs.core import parse_json_with_duplicates
from webargs.flaskparser import FlaskParser

JSON_HEADERS = {"Content-Type": "application/json"}
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


class InnerSchema(ma.Schema):
    x = fields.Int()


class OuterSchema(ma.Schema):
    inner = fields.Nested(InnerSchema)


class ItemSchema(ma.Schema):
    x = fields.Int()


def make_app(duplicate_policy=None):
    app = Flask(__name__)
    parser = FlaskParser(duplicate_policy=duplicate_policy)

    @app.errorhandler(422)
    def handle_422(err):
        return jsonify(err.data["messages"]), 422

    @app.route("/query")
    def query():
        return jsonify(parser.parse({"a": fields.Str()}, location="query"))

    @app.route("/query_list")
    def query_list():
        return jsonify(
            parser.parse({"a": fields.List(fields.Str())}, location="query")
        )

    @app.route("/query_data_key")
    def query_data_key():
        return jsonify(
            parser.parse({"a": fields.Str(data_key="A")}, location="query")
        )

    @app.route("/form", methods=["POST"])
    def form():
        return jsonify(parser.parse({"a": fields.Str()}, location="form"))

    @app.route("/json", methods=["POST"])
    def json_body():
        return jsonify(parser.parse({"a": fields.Int()}, location="json"))

    @app.route("/json_list", methods=["POST"])
    def json_list():
        return jsonify(
            parser.parse({"a": fields.List(fields.Int())}, location="json")
        )

    @app.route("/json_nested", methods=["POST"])
    def json_nested():
        return jsonify(
            parser.parse({"outer": fields.Nested(OuterSchema)}, location="json")
        )

    @app.route("/json_array", methods=["POST"])
    def json_array():
        return jsonify(
            parser.parse(
                {"items": fields.List(fields.Nested(ItemSchema))}, location="json"
            )
        )

    @app.route("/json_data_key", methods=["POST"])
    def json_data_key():
        return jsonify(
            parser.parse({"a": fields.Int(data_key="A")}, location="json")
        )

    return app


@pytest.fixture(scope="module")
def reject_app():
    return webtest.TestApp(make_app("reject"))


@pytest.fixture(scope="module")
def first_app():
    return webtest.TestApp(make_app("first"))


@pytest.fixture(scope="module")
def last_app():
    return webtest.TestApp(make_app("last"))


@pytest.fixture(scope="module")
def default_app():
    return webtest.TestApp(make_app())


def post_raw_json(testapp, url, body):
    return testapp.post(url, body, headers=JSON_HEADERS, expect_errors=True)


class TestDefaultPolicyUnchanged:
    def test_query_keeps_framework_behavior(self, default_app):
        # werkzeug multidicts resolve scalar lookups to the first value
        assert default_app.get("/query?a=1&a=2").json == {"a": "1"}

    def test_json_keeps_json_loads_behavior(self, default_app):
        # json.loads keeps the last occurrence of a repeated key
        res = post_raw_json(default_app, "/json", '{"a": 1, "a": 2}')
        assert res.status_code == 200
        assert res.json == {"a": 2}

    def test_form_keeps_framework_behavior(self, default_app):
        res = default_app.post("/form", "a=1&a=2", headers=FORM_HEADERS)
        assert res.json == {"a": "1"}


class TestRejectPolicy:
    def test_query_duplicate_rejected(self, reject_app):
        res = reject_app.get("/query?a=1&a=2", expect_errors=True)
        assert res.status_code == 422
        messages = res.json["query"]["a"]
        assert messages == ["Duplicate parameter at occurrence 2."]

    def test_query_identical_values_still_rejected(self, reject_app):
        res = reject_app.get("/query?a=1&a=1", expect_errors=True)
        assert res.status_code == 422
        assert "a" in res.json["query"]

    def test_query_occurrence_indices(self, reject_app):
        res = reject_app.get("/query?a=1&a=2&a=3", expect_errors=True)
        assert res.status_code == 422
        assert res.json["query"]["a"] == [
            "Duplicate parameter at occurrence 2.",
            "Duplicate parameter at occurrence 3.",
        ]

    def test_query_single_value_ok(self, reject_app):
        assert reject_app.get("/query?a=1").json == {"a": "1"}

    def test_list_field_collects_as_declared(self, reject_app):
        res = reject_app.get("/query_list?a=1&a=2")
        assert res.json == {"a": ["1", "2"]}

    def test_unknown_param_duplicate_not_masked(self, reject_app):
        # unknown=EXCLUDE for query locations must not hide the conflict
        res = reject_app.get("/query?a=1&b=1&b=2", expect_errors=True)
        assert res.status_code == 422
        assert "b" in res.json["query"]

    def test_data_key_duplicate_not_masked(self, reject_app):
        res = reject_app.get("/query_data_key?A=1&A=2", expect_errors=True)
        assert res.status_code == 422
        assert "A" in res.json["query"]

    def test_form_duplicate_rejected(self, reject_app):
        res = reject_app.post(
            "/form", "a=1&a=2", headers=FORM_HEADERS, expect_errors=True
        )
        assert res.status_code == 422
        assert res.json["form"]["a"] == ["Duplicate parameter at occurrence 2."]

    def test_json_duplicate_key_rejected(self, reject_app):
        res = post_raw_json(reject_app, "/json", '{"a": 1, "a": 2}')
        assert res.status_code == 422
        assert res.json["json"]["a"] == ["Duplicate parameter at occurrence 2."]

    def test_json_identical_values_still_rejected(self, reject_app):
        res = post_raw_json(reject_app, "/json", '{"a": 1, "a": 1}')
        assert res.status_code == 422
        assert "a" in res.json["json"]

    def test_json_nested_duplicate_key_rejected(self, reject_app):
        body = '{"outer": {"inner": {"x": 1, "x": 2}}}'
        res = post_raw_json(reject_app, "/json_nested", body)
        assert res.status_code == 422
        messages = res.json["json"]["outer"]["inner"]["x"]
        assert messages == ["Duplicate parameter at occurrence 2."]

    def test_json_duplicate_key_inside_array_rejected(self, reject_app):
        body = '{"items": [{"x": 1, "x": 2}]}'
        res = post_raw_json(reject_app, "/json_array", body)
        assert res.status_code == 422
        messages = res.json["json"]["items"]["0"]["x"]
        assert messages == ["Duplicate parameter at occurrence 2."]

    def test_json_escape_equivalent_keys_rejected(self, reject_app):
        # "a" and "a" are distinct raw keys but decode to the same name
        res = post_raw_json(reject_app, "/json", '{"a": 1, "a": 2}')
        assert res.status_code == 422
        assert res.json["json"]["a"] == ["Duplicate parameter at occurrence 2."]

    def test_json_list_field_duplicate_key_rejected(self, reject_app):
        res = post_raw_json(reject_app, "/json_list", '{"a": [1], "a": [2]}')
        assert res.status_code == 422
        assert "a" in res.json["json"]

    def test_json_data_key_duplicate_not_masked(self, reject_app):
        res = post_raw_json(reject_app, "/json_data_key", '{"A": 1, "A": 2}')
        assert res.status_code == 422
        assert "A" in res.json["json"]

    def test_error_does_not_echo_values(self, reject_app):
        res = reject_app.get("/query?a=secret-one&a=secret-two", expect_errors=True)
        assert res.status_code == 422
        assert "secret-one" not in res.text
        assert "secret-two" not in res.text

    def test_error_carries_source_path_and_occurrence(self):
        app = make_app("reject")
        parser = FlaskParser(duplicate_policy="reject")

        @parser.error_handler
        def reraise(error, req, schema, *, error_status_code, error_headers):
            raise error

        with app.test_request_context("/?a=1&a=2"):
            with pytest.raises(DuplicateParameterError) as exc_info:
                parser.parse({"a": fields.Str()}, location="query")
        error = exc_info.value
        assert error.location == "query"
        assert error.field_path == ("a",)
        assert error.occurrence == 2


class TestFirstLastPolicies:
    def test_query_first(self, first_app):
        assert first_app.get("/query?a=1&a=2").json == {"a": "1"}

    def test_query_last(self, last_app):
        assert last_app.get("/query?a=1&a=2").json == {"a": "2"}

    def test_form_first(self, first_app):
        res = first_app.post("/form", "a=1&a=2", headers=FORM_HEADERS)
        assert res.json == {"a": "1"}

    def test_form_last(self, last_app):
        res = last_app.post("/form", "a=1&a=2", headers=FORM_HEADERS)
        assert res.json == {"a": "2"}

    def test_list_field_still_collects(self, first_app, last_app):
        assert first_app.get("/query_list?a=1&a=2").json == {"a": ["1", "2"]}
        assert last_app.get("/query_list?a=1&a=2").json == {"a": ["1", "2"]}

    def test_json_first(self, first_app):
        res = post_raw_json(first_app, "/json", '{"a": 1, "a": 2}')
        assert res.status_code == 200
        assert res.json == {"a": 1}

    def test_json_last(self, last_app):
        res = post_raw_json(last_app, "/json", '{"a": 1, "a": 2}')
        assert res.status_code == 200
        assert res.json == {"a": 2}

    def test_json_nested_first(self, first_app):
        body = '{"outer": {"inner": {"x": 1, "x": 2}}}'
        res = post_raw_json(first_app, "/json_nested", body)
        assert res.status_code == 200
        assert res.json == {"outer": {"inner": {"x": 1}}}


class TestUnavailableRawData:
    def test_reject_without_raw_access_reports_unguaranteed(self):
        class CollapsingOnlyParser(FlaskParser):
            def _raw_load_json_text(self, req):
                return missing

            def _raw_load_json(self, req):
                # the framework only offers an already-collapsed value
                return req.get_json(silent=True) or missing

        app = Flask(__name__)
        parser = CollapsingOnlyParser(duplicate_policy="reject")

        @app.errorhandler(422)
        def handle_422(err):
            return jsonify(err.data["messages"]), 422

        @app.route("/json", methods=["POST"])
        def json_body():
            return jsonify(parser.parse({"a": fields.Int()}, location="json"))

        testapp = webtest.TestApp(app)
        res = post_raw_json(testapp, "/json", '{"a": 1}')
        assert res.status_code == 422
        messages = res.json["json"]["_schema"]
        assert messages == [
            "Duplicate parameter policy 'reject' cannot be enforced: "
            "the framework did not provide access to the raw request data, "
            "so duplicate parameters cannot be detected."
        ]


class TestParseJsonWithDuplicates:
    def test_no_duplicates(self):
        data, duplicates = parse_json_with_duplicates('{"a": 1, "b": [2, 3]}')
        assert data == {"a": 1, "b": [2, 3]}
        assert duplicates == []

    def test_nested_paths(self):
        body = '{"outer": [{"x": 1, "x": 2}], "y": {"y": 1, "y": 2}}'
        data, duplicates = parse_json_with_duplicates(body)
        assert duplicates == [(("outer", 0, "x"), 2), (("y", "y"), 2)]
        assert data == {"outer": [{"x": 2}], "y": {"y": 2}}

    def test_keep_first(self):
        data, duplicates = parse_json_with_duplicates(
            '{"a": 1, "a": 2, "a": 3}', keep="first"
        )
        assert data == {"a": 1}
        assert duplicates == [(("a",), 2), (("a",), 3)]

    def test_escape_equivalent_keys(self):
        data, duplicates = parse_json_with_duplicates('{"a": 1, "a": 2}')
        assert data == {"a": 2}
        assert duplicates == [(("a",), 2)]

    def test_bytes_input(self):
        data, duplicates = parse_json_with_duplicates(b'{"a": 1, "a": 2}')
        assert data == {"a": 2}
        assert duplicates == [(("a",), 2)]


def test_invalid_duplicate_policy_raises():
    with pytest.raises(ValueError, match="Invalid duplicate_policy"):
        FlaskParser(duplicate_policy="bogus")


def test_parse_level_policy_overrides_parser():
    app = make_app()
    parser = FlaskParser()

    @parser.error_handler
    def reraise(error, req, schema, *, error_status_code, error_headers):
        raise error

    with app.test_request_context("/?a=1&a=2"):
        with pytest.raises(DuplicateParameterError):
            parser.parse(
                {"a": fields.Str()}, location="query", duplicate_policy="reject"
            )
    with app.test_request_context("/?a=1&a=2"):
        assert parser.parse(
            {"a": fields.Str()}, location="query", duplicate_policy="last"
        ) == {"a": "2"}


def test_async_parse_enforces_policy():
    app = Flask(__name__)
    parser = FlaskParser(duplicate_policy="reject")

    @app.errorhandler(422)
    def handle_422(err):
        return jsonify(err.data["messages"]), 422

    @app.route("/query")
    async def query():
        return jsonify(
            await parser.async_parse({"a": fields.Str()}, location="query")
        )

    testapp = webtest.TestApp(app)
    res = testapp.get("/query?a=1&a=2", expect_errors=True)
    assert res.status_code == 422
    assert res.json["query"]["a"] == ["Duplicate parameter at occurrence 2."]
    assert testapp.get("/query?a=1").json == {"a": "1"}
