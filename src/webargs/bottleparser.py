"""Bottle request argument parsing module.

Example: ::

    from bottle import route, run
    from marshmallow import fields
    from webargs.bottleparser import use_args

    hello_args = {"name": fields.Str(load_default="World")}


    @route("/", method="GET", apply=use_args(hello_args))
    def index(args):
        return "Hello " + args["name"]


    if __name__ == "__main__":
        run(debug=True)
"""

import json

import bottle

from webargs import core


class BottleParser(core.Parser[bottle.Request]):
    """Bottle.py request argument parser."""

    def _handle_invalid_json_error(self, error, req, *args, **kwargs):
        raise bottle.HTTPError(
            status=400, body={"json": ["Invalid JSON body."]}, exception=error
        )

    def _raw_load_json(self, req):
        """Read a json payload from the request."""
        content_type = core.get_mimetype(req.content_type or "")
        if not (
            core.is_json(req.content_type)
            or content_type == "application/json-rpc"
        ):
            return core.missing
        body = req.body.read()
        if not body:
            return core.missing
        try:
            payload = core.parse_json_with_repetitions(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._handle_invalid_json_error(exc, req)
            return core.missing
        # Bottle does not distinguish an empty body from a body containing
        # JSON null before the body is consumed; preserve its historical
        # treatment of both as "no JSON body".
        if payload.value is None:
            return core.missing
        return payload

    def load_querystring(self, req, schema):
        """Return query params from the request as a MultiDictProxy."""
        return self._makeproxy(req.query, schema)

    def load_form(self, req, schema):
        """Return form values from the request as a MultiDictProxy."""
        # For consistency with other parsers' behavior, don't attempt to
        #  parse if content-type is mismatched.
        #  TODO: Make this check more specific
        if core.is_json(req.content_type):
            return core.missing
        return self._makeproxy(req.forms, schema)

    def load_headers(self, req, schema):
        """Return headers from the request as a MultiDictProxy."""
        return self._makeproxy(req.headers, schema)

    def load_cookies(self, req, schema):
        """Return cookies from the request."""
        return req.cookies

    def load_files(self, req, schema):
        """Return files from the request as a MultiDictProxy."""
        return self._makeproxy(req.files, schema)

    def handle_error(self, error, req, schema, *, error_status_code, error_headers):
        """Handles errors during parsing. Aborts the current request with a
        400 error.
        """
        status_code = error_status_code or self.DEFAULT_VALIDATION_STATUS
        raise bottle.HTTPError(
            status=status_code,
            body=error.messages,
            headers=error_headers,
            exception=error,
        )

    def get_default_request(self):
        """Override to use bottle's thread-local request object by default."""
        return bottle.request


parser = BottleParser()
use_args = parser.use_args
use_kwargs = parser.use_kwargs
