"""Typed item container for spider output."""

from __future__ import annotations

from typing import Any, Optional


class Field:
    """A typed, validated field for :class:`Item`."""

    def __init__(
        self,
        type: Any = str,
        required: bool = False,
        default: Any = None,
        serializer: Optional[Any] = None,
    ):
        self.type = type
        self.required = required
        self.default = default
        self.serializer = serializer

    def clean(self, value: Any) -> Any:
        if value is None:
            value = self.default
        if value is None and self.required:
            raise ValueError("required field is missing")
        if value is not None and self.type is not Any and not isinstance(value, self.type):
            try:
                value = self.type(value)
            except Exception:  # noqa: BLE001
                pass
        return value


class ItemMeta(type):
    def __new__(mcls, name, bases, namespace):
        fields = {}
        for base in bases:
            fields.update(getattr(base, "_fields", {}))
        for key, value in list(namespace.items()):
            if isinstance(value, Field):
                fields[key] = value
        namespace["_fields"] = fields
        cls = super().__new__(mcls, name, bases, namespace)
        return cls


class Item(dict, metaclass=ItemMeta):
    """A dict subclass with optional typed :class:`Field` declarations.

    Subclass it and declare fields as class attributes::

        class Product(Item):
            title = Field(str, required=True)
            price = Field(float)

        p = Product(title="Widget", price="9.99")  # coerced to 9.99
    """

    _fields: dict[str, Field] = {}

    def __init__(self, *args, **kwargs):
        super().__init__()
        for key in self._fields:
            self[key] = self._fields[key].default
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def __setitem__(self, key, value):
        field = self._fields.get(key)
        if field is not None:
            value = field.clean(value)
        super().__setitem__(key, value)

    def to_dict(self) -> dict[str, Any]:
        return dict(self)
