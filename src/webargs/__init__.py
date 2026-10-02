from __future__ import annotations

# Make marshmallow's validation functions importable from webargs
from marshmallow import validate
from marshmallow.utils import missing

from webargs import fields
from webargs.core import DuplicateValuePolicy, ParameterCardinality, ValidationError

__all__ = (
    "DuplicateValuePolicy",
    "ParameterCardinality",
    "ValidationError",
    "fields",
    "missing",
    "validate",
)
