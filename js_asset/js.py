from __future__ import annotations

import copy
import json
import re
import warnings

from django.core.serializers.json import DjangoJSONEncoder
from django.forms.utils import flatatt
from django.templatetags.static import static
from django.utils.functional import lazy
from django.utils.html import format_html, json_script, mark_safe

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


class _JSONAsset(MediaAsset):
    """
    A ``<script>`` element whose content is data serialized as JSON. Like
    :class:`InlineStyle` its ``path`` is the content of the element.
    """

    element_template = "<script{attributes}>{path}</script>"

    def __init__(self, data, **attributes):
        # Copy the data: assets are hashable (``Media.merge`` relies on it), so
        # they must not change when the caller's dict does.
        super().__init__(copy.deepcopy(data), **attributes)

    @property
    def path(self):
        return self._serialize(self._path)

    @staticmethod
    def _serialize(data):
        # ``json_script`` escapes ``<``, ``>`` and ``&``, so the JSON cannot
        # close the element. ``DjangoJSONEncoder`` resolves lazy values, e.g.
        # ``static_lazy`` paths, at rendering time.
        return mark_safe(
            json_script(data)
            .removeprefix('<script type="application/json">')
            .removesuffix("</script>")
        )

    def __eq__(self, other):
        # Django < 6.2 compares ``path`` only, which would make the equality
        # depend on the order of the keys.
        return (
            self.__class__ is other.__class__
            and self._path == other._path
            and self.attributes == other.attributes
        )

    def __hash__(self):
        # ``__eq__`` compares the underlying dict order-insensitively, so the
        # hash must too -- see ``_canonical_hash``. Attributes are combined
        # like Django's ``MediaAsset.__hash__`` does; serializing them would
        # give equal attributes such as ``True`` and ``1`` different hashes.
        if self.attributes:
            return _canonical_hash(self._path) ^ hash(
                frozenset(self.attributes.items())
            )
        return _canonical_hash(self._path)

    def render(self, *, attrs=None, nonce=""):
        if nonce:
            warnings.warn(
                f"{self.__class__.__name__}.render(nonce=...) is deprecated, use"
                " render(attrs={'nonce': ...}) instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            attrs = {"nonce": nonce} | (attrs or {})
        # Django's ``MediaAsset.render(attrs=)`` doesn't exist on 5.2 and 6.0.
        return format_html(
            self.element_template,
            path=self.path,
            attributes=flatatt({**(attrs or {}), **self.attributes}),
        )

    def __str__(self):
        return self.render()


class JSON(_JSONAsset):
    def __init__(self, data, *, id="", **attributes):
        if id:
            attributes["id"] = id
        super().__init__(data, type="application/json", **attributes)

    @property
    def data(self):
        return self._path

    @property
    def id(self):
        return self.attributes.get("id", "")


_IMPORTMAP_KEYS = {"imports", "scopes", "integrity"}

# Paths which are used as they are instead of being passed through ``static()``:
# URLs with a scheme (the same check as Django's
# ``HashedFilesMixin.url_converter``), paths starting with ``/`` (including
# protocol-relative URLs), ``./`` or ``../``, and paths ending with ``/``.
# The latter are prefix mappings; storages cannot resolve those.
_URL_WITH_SCHEME = re.compile(r"^[a-z]+:")
_UNRESOLVED_PREFIXES = ("/", "./", "../")


def _resolve(path):
    path = str(path)  # Resolves lazy strings such as ``static_lazy`` paths.
    if (
        _URL_WITH_SCHEME.match(path)
        or path.startswith(_UNRESOLVED_PREFIXES)
        or path.endswith("/")
    ):
        return path
    return static(path)


def _is_full_importmap(imports):
    # Specifiers map to paths (strings), the top-level keys of a full import
    # map to dictionaries, so the two cannot be confused.
    return any(
        key in _IMPORTMAP_KEYS and isinstance(value, dict)
        for key, value in imports.items()
    )


class ImportMap(_JSONAsset):
    """
    An import map, rendered as ``<script type="importmap">``.

    ``imports`` maps module specifiers to paths, ``scopes`` maps URL prefixes
    to additional imports only used by modules loaded from those prefixes, and
    ``integrity`` maps URLs to integrity metadata. Relative paths in
    ``imports`` and ``scopes`` are passed through ``static()`` when rendering,
    URLs with a scheme, paths starting with ``/``, ``./`` or ``../`` and paths
    ending with ``/`` are used as they are.
    """

    element_template = '<script type="importmap"{attributes}>{path}</script>'

    def __init__(self, imports=None, *, scopes=None, integrity=None, **attributes):
        if (
            imports is not None
            and scopes is None
            and integrity is None
            and _is_full_importmap(imports)
        ):
            warnings.warn(
                "Passing a full import map to ImportMap() is deprecated, pass"
                " the imports and the scopes= and integrity= keyword arguments"
                " instead: ImportMap(imports, scopes=..., integrity=...).",
                DeprecationWarning,
                stacklevel=2,
            )
            data = imports
        else:
            data = {}
            if imports:
                data["imports"] = dict(imports)
            if scopes:
                data["scopes"] = {
                    scope: dict(scope_imports)
                    for scope, scope_imports in scopes.items()
                }
            if integrity:
                data["integrity"] = dict(integrity)
        super().__init__(data, **attributes)

    @classmethod
    def _from_data(cls, data, **attributes):
        importmap = cls.__new__(cls)
        _JSONAsset.__init__(importmap, data, **attributes)
        return importmap

    @property
    def path(self):
        # Copy, resolving the paths must not change the import map.
        data = dict(self._path)
        if "imports" in data:
            data["imports"] = {
                key: _resolve(path) for key, path in data["imports"].items()
            }
        if "scopes" in data:
            data["scopes"] = {
                scope: {key: _resolve(path) for key, path in scope_imports.items()}
                for scope, scope_imports in data["scopes"].items()
            }
        return self._serialize(data)

    def __or__(self, other):
        if not isinstance(other, ImportMap):
            return NotImplemented
        a, b = self._path, other._path
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
        return self._from_data(combined, **(self.attributes | other.attributes))
