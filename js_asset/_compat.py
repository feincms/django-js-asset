"""
Django's object-based media assets (``MediaAsset``, ``Script``,
``Stylesheet``) appeared gradually:

* ``MediaAsset`` and ``Script`` -- Django 5.2
* ``Stylesheet``, ``MediaAsset.render(*, attrs=)`` and attribute-aware
  ``__eq__``/``__hash__`` (path *and* attributes) -- Django 6.1

``js_asset`` supports Django >= 4.2, so this module backports whatever the
running Django lacks. Backports follow the **6.1** contract (attribute-aware
equality + ``render(attrs=)``) so the support floor matches the design target.
On 5.2 / 6.0 we use Django's *native* ``MediaAsset``, which still dedups on the
path alone -- that looser middle is intentional and accepted.
"""

import django
from django.forms.utils import flatatt
from django.templatetags.static import static
from django.utils.html import format_html, html_safe


__all__ = ["MediaAsset", "Script", "Stylesheet"]


if django.VERSION >= (5, 2):
    from django.forms.widgets import MediaAsset, Script
else:

    @html_safe
    class MediaAsset:
        element_template = "{path}"

        def __init__(self, path, **attributes):
            self._path = path
            self.attributes = attributes

        def __eq__(self, other):
            # 6.1 contract: identity is path *and* attributes, plus the
            # bare-string shortcut Django relies on in ``Media.merge``.
            return (
                self.__class__ is other.__class__
                and self._path == other._path
                and self.attributes == other.attributes
            ) or (isinstance(other, str) and self._path == other)

        def __hash__(self):
            if self.attributes:
                return hash(self._path) ^ hash(frozenset(self.attributes.items()))
            return hash(self._path)

        def render(self, *, attrs=None):
            if (
                attrs
                and self.attributes
                and (conflicts := attrs.keys() & self.attributes.keys())
            ):
                conflicts = ", ".join(sorted(conflicts))
                raise ValueError(
                    f"{self.__class__.__qualname__} has conflicting attributes: "
                    f"{conflicts}"
                )
            return format_html(
                self.element_template,
                path=self.path,
                attributes=flatatt({**(attrs or {}), **self.attributes}),
            )

        def __str__(self):
            return self.render()

        def __repr__(self):
            return f"{type(self).__qualname__}({self._path!r})"

        @property
        def path(self):
            """
            Ensure an absolute path.
            Relative paths are resolved via the {% static %} template tag.
            """
            if self._path.startswith(("http://", "https://", "/")):
                return self._path
            return static(self._path)

    class Script(MediaAsset):
        element_template = '<script src="{path}"{attributes}></script>'

        def __init__(self, src, **attributes):
            # Alter the signature to allow src to be passed as a keyword argument.
            super().__init__(src, **attributes)


if django.VERSION >= (6, 1):
    from django.forms.widgets import Stylesheet
else:

    class Stylesheet(MediaAsset):
        element_template = '<link href="{path}"{attributes}>'

        def __init__(self, href, **attributes):
            super().__init__(href, rel="stylesheet", **attributes)
