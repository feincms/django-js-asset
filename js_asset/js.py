from __future__ import annotations

import copy
import re

from django.forms.utils import flatatt
from django.templatetags.static import static
from django.utils.functional import lazy
from django.utils.html import format_html, html_safe, json_script, mark_safe

from js_asset._compat import MediaAsset, Script, Stylesheet


__all__ = [
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

    def render(self, *, attrs=None):
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
        # Specifiers map to paths, so a dictionary is a full import map, which
        # ImportMap() doesn't take anymore. It would render as garbage.
        if imports and any(isinstance(value, dict) for value in imports.values()):
            raise TypeError(
                "ImportMap() takes the imports, pass scopes= and integrity= as"
                " keyword arguments: ImportMap(imports, scopes=..., integrity=...)."
            )
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

    def render(self, *, attrs=None):
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
