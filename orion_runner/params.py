"""ORION Runner - param model.

Portions adapted from higgsfield (https://github.com/higgsfield-ai/higgsfield),
Copyright (c) higgsfield.ai authors, licensed under Apache-2.0 (see
third_party/higgsfield/LICENSE and THIRD_PARTY.md). Changes made by ORION.
"""
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple

NONE_TYPE = type(None)
_TYPE_BUILTIN = type

_SCALAR_TYPES = (str, int, float, bool, NONE_TYPE)
_OPTION_TYPES = (str, int, float, bool, NONE_TYPE)


@dataclass(frozen=True, eq=True)
class Param:
    name: str
    default: Any = None
    description: Optional[str] = None
    required: bool = False
    type: Optional[type] = None
    options: Optional[Tuple[Any, ...]] = None

    @classmethod
    def from_values(cls, name, default=None, description=None, required=False,
                    type=None, options=None):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("param name must be a non-empty string")
        if options is not None:
            options = tuple(options)
            if not all(isinstance(o, _OPTION_TYPES) for o in options):
                raise ValueError(f"param {name!r}: options must be scalar values")
        if type is not None and not isinstance(type, _TYPE_BUILTIN):
            raise ValueError(f"param {name!r}: type must be a class, got {type!r}")
        if default is not None and type is not None:
            if isinstance(default, bool):
                if type is not bool and type is not int:
                    raise ValueError(f"param {name!r}: default bool not valid for {type.__name__}")
            elif not isinstance(default, type):
                raise ValueError(f"param {name!r}: default {default!r} is not {getattr(type, '__name__', type)}")
        return cls(name=name, default=default, description=description,
                   required=bool(required), type=type, options=options)

    def to_schema(self) -> dict:
        return {
            "name": self.name,
            "default": self.default,
            "description": self.description,
            "required": bool(self.required),
            "type": getattr(self.type, "__name__", None),
            "options": list(self.options) if self.options else None,
        }

    def coerce(self, value: Any) -> Any:
        if self.type is None or value is None:
            return value
        if isinstance(value, self.type):
            result = value
        elif self.type is bool and isinstance(value, str):
            lowered = value.strip().lower()
            if lowered not in ("1", "0", "true", "false", "yes", "no", "on", "off"):
                raise ValueError(f"param {self.name!r}: cannot coerce {value!r} to bool")
            result = lowered in ("1", "true", "yes", "on")
        elif self.type is int:
            if isinstance(value, str):
                result = int(value)
            elif isinstance(value, bool):
                result = int(value)
            else:
                result = value
        elif self.type is float:
            if isinstance(value, str):
                result = float(value)
            elif isinstance(value, (int, bool)):
                result = float(value)
            else:
                result = value
        elif self.type is str:
            result = str(value)
        else:
            raise ValueError(f"param {self.name!r}: {value!r} is not compatible with {self.type.__name__}")
        if self.options is not None and result not in self.options:
            raise ValueError(f"param {self.name!r}: {value!r} is not one of {self.options}")
        return result

    def as_dict(self) -> dict:
        return self.to_schema()


def schema_for(params) -> list:
    return [p.to_schema() for p in params]