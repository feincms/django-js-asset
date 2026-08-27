from unittest import skipIf

from django.forms import Media as DjangoMedia
from django.test import TestCase
from django.utils.functional import SimpleLazyObject, empty
from django.utils.html import html_safe
from django.utils.safestring import mark_safe

from js_asset import CSS, JS, JSON, ImportMap, Media, Script, Stylesheet


try:  # Django >= 6.1
    from django.utils.csp import LazyNonce as DjangoLazyNonce, nonce_attr
except ImportError:
    DjangoLazyNonce = nonce_attr = None


@html_safe
class HTMLOnlyAsset:
    """
    A media asset using Django's plain ``__html__`` contract -- not a
    ``MediaAsset`` and not one of our ``ImportMap``/``JSON`` types. Stock
    ``forms.Media`` renders such assets via ``__html__()``.
    """

    def __init__(self, markup):
        self._markup = markup

    def __str__(self):
        return self._markup


# Django 6.1 normalizes *every* js/css string -- html-safe ones included --
# into ``Script``/``Stylesheet`` inside ``forms.Media.__init__`` (ticket #37262,
# fixed on the 6.1.x branch for 6.1.1). Our ``Media`` overrides the normalizers
# so media built through *our* class is unaffected, but assets adopted from a
# foreign ``forms.Media`` arrive already mangled. This probe marks that window.
_PROBE = mark_safe('<script src="/probe.js"></script>')
DJANGO_KEEPS_HTML_SAFE_STRINGS = str(DjangoMedia(js=[_PROBE])) == _PROBE


HTML_SAFE_JS = mark_safe('<script defer src="https://example.org/asset.js"></script>')
HTML_SAFE_CSS = mark_safe(
    '<link href="https://example.org/asset.css" rel="stylesheet">'
)

# (label, asset, rendering without a nonce, rendering with nonce="n0nce").
#
# One row per kind of asset a ``Media`` can carry. Add a row whenever a new
# asset kind appears -- this is the guard against a rendering branch (such as
# the "is it a bare path?" test in ``Media._render_js``/``._render_css``)
# quietly mishandling one of them.
JS_ASSETS = [
    (
        "bare path string",
        "app.js",
        '<script src="/static/app.js"></script>',
        '<script src="/static/app.js" nonce="n0nce"></script>',
    ),
    (
        "JS factory",
        JS("app.js"),
        '<script src="/static/app.js"></script>',
        '<script src="/static/app.js" nonce="n0nce"></script>',
    ),
    (
        "JS factory with attributes",
        JS("app.js", {"type": "module"}),
        '<script src="/static/app.js" type="module"></script>',
        '<script src="/static/app.js" nonce="n0nce" type="module"></script>',
    ),
    (
        "Script object",
        Script("app.js"),
        '<script src="/static/app.js"></script>',
        '<script src="/static/app.js" nonce="n0nce"></script>',
    ),
    (
        "JSON block",
        JSON({"a": 1}, id="cfg"),
        # Data, not executed script: no nonce either way.
        '<script id="cfg" type="application/json">{"a": 1}</script>',
        '<script id="cfg" type="application/json">{"a": 1}</script>',
    ),
    (
        "ImportMap",
        ImportMap({"imports": {"a": "/static/a.js"}}),
        '<script type="importmap">{"imports": {"a": "/static/a.js"}}</script>',
        (
            '<script type="importmap" nonce="n0nce">'
            '{"imports": {"a": "/static/a.js"}}</script>'
        ),
    ),
    (
        "object with only __html__",
        HTMLOnlyAsset('<script src="/bundle.js"></script>'),
        # Opaque markup: rendered verbatim, and the nonce cannot be threaded in
        # (same as stock ``forms.Media``).
        '<script src="/bundle.js"></script>',
        '<script src="/bundle.js"></script>',
    ),
    (
        "html-safe string",
        HTML_SAFE_JS,
        # A ``SafeString`` is a ``str``, but it is a complete tag rather than a
        # path: it must never be resolved through ``static()``.
        HTML_SAFE_JS,
        HTML_SAFE_JS,
    ),
]

CSS_ASSETS = [
    (
        "bare path string",
        "app.css",
        '<link href="/static/app.css" media="all" rel="stylesheet">',
        '<link href="/static/app.css" media="all" nonce="n0nce" rel="stylesheet">',
    ),
    (
        "CSS factory",
        CSS("app.css"),
        '<link href="/static/app.css" media="all" rel="stylesheet">',
        '<link href="/static/app.css" media="all" nonce="n0nce" rel="stylesheet">',
    ),
    (
        # Django's ``Stylesheet`` has no implicit ``media``; unlike the ``CSS``
        # factory it only emits the attribute when one is passed. The dict key
        # it is filed under does not add one.
        "Stylesheet object",
        Stylesheet("app.css"),
        '<link href="/static/app.css" rel="stylesheet">',
        '<link href="/static/app.css" nonce="n0nce" rel="stylesheet">',
    ),
    (
        "inline CSS",
        CSS("body{color:red}", inline=True),
        '<style media="all">body{color:red}</style>',
        '<style media="all" nonce="n0nce">body{color:red}</style>',
    ),
    (
        "object with only __html__",
        HTMLOnlyAsset('<link href="/bundle.css" rel="stylesheet">'),
        '<link href="/bundle.css" rel="stylesheet">',
        '<link href="/bundle.css" rel="stylesheet">',
    ),
    (
        "html-safe string",
        HTML_SAFE_CSS,
        HTML_SAFE_CSS,
        HTML_SAFE_CSS,
    ),
]


class AssetRenderingTest(TestCase):
    """
    Exhaustive per-asset-kind rendering, with and without a CSP nonce.
    """

    def _check(self, rows, kwargs_for):
        for label, asset, plain, with_nonce in rows:
            with self.subTest(asset=label):
                self.assertEqual(Media(**kwargs_for(asset)).render(), plain)
                self.assertEqual(
                    Media(nonce="n0nce", **kwargs_for(asset)).render(), with_nonce
                )

    def test_js_assets(self):
        self._check(JS_ASSETS, lambda asset: {"js": [asset]})

    def test_css_assets(self):
        self._check(CSS_ASSETS, lambda asset: {"css": {"all": [asset]}})

    def test_matches_django_rendering(self):
        # Our rendering must not drift from stock ``forms.Media`` for the asset
        # kinds Django itself understands -- this is what catches a future
        # change to Django's normalization or tag format that our overridden
        # ``_normalize_{js,css}`` would otherwise silently skip. (Excludes
        # ``ImportMap``, which we deliberately merge and hoist, and html-safe
        # strings, which Django 6.1 itself gets wrong.)
        kwargs = {
            "css": {"all": ["a.css", CSS("b.css"), Stylesheet("c.css")]},
            "js": ["a.js", JS("b.js"), Script("c.js"), JS("d.js", {"defer": True})],
        }
        self.assertEqual(str(Media(**kwargs)), str(DjangoMedia(**kwargs)))


class MediaTest(TestCase):
    def test_nonce_applied_to_assets(self):
        media = Media(
            nonce="r@nd0m",
            css={"all": [CSS("app.css")]},
            js=[JS("app.js")],
        )
        html = media.render()
        self.assertInHTML(
            '<link href="/static/app.css" media="all" nonce="r@nd0m" rel="stylesheet">',
            html,
        )
        self.assertInHTML(
            '<script src="/static/app.js" nonce="r@nd0m"></script>',
            html,
        )

    def test_no_nonce_keeps_plain_output(self):
        media = Media(js=[JS("app.js")])
        self.assertEqual(media.render(), '<script src="/static/app.js"></script>')

    def test_importmaps_are_merged_and_rendered_first(self):
        media = Media(
            nonce="r@nd0m",
            js=[
                ImportMap({"imports": {"a": "/static/a.js"}}),
                JS("app.js", {"type": "module"}),
                ImportMap({"imports": {"b": "/static/b.js"}}),
            ],
        )
        self.assertEqual(
            media.render(),
            '<script type="importmap" nonce="r@nd0m">'
            '{"imports": {"a": "/static/a.js", "b": "/static/b.js"}}</script>\n'
            '<script src="/static/app.js" nonce="r@nd0m" type="module"></script>',
        )

    def test_type_and_nonce_preserved_when_merging(self):
        ours = Media(nonce="abc", js=[ImportMap({"imports": {"a": "/static/a.js"}})])
        plain = DjangoMedia(js=["app.js"])

        # Our Media on the right-hand side (the case plain forms.Media drops).
        merged = plain + ours
        self.assertIsInstance(merged, Media)
        self.assertEqual(merged.nonce, "abc")

        # ... and on the left-hand side.
        merged = ours + plain
        self.assertIsInstance(merged, Media)
        self.assertEqual(merged.nonce, "abc")

    def test_bare_string_assets_get_nonce(self):
        # Bare paths stay strings on Django < 6.2 and are wrapped into
        # MediaAsset objects on >= 6.2; both paths must receive the nonce.
        media = Media(nonce="n0nce", css={"all": ["plain.css"]}, js=["plain.js"])
        html = media.render()
        self.assertInHTML(
            '<link href="/static/plain.css" media="all" nonce="n0nce"'
            ' rel="stylesheet">',
            html,
        )
        self.assertInHTML(
            '<script src="/static/plain.js" nonce="n0nce"></script>',
            html,
        )

    def test_merging_combines_css_and_js(self):
        ours = Media(nonce="n", css={"all": [CSS("a.css")]}, js=[JS("a.js")])
        plain = DjangoMedia(css={"all": ["b.css"]}, js=["b.js"])

        merged = plain + ours  # via __radd__
        self.assertIsInstance(merged, Media)
        html = merged.render()
        for snippet in (
            '<link href="/static/b.css" media="all" nonce="n" rel="stylesheet">',
            '<link href="/static/a.css" media="all" nonce="n" rel="stylesheet">',
            '<script src="/static/b.js" nonce="n"></script>',
            '<script src="/static/a.js" nonce="n"></script>',
        ):
            self.assertInHTML(snippet, html)

    def test_render_accepts_attrs_nonce(self):
        # Django >= 6.2's CSP integration calls media.render(attrs={"nonce": ...}).
        media = Media(js=[JS("app.js")])
        self.assertInHTML(
            '<script src="/static/app.js" nonce="from-attrs"></script>',
            media.render(attrs={"nonce": "from-attrs"}),
        )
        # A passed nonce overrides the stored one.
        media = Media(nonce="stored", js=[JS("app.js")])
        self.assertInHTML(
            '<script src="/static/app.js" nonce="from-attrs"></script>',
            media.render(attrs={"nonce": "from-attrs"}),
        )

    def test_html_only_asset_renders_via_html(self):
        # A plain ``__html__``-only asset (e.g. a build-tool helper) is neither
        # a MediaAsset nor one of our types; it must fall back to ``__html__()``
        # the way stock ``forms.Media`` does, instead of crashing on a missing
        # ``render`` method.
        media = Media(js=[HTMLOnlyAsset('<script src="/bundle.js"></script>')])
        self.assertEqual(media.render(), '<script src="/bundle.js"></script>')

    def test_html_only_asset_renders_with_nonce_set(self):
        # The nonce cannot be threaded into an opaque ``__html__`` asset (same
        # as stock Django), but its presence must not break rendering.
        media = Media(
            nonce="n0nce",
            js=[HTMLOnlyAsset('<script src="/bundle.js"></script>')],
        )
        self.assertEqual(media.render(), '<script src="/bundle.js"></script>')

    def test_json_asset_rendered_through_media(self):
        # A JSON block carried as a JS asset renders via its own ``render``.
        # It is data, not executed script, so it stays nonce-free even when a
        # nonce is set on the media.
        media = Media(nonce="n0nce", js=[JSON({"a": 1}, id="cfg")])
        self.assertInHTML(
            '<script id="cfg" type="application/json">{"a": 1}</script>',
            media.render(),
        )

    def test_adding_non_media_is_not_supported(self):
        with self.assertRaises(TypeError):
            Media() + 3
        # The reverse case dispatches to Media.__radd__, which must also return
        # NotImplemented (a clean TypeError) rather than raise AttributeError.
        with self.assertRaises(TypeError):
            3 + Media()

    def test_from_media_wraps_existing_instance(self):
        plain = DjangoMedia(
            js=[ImportMap({"imports": {"a": "/static/a.js"}}), JS("app.js")]
        )
        wrapped = Media.from_media(plain, nonce="w")

        self.assertIsInstance(wrapped, Media)
        self.assertEqual(wrapped.nonce, "w")
        html = wrapped.render()
        self.assertInHTML(
            '<script type="importmap" nonce="w">'
            '{"imports": {"a": "/static/a.js"}}</script>',
            html,
        )
        self.assertInHTML(
            '<script src="/static/app.js" nonce="w"></script>',
            html,
        )

    def test_with_nonce_returns_a_copy(self):
        media = Media(js=[JS("app.js")])
        request_media = media.with_nonce("xyz")

        self.assertIsInstance(request_media, Media)
        self.assertEqual(request_media.nonce, "xyz")
        # The shared (e.g. cached widget) media is left untouched.
        self.assertEqual(media.nonce, "")
        self.assertInHTML(
            '<script src="/static/app.js" nonce="xyz"></script>',
            request_media.render(),
        )

    def test_html_safe_strings_dedupe_and_merge(self):
        # Mirrors Django's own #37262 tests: html-safe strings survive
        # deduplication and media merging alongside regular path assets.
        first = Media(
            css={"all": [HTML_SAFE_CSS, "a.css"]},
            js=["a.js", HTML_SAFE_JS],
        )
        second = Media(
            nonce="n0nce",
            css={"all": [HTML_SAFE_CSS]},
            js=[HTML_SAFE_JS, JS("b.js")],
        )
        merged = first + second

        self.assertEqual(merged.nonce, "n0nce")
        self.assertEqual(
            merged.render(),
            f"{HTML_SAFE_CSS}\n"
            '<link href="/static/a.css" media="all" nonce="n0nce" rel="stylesheet">\n'
            '<script src="/static/a.js" nonce="n0nce"></script>\n'
            f"{HTML_SAFE_JS}\n"
            '<script src="/static/b.js" nonce="n0nce"></script>',
        )

    def test_html_safe_strings_normalized_through_our_class(self):
        # We override ``_normalize_{js,css}`` so html-safe strings survive
        # construction even on Django 6.1, whose own normalizers mangle them.
        self.assertEqual(Media(js=[HTML_SAFE_JS]).render(), HTML_SAFE_JS)
        self.assertEqual(
            Media(media=type("Def", (), {"js": [HTML_SAFE_JS]})).render(),
            HTML_SAFE_JS,
        )

    def test_html_safe_strings_adopted_from_foreign_media(self):
        # ``from_media`` adopts assets a plain ``forms.Media`` already
        # normalized, so on Django 6.1 the damage is done before we see them.
        # Nothing to fix from here -- just pin which side the boundary is on.
        adopted = Media.from_media(DjangoMedia(js=[HTML_SAFE_JS]))
        if DJANGO_KEEPS_HTML_SAFE_STRINGS:
            self.assertEqual(adopted.render(), HTML_SAFE_JS)
        else:
            self.assertNotEqual(adopted.render(), HTML_SAFE_JS)
            self.assertEqual(adopted.render(), str(DjangoMedia(js=[HTML_SAFE_JS])))


class LazyNonce(SimpleLazyObject):
    """
    A stand-in for ``django.utils.csp.LazyNonce`` (Django >= 6.2), which is
    *falsy* until the nonce has been generated so that a nonce is only added to
    the CSP header if the template actually used it.
    """

    def __init__(self, value):
        super().__init__(lambda: value)

    def __bool__(self):
        return self._wrapped is not empty


class LazyNonceTest(TestCase):
    def test_lazy_nonce_from_attrs(self):
        # Django >= 6.2 renders media as ``media.render(attrs={"nonce": nonce})``
        # with the lazy nonce straight from the template context. Truth-testing
        # it says "no nonce" as long as it has not been read yet, so the nonce
        # must be resolved instead of checked for truthiness.
        media = Media(js=[JS("app.js")])
        self.assertEqual(
            media.render(attrs={"nonce": LazyNonce("l@zy")}),
            '<script src="/static/app.js" nonce="l@zy"></script>',
        )

    def test_lazy_nonce_stored_on_the_media(self):
        media = Media(nonce=LazyNonce("l@zy"), js=[JS("app.js")])
        self.assertEqual(
            media.render(),
            '<script src="/static/app.js" nonce="l@zy"></script>',
        )
        self.assertEqual(
            media.with_nonce(LazyNonce("l@zy")).render(),
            '<script src="/static/app.js" nonce="l@zy"></script>',
        )

    def test_lazy_nonce_applied_to_importmaps(self):
        media = Media(js=[ImportMap({"imports": {"a": "/static/a.js"}})])
        self.assertEqual(
            media.render(nonce=LazyNonce("l@zy")),
            '<script type="importmap" nonce="l@zy">'
            '{"imports": {"a": "/static/a.js"}}</script>',
        )

    def test_lazy_nonce_untouched_for_empty_media(self):
        # Nothing to render, so the nonce must not be generated: on Django the
        # CSP header only carries a nonce if one was actually used.
        nonce = LazyNonce("l@zy")
        self.assertEqual(Media().render(attrs={"nonce": nonce}), "")
        self.assertFalse(nonce)

    @skipIf(nonce_attr is None, "Django < 6.1 has no built-in CSP support")
    def test_csp_nonce_attr_template_tag(self):
        # The real thing, on the Django versions which have it.
        nonce = DjangoLazyNonce()
        html = nonce_attr(
            {"csp_nonce": nonce},
            Media(js=[ImportMap({"imports": {"a": "/static/a.js"}}), JS("app.js")]),
        )
        self.assertTrue(nonce)
        self.assertEqual(
            html,
            f'<script type="importmap" nonce="{nonce}">'
            '{"imports": {"a": "/static/a.js"}}</script>\n'
            f'<script src="/static/app.js" nonce="{nonce}"></script>',
        )


class RenderPartsTest(TestCase):
    """
    ``render_css()``/``render_js()`` are ``forms.Media`` API in their own right;
    they must behave like ``render()`` regarding the nonce and import maps.
    """

    def setUp(self):
        self.media = Media(
            nonce="n0nce",
            css={"all": [CSS("app.css")]},
            js=[
                ImportMap({"imports": {"a": "/static/a.js"}}),
                JS("app.js"),
                ImportMap({"imports": {"b": "/static/b.js"}}),
            ],
        )

    def test_render_css_applies_the_nonce(self):
        self.assertEqual(
            list(self.media.render_css()),
            [
                '<link href="/static/app.css" media="all" nonce="n0nce" rel="stylesheet">'
            ],
        )

    def test_render_js_applies_the_nonce_and_merges_importmaps(self):
        self.assertEqual(
            list(self.media.render_js()),
            [
                (
                    '<script type="importmap" nonce="n0nce">'
                    '{"imports": {"a": "/static/a.js", "b": "/static/b.js"}}</script>'
                ),
                '<script src="/static/app.js" nonce="n0nce"></script>',
            ],
        )

    def test_render_parts_accept_attrs(self):
        media = Media(css={"all": [CSS("app.css")]}, js=[JS("app.js")])
        attrs = {"nonce": "from-attrs"}
        self.assertEqual(
            list(media.render_css(attrs=attrs)),
            [
                (
                    '<link href="/static/app.css" media="all" nonce="from-attrs"'
                    ' rel="stylesheet">'
                )
            ],
        )
        self.assertEqual(
            list(media.render_js(attrs=attrs)),
            ['<script src="/static/app.js" nonce="from-attrs"></script>'],
        )


class GetItemTest(TestCase):
    """
    ``media["css"]`` / ``media["js"]`` -- reached as ``{{ media.css }}`` and
    ``{{ media.js }}`` from templates -- must keep our type and its nonce.
    """

    def setUp(self):
        self.media = Media(
            nonce="n0nce",
            css={"all": [CSS("app.css")]},
            js=[
                ImportMap({"imports": {"a": "/static/a.js"}}),
                JS("app.js"),
                ImportMap({"imports": {"b": "/static/b.js"}}),
            ],
        )

    def test_css_subset(self):
        subset = self.media["css"]
        self.assertIsInstance(subset, Media)
        self.assertEqual(subset.nonce, "n0nce")
        self.assertEqual(
            subset.render(),
            '<link href="/static/app.css" media="all" nonce="n0nce" rel="stylesheet">',
        )

    def test_js_subset(self):
        subset = self.media["js"]
        self.assertIsInstance(subset, Media)
        self.assertEqual(
            subset.render(),
            '<script type="importmap" nonce="n0nce">'
            '{"imports": {"a": "/static/a.js", "b": "/static/b.js"}}</script>\n'
            '<script src="/static/app.js" nonce="n0nce"></script>',
        )

    def test_unknown_media_type(self):
        with self.assertRaises(KeyError):
            self.media["json"]

    @skipIf(nonce_attr is None, "Django < 6.1 has no built-in CSP support")
    def test_csp_nonce_attr_on_a_subset(self):
        # What Django's own admin templates do: {% csp_nonce_attr media.js %}.
        nonce = DjangoLazyNonce()
        media = Media(js=[ImportMap({"imports": {"a": "/static/a.js"}}), JS("app.js")])
        self.assertEqual(
            nonce_attr({"csp_nonce": nonce}, media["js"]),
            f'<script type="importmap" nonce="{nonce}">'
            '{"imports": {"a": "/static/a.js"}}</script>\n'
            f'<script src="/static/app.js" nonce="{nonce}"></script>',
        )
