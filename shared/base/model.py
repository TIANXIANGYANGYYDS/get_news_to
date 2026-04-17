from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime
from typing import Any, TypeVar, get_args, get_origin

T = TypeVar("T", bound="ModelBase")


class ModelBase:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        kwargs: dict[str, Any] = {}
        for field in fields(cls):
            value = data.get(field.name)
            kwargs[field.name] = _coerce_value(field.type, value)
        return cls(**kwargs)



def _coerce_value(field_type: Any, value: Any) -> Any:
    if value is None:
        return None

    origin = get_origin(field_type)
    args = get_args(field_type)

    if origin is list and args:
        subtype = args[0]
        return [_coerce_value(subtype, item) for item in value]

    if origin is tuple and args:
        return tuple(_coerce_value(args[0], item) for item in value)

    if origin is not None and args and type(None) in args:
        concrete = [arg for arg in args if arg is not type(None)][0]
        return _coerce_value(concrete, value)

    if isinstance(field_type, type) and issubclass(field_type, ModelBase) and isinstance(value, dict):
        return field_type.from_dict(value)

    if field_type is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)

    if isinstance(field_type, type):
        try:
            from enum import Enum
            if issubclass(field_type, Enum):
                return field_type(value)
        except Exception:
            pass

    return value
