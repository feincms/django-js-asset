from __future__ import annotations

import copy
import re
import warnings

from django.forms.utils import flatatt
from django.templatetags.static import static
from django.utils.functional import lazy
from django.utils.html import format_html, html_safe, json_script, mark_safe

from js_asset._compat import MediaAsset, Script, Stylesheet


__all__ = [
    "CSS",
    "JS",
    "JSON",
    "ImportMap",
    "InlineStyle",
    "MediaAsset",
    "RemovedInDjangoJsAsset60Warning",
    "Script",
    "Stylesheet",
    "static",
    "static_lazy",
]


static_lazy = lazy(static, str)


class InlineStyle(MediaAsset):
    """
    An inline ``<style>`` block. Unlike :class:`Stylesheet` its ``path`` is the
    CSS source itself (rendered verbatim, never resolved through ``static()``),
    so it has no Django counterpart and stays a small dedicated
    :class:`~django.forms.widgets.MediaAsset` subclass.
    """

    element_template = "<style{attributes}>{path}</style>"

    def __init__(self, css, **attributes):
        # ``<style>`` is a raw text element, so nothing inside it can be
        # escaped -- which also means the CSS is only safe as long as it cannot
        # close the element. That takes exactly one sequence (HTML spec:
        # "</style", ASCII case-insensitive), so reject it instead of shipping
        # broken markup.
        if "</style" in str(css).lower():
            raise ValueError("Inline CSS must not contain '</style'.")
        super().__init__(css, **attributes)

    @property
    def path(self):
        # Verbatim, not escaped: HTML character references are *not* decoded
        # inside a raw text element, so an escaped ``&gt;`` or ``&quot;`` would
        # not be read back as ``>`` or ``"`` -- it would simply break the rule
        # (``nav &gt; a`` matches nothing). See ``__init__`` on why this is safe.
        return mark_safe(self._path)


class RemovedInDjangoJsAsset60Warning(DeprecationWarning):
    """
    Warns about features which will be removed in django-js-asset 6.0. A
    separate category so that projects can turn exactly these into errors.
    """


class _ProducesAsset(type):
    """
    Metaclass turning the deprecated ``JS``/``CSS`` into factories: calling
    them returns a Django asset (``Script``/``Stylesheet``/``InlineStyle``) so
    they share ``forms.Media.merge`` buckets -- and dedup -- with Django's own
    assets and with bare path strings. ``isinstance(x, JS)`` keeps answering
    truthfully by delegating to the produced type(s).
    """

    def __call__(cls, *args, **kwargs):
        return cls._produce(*args, **kwargs)

    def __instancecheck__(cls, instance):
        _deprecated(cls._isinstance_message, stacklevel=3)
        return isinstance(instance, cls._produces)

    def __subclasscheck__(cls, subclass):
        _deprecated(cls._isinstance_message, stacklevel=3)
        return issubclass(subclass, cls._produces)


def _deprecated(message, stacklevel=4):
    # Called from ``_produce``, which is called from ``_ProducesAsset.__call__``.
    warnings.warn(message, RemovedInDjangoJsAsset60Warning, stacklevel=stacklevel)


def _legacy_attrs(name, args, attributes):
    # The attributes dict of 4.x and older, ``Script``/``Stylesheet`` take the
    # attributes as keyword arguments.
    if len(args) > 1:
        raise TypeError(f"{name}() takes at most one attributes dict.")
    attrs = attributes.pop("attrs", None)
    if args:
        attrs = args[0]
    return {**(attrs or {}), **attributes}


class JS(metaclass=_ProducesAsset):
    """
    Deprecated, produces a :class:`Script`. Use ``Script(src, **attributes)``.
    """

    _produces = Script
    _isinstance_message = (
        "JS is deprecated and will be removed in django-js-asset 6.0, check"
        " against Script instead."
    )

    @staticmethod
    def _produce(src, *args, **attributes):
        _deprecated(
            "JS() is deprecated and will be removed in django-js-asset 6.0, use"
            " Script(src, **attrs) instead (from django.forms on Django >= 5.2,"
            " from js_asset otherwise)."
        )
        return Script(src, **_legacy_attrs("JS", args, attributes))


class CSS(metaclass=_ProducesAsset):
    """
    Deprecated, produces a :class:`Stylesheet` (or an :class:`InlineStyle`
    with ``inline=True``). Use ``Stylesheet(href, media="all", **attributes)``;
    ``CSS()`` adds ``media="all"`` when no media is given, ``Stylesheet()``
    doesn't.
    """

    _produces = (Stylesheet, InlineStyle)
    _isinstance_message = (
        "CSS is deprecated and will be removed in django-js-asset 6.0, check"
        " against Stylesheet or InlineStyle instead."
    )

    @staticmethod
    def _produce(href, *args, inline=False, **attributes):
        if inline:
            _deprecated(
                "CSS(..., inline=True) is deprecated and will be removed in"
                " django-js-asset 6.0, use InlineStyle(css, **attrs) instead."
            )
        else:
            _deprecated(
                "CSS() is deprecated and will be removed in django-js-asset 6.0,"
                ' use Stylesheet(href, media="all", **attrs) instead (from'
                " django.forms on Django >= 6.1, from js_asset otherwise). Pass"
                " the media explicitly: Stylesheet() has no default media, and"
                ' media="all" is what de-duplicates it against paths in'
                ' css={"all": [...]}.'
            )
        if args:
            attributes["media"], *args = args
        attributes = _legacy_attrs("CSS", args, attributes)
        attributes.setdefault("media", "all")
        if inline:
            return InlineStyle(href, **attributes)
        return Stylesheet(href, **attributes)


def _json_content(data):
    # ``json_script`` escapes ``<``, ``>`` and ``&``, so the JSON cannot close
    # the element. ``DjangoJSONEncoder`` resolves lazy values, e.g.
    # ``static_lazy`` paths, at rendering time.
    return mark_safe(
        json_script(data)
        .removeprefix('<script type="application/json">')
        .removesuffix("</script>")
    )


class JSON(MediaAsset):
    """
    A ``<script type="application/json">`` data block. Like
    :class:`InlineStyle` its ``path`` is the content of the element.
    """

    element_template = "<script{attributes}>{path}</script>"

    def __init__(self, data, *, id="", **attributes):
        if id:
            attributes["id"] = id
        # Copy the data: assets are hashable (``Media.merge`` relies on it), so
        # they must not change when the caller's dict does.
        super().__init__(copy.deepcopy(data), type="application/json", **attributes)

    @property
    def data(self):
        # A copy, see ``__init__``.
        return copy.deepcopy(self._path)

    @property
    def id(self):
        return self.attributes.get("id", "")

    @property
    def path(self):
        return _json_content(self._path)

    def __eq__(self, other):
        # Django 5.2 and 6.0 compare ``path`` only, which would make the equality
        # depend on the order of the keys.
        return (
            self.__class__ is other.__class__
            and self._path == other._path
            and self.attributes == other.attributes
        )

    def __hash__(self):
        # Equal objects need equal hashes, distinct ones don't. Hashing the
        # data consistently with ``__eq__`` (order-insensitive, ``1 == 1.0``)
        # isn't worth it, data blocks are few and mostly differ in their id.
        return hash(frozenset(self.attributes.items()))

    def render(self, *, attrs=None, nonce=""):
        if nonce:
            warnings.warn(
                f"{self.__class__.__name__}.render(nonce=...) is deprecated, use"
                " render(attrs={'nonce': ...}) instead.",
                RemovedInDjangoJsAsset60Warning,
                stacklevel=2,
            )
            attrs = {"nonce": nonce} | (attrs or {})
        # Django's ``MediaAsset.render(attrs=)`` doesn't exist on 5.2 and 6.0.
        # Raise on conflicting attributes like it does.
        if attrs and (conflicts := attrs.keys() & self.attributes.keys()):
            raise ValueError(
                f"{self.__class__.__qualname__} has conflicting attributes: "
                + ", ".join(sorted(conflicts))
            )
        return format_html(
            self.element_template,
            path=self.path,
            attributes=flatatt((attrs or {}) | self.attributes),
        )

    def __str__(self):
        return self.render()


_IMPORTMAP_KEYS = {"imports", "scopes", "integrity"}

# Paths which are used as they are instead of being passed through ``static()``:
# URLs with a scheme (the same check as Django's
# ``HashedFilesMixin.url_converter``) and paths starting with ``/`` (including
# protocol-relative URLs). Everything else is relative to the static files;
# that includes prefix mappings ending with ``/``, which ``static()`` resolves
# without hashing.
_URL_WITH_SCHEME = re.compile(r"^[a-z]+:")


def _resolve(path):
    path = str(path)  # Resolves lazy strings such as ``static_lazy`` paths.
    if _URL_WITH_SCHEME.match(path) or path.startswith("/"):
        return path
    return static(path)


def _is_full_importmap(imports):
    # Specifiers map to paths (strings), the top-level keys of a full import
    # map to dictionaries, so the two cannot be confused.
    return any(
        key in _IMPORTMAP_KEYS and isinstance(value, dict)
        for key, value in imports.items()
    )


@html_safe
class ImportMap:
    """
    An import map, rendered as ``<script type="importmap">``.

    ``imports`` maps module specifiers to paths, ``scopes`` maps URL prefixes
    to additional imports only used by modules loaded from those prefixes, and
    ``integrity`` maps URLs to integrity metadata. Relative paths in
    ``imports`` and ``scopes`` are passed through ``static()`` when rendering,
    URLs with a scheme and paths starting with ``/`` are used as they are.
    Scope prefixes and the URLs in ``integrity`` are never resolved,
    ``integrity`` needs the final URLs.

    Import maps aren't media assets: They are passed to
    ``Media(importmap=...)`` instead of being added to ``js`` lists.
    """

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
                RemovedInDjangoJsAsset60Warning,
                stacklevel=2,
            )
            data = imports
        else:
            data = {}
            if imports:
                data["imports"] = imports
            if scopes:
                data["scopes"] = scopes
            if integrity:
                data["integrity"] = integrity
        if "type" in attributes:
            raise ValueError("ImportMap doesn't accept a type attribute.")
        # Copy the data, import maps must not change when the caller's dict does.
        self._data = copy.deepcopy(data)
        self.attributes = attributes

    @classmethod
    def _from_data(cls, data, **attributes):
        importmap = cls.__new__(cls)
        importmap._data = data
        importmap.attributes = attributes
        return importmap

    def __eq__(self, other):
        return (
            isinstance(other, ImportMap)
            and self._data == other._data
            and self.attributes == other.attributes
        )

    # Import maps aren't media assets, ``Media.merge`` doesn't need them to be
    # hashable.
    __hash__ = None

    def __repr__(self):
        return f"{type(self).__qualname__}({self._data!r})"

    def render(self, *, attrs=None, nonce=""):
        if nonce:
            warnings.warn(
                "ImportMap.render(nonce=...) is deprecated, use"
                " render(attrs={'nonce': ...}) instead.",
                RemovedInDjangoJsAsset60Warning,
                stacklevel=2,
            )
            attrs = {"nonce": nonce} | (attrs or {})
        # Like Django's ``MediaAsset.render(attrs=)``. ``type`` is always
        # ``importmap``, a second one would be ignored by browsers.
        if attrs and (conflicts := attrs.keys() & {"type", *self.attributes}):
            raise ValueError(
                "ImportMap has conflicting attributes: " + ", ".join(sorted(conflicts))
            )
        # Copy, resolving the paths must not change the import map.
        data = dict(self._data)
        if "imports" in data:
            data["imports"] = {
                key: _resolve(path) for key, path in data["imports"].items()
            }
        if "scopes" in data:
            data["scopes"] = {
                scope: {key: _resolve(path) for key, path in scope_imports.items()}
                for scope, scope_imports in data["scopes"].items()
            }
        return format_html(
            '<script type="importmap"{}>{}</script>',
            flatatt((attrs or {}) | self.attributes),
            _json_content(data),
        )

    def __str__(self):
        return self.render()

    def __or__(self, other):
        if not isinstance(other, ImportMap):
            return NotImplemented
        a, b = self._data, other._data
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
