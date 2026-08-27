import operator
from functools import reduce

from django import forms
from django.forms.utils import flatatt
from django.utils.html import format_html, mark_safe

from js_asset._compat import MediaAsset, Script, Stylesheet
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

    # -- Normalization ----------------------------------------------------

    # ``forms.Media.__init__`` calls these through ``self``, so a subclass can
    # override them. They only exist -- and are only reached -- on Django >=
    # 6.1; older versions keep js/css entries as given and ``_render_{js,css}``
    # wraps them at render time instead.
    #
    # Django 6.1 normalizes with ``isinstance(path, str)``, which swallows
    # html-safe strings: a ``SafeString`` such as
    # ``mark_safe('<script defer src="..."></script>')`` is a complete tag, but
    # being a ``str`` subclass it got turned into a ``Script`` and resolved
    # through ``static()`` (ticket #37262, fixed for 6.1.1). Normalizing with
    # the ``__html__`` predicate instead keeps such entries verbatim on 6.1 too.
    # ``Script``/``Stylesheet`` come from ``_compat``, so the wrapped output is
    # the same on every supported Django.
    #
    # This can only help media built *through* this class. Assets adopted from
    # a foreign ``forms.Media`` (``from_media``, ``__add__``, and Django's
    # widget ``media_property``, which always instantiates ``forms.Media``) are
    # already normalized by the time we see them.

    @staticmethod
    def _normalize_js(js):
        return [path if hasattr(path, "__html__") else Script(path) for path in js]

    @staticmethod
    def _normalize_css(css):
        return {
            medium: [
                path if hasattr(path, "__html__") else Stylesheet(path, media=medium)
                for path in paths
            ]
            for medium, paths in css.items()
        }

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

    # -- Access -----------------------------------------------------------

    def __getitem__(self, name):
        # Django's ``__getitem__`` hardcodes ``forms.Media``, so ``media["js"]``
        # -- reached from templates as ``{{ media.js }}``, and used by the admin
        # as ``{% csp_nonce_attr media.js %}`` -- would drop our type, and with
        # it the nonce and the import-map merging.
        return self.from_media(super().__getitem__(name), nonce=self.nonce)

    # -- Rendering --------------------------------------------------------

    def render(self, *, nonce=None, attrs=None):
        nonce = self._resolve_nonce(nonce, attrs)
        return mark_safe(
            "\n".join(filter(None, [*self._render_css(nonce), *self._render_js(nonce)]))
        )

    def render_css(self, *, attrs=None):
        return self._render_css(self._resolve_nonce(None, attrs))

    def render_js(self, *, attrs=None):
        # ``render_{css,js}`` are part of ``forms.Media``'s public API (and are
        # what Django's own ``render()`` calls), so they have to apply the nonce
        # and hoist import maps as well -- otherwise anything rendering the
        # media through them silently loses both. The ``attrs`` keyword only
        # exists on Django >= 6.2; accepting it keeps the signature compatible.
        return self._render_js(self._resolve_nonce(None, attrs))

    def _resolve_nonce(self, nonce, attrs):
        # ``attrs`` is accepted for compatibility with Django >= 6.2, whose
        # built-in CSP integration renders media via
        # ``media.render(attrs={"nonce": nonce})`` (see the ``csp_nonce_attr``
        # template tag). Only the nonce is honoured; the stored nonce is used
        # as a fallback, since templates call ``render()`` without arguments.
        if attrs and attrs.get("nonce") is not None:
            nonce = attrs["nonce"]
        if nonce is None:
            nonce = self.nonce
        if type(nonce) is not str:
            # Django's ``LazyNonce`` (the ``csp_nonce`` context value on >= 6.2)
            # is deliberately *falsy* until it is first read, so truth-testing
            # it -- as the rendering code below does -- would silently drop the
            # nonce. Resolve lazy nonces to a string here instead. Only do so
            # when there is something to render, so that rendering an empty
            # media does not generate a nonce (and add it to the CSP header).
            # ``isinstance`` is no use for the check: a lazy object reports the
            # wrapped value's class -- and evaluates itself while doing so.
            nonce = str(nonce) if any(self._js_lists) or any(self._css_lists) else ""
        return nonce

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
            # ``hasattr(item, "__html__")`` -- not ``isinstance(item, str)``:
            # ``SafeString`` is a ``str`` subclass, and html-safe strings such
            # as ``mark_safe("<script defer src=...></script>")`` are complete
            # tags which must render verbatim instead of being resolved through
            # ``static()``. Only bare paths are wrapped. (Django hit the same
            # trap in 6.1, fixed for 6.1.1 -- ticket #37262.)
            asset = item if hasattr(item, "__html__") else JS(item)
            rendered.append(self._render_asset(asset, nonce))
        return rendered

    def _render_css(self, nonce):
        rendered = []
        for medium in sorted(self._css):
            for item in self._css[medium]:
                # See ``_render_js`` on the ``__html__`` check.
                asset = item if hasattr(item, "__html__") else CSS(item, media=medium)
                rendered.append(self._render_asset(asset, nonce))
        return rendered

    @staticmethod
    def _render_asset(asset, nonce):
        if isinstance(asset, MediaAsset):
            if not nonce:
                return asset.__html__()
            # Inject the nonce ourselves rather than via MediaAsset.render(
            # attrs=), which only exists on Django >= 6.1. Rebuilding the tag
            # from ``element_template`` keeps output identical on every
            # supported Django (4.2 -> main), and ``flatatt`` sorts the
            # attributes so the nonce lands in the same place as Django's own.
            return format_html(
                asset.element_template,
                path=asset.path,
                attributes=flatatt({**asset.attributes, "nonce": nonce}),
            )
        if isinstance(asset, (ImportMap, JSON)):
            # Our own non-MediaAsset types take a ``nonce`` keyword.
            return asset.render(nonce=nonce)
        # Any other asset follows Django's plain ``__html__`` media contract
        # (an object that only knows how to render itself). Mirror
        # ``forms.Media``'s fallback so such assets keep working -- the nonce
        # cannot be threaded through, just as with stock Django.
        return asset.__html__()
