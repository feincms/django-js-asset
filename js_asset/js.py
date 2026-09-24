from __future__ import annotations

import copy
import json
import warnings
from dataclasses import dataclass, field
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.forms.utils import flatatt
from django.templatetags.static import static
from django.utils.functional import lazy
from django.utils.html import html_safe, json_script, mark_safe

from js_asset._compat import MediaAsset, Script, Stylesheet


__all__ = [
    "CSS",
    "JS",
    "JSON",
    "ImportMap",
    "InlineStyle",
    "MediaAsset",
    "Script",
    "Stylesheet",
    "static",
    "static_lazy",
]


static_lazy = lazy(static, str)


def _canonical_hash(data):
    # Hash an order-insensitive canonical form so the hash stays consistent
    # with dict equality (``a == b`` must imply ``hash(a) == hash(b)``).
    # ``DjangoJSONEncoder`` resolves lazy values, e.g. ``static_lazy`` paths.
    return hash(json.dumps(data, sort_keys=True, cls=DjangoJSONEncoder))


class InlineStyle(MediaAsset):
    """
    An inline ``<style>`` block. Unlike :class:`Stylesheet` its ``path`` is the
    CSS source itself (rendered verbatim, never resolved through ``static()``),
    so it has no Django counterpart and stays a small dedicated
    :class:`~django.forms.widgets.MediaAsset` subclass.
    """

    element_template = "<style{attributes}>{path}</style>"

    def __init__(self, css, *, media="all", **attributes):
        # ``<style>`` is a raw text element, so nothing inside it can be
        # escaped -- which also means the CSS is only safe as long as it cannot
        # close the element. That takes exactly one sequence (HTML spec:
        # "</style", ASCII case-insensitive), so reject it instead of shipping
        # broken markup.
        if "</style" in str(css).lower():
            raise ValueError("Inline CSS must not contain '</style'.")
        super().__init__(css, media=media, **attributes)

    @property
    def path(self):
        # Verbatim, not escaped: HTML character references are *not* decoded
        # inside a raw text element, so an escaped ``&gt;`` or ``&quot;`` would
        # not be read back as ``>`` or ``"`` -- it would simply break the rule
        # (``nav &gt; a`` matches nothing). See ``__init__`` on why this is safe.
        return mark_safe(self._path)


class _ProducesAsset(type):
    """
    Metaclass turning ``JS``/``CSS`` into factories: calling them returns a
    Django asset (``Script``/``Stylesheet``/``InlineStyle``) so they share
    ``forms.Media.merge`` buckets -- and dedup -- with Django's own assets and
    with bare path strings. ``isinstance(x, JS)`` keeps answering truthfully by
    delegating to the produced type(s).
    """

    def __call__(cls, *args, **kwargs):
        return cls._produce(*args, **kwargs)

    def __instancecheck__(cls, instance):
        return isinstance(instance, cls._produces)

    def __subclasscheck__(cls, subclass):
        return issubclass(subclass, cls._produces)


class JS(metaclass=_ProducesAsset):
    _produces = Script

    @staticmethod
    def _produce(src, attrs=None):
        return Script(src, **(attrs or {}))


class CSS(metaclass=_ProducesAsset):
    _produces = (Stylesheet, InlineStyle)

    @staticmethod
    def _produce(src, media="all", *, inline=False):
        if inline:
            return InlineStyle(src, media=media)
        return Stylesheet(src, media=media)


@html_safe
@dataclass(eq=True)
class JSON:
    data: dict[str, Any]
    id: str | None = field(default="", kw_only=True)

    def __hash__(self):
        # ``__eq__`` (dataclass) compares ``data`` order-insensitively, so the
        # hash must too -- see ``_canonical_hash``.
        return hash((_canonical_hash(self.data), self.id))

    def render(self, *, attrs=None, nonce=""):
        # A type="application/json" block is data, not executed JavaScript, so
        # it is not governed by CSP and needs no nonce. ``attrs`` is accepted
        # for compatibility with ``MediaAsset.render()`` (whose callers pass
        # the nonce that way) and ignored as well.
        return json_script(self.data, self.id)

    def __str__(self):
        return self.render()


@html_safe
class ImportMap:
    def __init__(self, importmap):
        # Copy the data: import maps are hashable (``Media.merge`` relies on
        # it), so they must not change when the caller's dict does.
        self._importmap = copy.deepcopy(importmap)

    def __eq__(self, other):
        return isinstance(other, ImportMap) and self._importmap == other._importmap

    def __hash__(self):
        # ``__eq__`` compares the underlying dict order-insensitively, so the
        # hash must too -- see ``_canonical_hash``.
        return _canonical_hash(self._importmap)

    def __bool__(self):
        return bool(self._importmap)

    def render(self, *, attrs=None, nonce=""):
        # ``attrs`` matches ``MediaAsset.render()``; ``nonce`` is kept for
        # backwards compatibility.
        if self:
            attrs = ({"nonce": nonce} if nonce else {}) | (attrs or {})
            html = json_script(self._importmap).removeprefix(
                '<script type="application/json">'
            )
            return mark_safe(f'<script type="importmap"{flatatt(attrs)}>{html}')
        return ""

    def __str__(self):
        return self.render()

    def update(self, other):
        warnings.warn(
            "ImportMap.update() is deprecated, import maps will become immutable."
            " Use map1 | map2 or map1 |= map2 instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if isinstance(other, ImportMap):
            other = other._importmap

        if imports := other.get("imports"):
            self._importmap.setdefault("imports", {}).update(imports)
        if integrity := other.get("integrity"):
            self._importmap.setdefault("integrity", {}).update(integrity)
        if scopes := other.get("scopes"):
            for scope, imports in scopes.items():
                self._importmap.setdefault("scopes", {}).setdefault(scope, {}).update(
                    imports
                )

    def __or__(self, other):
        if not isinstance(other, ImportMap):
            return NotImplemented
        a, b = self._importmap, other._importmap
        combined = {}
        for key in ("imports", "integrity"):
            if key in a or key in b:
                combined[key] = a.get(key, {}) | b.get(key, {})
        if "scopes" in a or "scopes" in b:
            scopes = a.get("scopes", {}), b.get("scopes", {})
            combined["scopes"] = {
                scope: scopes[0].get(scope, {}) | scopes[1].get(scope, {})
                for scope in scopes[0] | scopes[1]
            }
        return self.__class__(combined)
