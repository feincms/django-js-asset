import operator
from functools import reduce

from django import forms
from django.utils.html import mark_safe

from js_asset.js import CSS, JS, JSON, ImportMap


__all__ = ["Media"]


class Media(forms.Media):
    """
    A ``forms.Media`` subclass with two extra abilities:

    * It merges all :class:`~js_asset.js.ImportMap` objects found in its assets
      into a single ``<script type="importmap">`` tag, rendered before any
      other script. This avoids the need for a global importmap which is always
      the same regardless of the assets actually required by the current code
      path.
    * It applies a (request-scoped) CSP ``nonce`` to the rendered tags.

    Because it implements both ``__add__`` and ``__radd__`` it preserves its
    type -- and the nonce -- when combined with other media from either side,
    so it survives the merging Django performs while collecting the media of
    forms and widgets. A plain ``forms.Media`` would silently swallow it when
    it ended up on the right-hand side of an addition.
    """

    def __init__(self, media=None, *, nonce="", css=None, js=None):
        self.nonce = nonce
        super().__init__(media=media, css=css, js=js)

    @classmethod
    def from_media(cls, media, *, nonce=""):
        """
        Wrap an existing ``forms.Media`` instance (e.g. ``form.media``), keeping
        its assets and optionally attaching a nonce.

        Useful when you cannot control how the media was created -- note that
        ``Media(form.media)`` does *not* work, because ``forms.Media`` copies
        assets from a media *definition* (with ``css``/``js`` attributes), not
        from a media *instance*.
        """
        clone = cls(nonce=nonce)
        clone._css_lists = media._css_lists[:]
        clone._js_lists = media._js_lists[:]
        return clone

    def with_nonce(self, nonce):
        """Return a copy of this media carrying the given CSP nonce."""
        return self.from_media(self, nonce=nonce)

    # -- Addition ---------------------------------------------------------

    def _combine(self, first, second):
        combined = Media(
            nonce=getattr(first, "nonce", "") or getattr(second, "nonce", "")
        )
        combined._css_lists = first._css_lists[:]
        combined._js_lists = first._js_lists[:]
        for item in second._css_lists:
            if item and item not in combined._css_lists:
                combined._css_lists.append(item)
        for item in second._js_lists:
            if item and item not in combined._js_lists:
                combined._js_lists.append(item)
        return combined

    def __add__(self, other):
        if not isinstance(other, forms.Media):
            return NotImplemented
        return self._combine(self, other)

    def __radd__(self, other):
        if not isinstance(other, forms.Media):
            return NotImplemented
        return self._combine(other, self)

    # -- Rendering --------------------------------------------------------

    def render(self, *, nonce=None, attrs=None):
        # ``attrs`` is accepted for compatibility with Django >= 6.2, whose
        # built-in CSP integration renders media via
        # ``media.render(attrs={"nonce": nonce})`` (see the ``csp_nonce_attr``
        # template tag). Only the nonce is honoured; the stored nonce is used
        # as a fallback, since templates call ``render()`` without arguments.
        if attrs and attrs.get("nonce"):
            nonce = attrs["nonce"]
        if nonce is None:
            nonce = self.nonce
        return mark_safe(
            "\n".join(filter(None, [*self._render_css(nonce), *self._render_js(nonce)]))
        )

    def _render_js(self, nonce):
        importmap = reduce(
            operator.or_,
            (asset for asset in self._js if isinstance(asset, ImportMap)),
            ImportMap({}),
        )
        rendered = []
        if importmap._importmap:
            rendered.append(importmap.render(nonce=nonce))
        for item in self._js:
            if isinstance(item, ImportMap):
                continue
            asset = JS(item) if isinstance(item, str) else item
            rendered.append(self._render_asset(asset, nonce))
        return rendered

    def _render_css(self, nonce):
        rendered = []
        for medium in sorted(self._css):
            for item in self._css[medium]:
                asset = CSS(item, media=medium) if isinstance(item, str) else item
                rendered.append(self._render_asset(asset, nonce))
        return rendered

    @staticmethod
    def _render_asset(asset, nonce):
        if isinstance(asset, (CSS, JS, JSON, ImportMap)):
            return asset.render(nonce=nonce)
        # Django >= 6.2 wraps bare paths in MediaAsset objects which render via
        # an ``attrs`` mapping instead of a ``nonce`` keyword.
        return asset.render(attrs={"nonce": nonce} if nonce else None)
