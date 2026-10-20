from unittest import skipIf

from django import forms
from django.forms import Media as DjangoMedia
from django.test import TestCase
from django.utils.functional import SimpleLazyObject, empty
from django.utils.html import html_safe
from django.utils.safestring import mark_safe

from js_asset import (
    JSON,
    ImportMap,
    InlineStyle,
    Media,
    RemovedInDjangoJsAsset60Warning,
    Script,
    Stylesheet,
)


try:  # Django >= 6.1
    from django.utils.csp import LazyNonce as DjangoLazyNonce, nonce_attr
except ImportError:
    DjangoLazyNonce = nonce_attr = None


@html_safe
class HTMLOnlyAsset:
    """
    A media asset using Django's plain ``__html__`` contract -- not a
    ``MediaAsset``. Stock
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
# the "is it a bare path?" test in ``Media.render_js``/``.render_css``)
# quietly mishandling one of them.
JS_ASSETS = [
    (
        "bare path string",
        "app.js",
        '<script src="/static/app.js"></script>',
        '<script src="/static/app.js" nonce="n0nce"></script>',
    ),
    (
        "Script object with attributes",
        Script("app.js", type="module"),
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
        '<script id="cfg" type="application/json">{"a": 1}</script>',
        '<script id="cfg" nonce="n0nce" type="application/json">{"a": 1}</script>',
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
        "Stylesheet object with media",
        Stylesheet("app.css", media="all"),
        '<link href="/static/app.css" media="all" rel="stylesheet">',
        '<link href="/static/app.css" media="all" nonce="n0nce" rel="stylesheet">',
    ),
    (
        # Django's ``Stylesheet`` has no implicit ``media``, it only emits the
        # attribute when one is passed. The dict key it is filed under does not
        # add one.
        "Stylesheet object",
        Stylesheet("app.css"),
        '<link href="/static/app.css" rel="stylesheet">',
        '<link href="/static/app.css" nonce="n0nce" rel="stylesheet">',
    ),
    (
        "inline CSS",
        InlineStyle("body{color:red}"),
        "<style>body{color:red}</style>",
        '<style nonce="n0nce">body{color:red}</style>',
    ),
    (
        # ``<style>`` is a raw text element: HTML escapes are not decoded inside
        # it, so the CSS has to be rendered exactly as given -- an escaped
        # ``&gt;`` would break the selector instead of standing for ``>``.
        "inline CSS with characters HTML would escape",
        InlineStyle('nav > a{content:"&"}'),
        '<style>nav > a{content:"&"}</style>',
        '<style nonce="n0nce">nav > a{content:"&"}</style>',
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
        # html-safe strings, which Django 6.1 itself gets wrong.)
        kwargs = {
            "css": {
                "all": ["a.css", Stylesheet("b.css", media="all"), Stylesheet("c.css")]
            },
            "js": ["a.js", Script("b.js"), Script("c.js"), Script("d.js", defer=True)],
        }
        self.assertEqual(str(Media(**kwargs)), str(DjangoMedia(**kwargs)))


APP_JS = '<script src="/static/app.js"{}></script>'
IMPORTMAP = '<script type="importmap"{}>{{"imports": {{"a": "/static/a.js"}}}}</script>'


def nonce(value):
    return f' nonce="{value}"'


class MediaTest(TestCase):
    def test_nonce_conflicts_with_asset_nonce(self):
        for kwargs in [
            {"js": [Script("app.js", nonce="own")]},
            {"importmap": ImportMap({"a": "/static/a.js"}, nonce="own")},
        ]:
            with self.subTest(kwargs=kwargs):
                media = Media(nonce="r@nd0m", **kwargs)
                with self.assertRaisesMessage(
                    ValueError, "has conflicting attributes: nonce"
                ):
                    media.render()
                # Without a nonce to apply, the asset's own nonce is rendered.
                self.assertIn('nonce="own"', Media(**kwargs).render())

    @skipIf(nonce_attr is None, "Django < 6.1 has no built-in CSP support")
    def test_nonce_conflict_matches_django(self):
        asset = Script("app.js", nonce="own")
        with self.assertRaisesMessage(ValueError, "has conflicting attributes: nonce"):
            DjangoMedia(js=[asset]).render(attrs={"nonce": "r@nd0m"})
        with self.assertRaisesMessage(ValueError, "has conflicting attributes: nonce"):
            Media(js=[asset]).render(attrs={"nonce": "r@nd0m"})

    def test_none_nonce(self):
        media = Media(nonce=None, js=[Script("app.js")])
        self.assertEqual(media.render(), APP_JS.format(""))

    def test_render_nonce(self):
        media = Media(nonce="stored", js=[Script("app.js")])
        # A passed nonce overrides the stored one.
        self.assertEqual(
            media.render(attrs={"nonce": "passed"}), APP_JS.format(nonce("passed"))
        )
        with self.assertWarns(RemovedInDjangoJsAsset60Warning) as cm:
            html = media.render(nonce="n")
        self.assertEqual(html, APP_JS.format(nonce("n")))
        self.assertEqual(cm.filename, __file__)

    def test_render_applies_all_attrs(self):
        # Like Django >= 6.1's ``Media.render(attrs=)``, all attributes are
        # added to every tag, not just the nonce.
        media = Media(
            nonce="stored",
            importmap=ImportMap({"a": "/static/a.js"}),
            css={"all": [Stylesheet("app.css", media="all")]},
            js=[Script("app.js")],
        )
        self.assertEqual(
            media.render(attrs={"data-x": "1"}),
            '<script type="importmap" data-x="1" nonce="stored">'
            '{"imports": {"a": "/static/a.js"}}</script>\n'
            '<link href="/static/app.css" data-x="1" media="all" nonce="stored"'
            ' rel="stylesheet">\n'
            '<script src="/static/app.js" data-x="1" nonce="stored"></script>',
        )
        with self.assertRaisesMessage(ValueError, "has conflicting attributes: media"):
            media.render(attrs={"media": "print"})

    def test_adding_keeps_type_nonce_and_assets(self):
        ours = Media(nonce="n", css={"all": ["a.css"]}, js=[Script("a.js")])
        plain = DjangoMedia(css={"all": ["b.css"]}, js=["b.js"])
        # Plain ``forms.Media`` would drop our media on the right-hand side.
        for merged in (plain + ours, ours + plain):
            with self.subTest(merged=merged):
                self.assertIsInstance(merged, Media)
                html = merged.render()
                for path in ("a.css", "b.css"):
                    self.assertInHTML(
                        f'<link href="/static/{path}" media="all" nonce="n"'
                        ' rel="stylesheet">',
                        html,
                    )
                for path in ("a.js", "b.js"):
                    self.assertInHTML(
                        f'<script src="/static/{path}" nonce="n"></script>', html
                    )

    def test_subclass_preserved(self):
        class MyMedia(Media):
            pass

        media = MyMedia(js=[Script("app.js")])
        self.assertIs(type(media + DjangoMedia()), MyMedia)
        self.assertIs(type(DjangoMedia() + media), MyMedia)
        for name in ("css", "js", "importmap"):
            self.assertIs(type(media[name]), MyMedia)

    def test_adding_non_media_is_not_supported(self):
        with self.assertRaises(TypeError):
            Media() + 3
        # The reverse case dispatches to Media.__radd__, which must also return
        # NotImplemented (a clean TypeError) rather than raise AttributeError.
        with self.assertRaises(TypeError):
            3 + Media()

    def test_from_media(self):
        wrapped = Media.from_media(DjangoMedia(js=[Script("app.js")]), nonce="w")
        self.assertIsInstance(wrapped, Media)
        self.assertEqual(wrapped.render(), APP_JS.format(nonce("w")))

        media = Media(nonce="n", js=[Script("app.js")])
        self.assertEqual(Media.from_media(media).nonce, "n")
        self.assertEqual(Media.from_media(media, nonce="").nonce, "")
        self.assertEqual(Media.from_media(DjangoMedia()).nonce, "")

    def test_with_nonce_returns_a_copy(self):
        media = Media(js=[Script("app.js")])
        request_media = media.with_nonce("xyz")
        self.assertIsInstance(request_media, Media)
        self.assertEqual(request_media.render(), APP_JS.format(nonce("xyz")))
        # The shared (e.g. cached widget) media is left untouched.
        self.assertEqual(media.nonce, "")

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
            js=[HTML_SAFE_JS, Script("b.js")],
        )
        self.assertEqual(
            (first + second).render(),
            f"{HTML_SAFE_CSS}\n"
            '<link href="/static/a.css" media="all" nonce="n0nce" rel="stylesheet">\n'
            '<script src="/static/a.js" nonce="n0nce"></script>\n'
            f"{HTML_SAFE_JS}\n"
            '<script src="/static/b.js" nonce="n0nce"></script>',
        )

    def test_html_safe_strings_in_media_definitions(self):
        # Django 6.1.0 normalizes media definitions with ``isinstance(path,
        # str)`` too, our ``_normalize_{js,css}`` keep them verbatim.
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
    A stand-in for ``django.utils.csp.LazyNonce`` (Django >= 6.0), which is
    *falsy* until the nonce has been generated so that a nonce is only added to
    the CSP header if the template actually used it.
    """

    def __init__(self, value):
        super().__init__(lambda: value)

    def __bool__(self):
        return self._wrapped is not empty


class LazyNonceTest(TestCase):
    def test_lazy_nonce_from_attrs(self):
        # Django >= 6.1 renders media as ``media.render(attrs={"nonce": nonce})``
        # with the lazy nonce straight from the template context. Truth-testing
        # it says "no nonce" as long as it has not been read yet, so the nonce
        # must be resolved instead of checked for truthiness.
        for media, html in [
            (Media(js=[Script("app.js")]), APP_JS),
            (Media(importmap=ImportMap({"a": "/static/a.js"})), IMPORTMAP),
        ]:
            with self.subTest(html=html):
                self.assertEqual(
                    media.render(attrs={"nonce": LazyNonce("l@zy")}),
                    html.format(nonce("l@zy")),
                )

    def test_lazy_nonce_stored_on_the_media(self):
        html = APP_JS.format(nonce("l@zy"))
        media = Media(nonce=LazyNonce("l@zy"), js=[Script("app.js")])
        self.assertEqual(media.render(), html)
        # An unread lazy nonce is falsy, which must not make adding media
        # prefer the other side's nonce -- or drop it altogether.
        for combined in (
            media + DjangoMedia(),
            DjangoMedia() + media,
            media + Media(nonce="other"),
        ):
            with self.subTest(media=combined):
                self.assertEqual(combined.render(), html)

    def test_lazy_nonce_untouched_for_empty_media(self):
        # Nothing to render, so the nonce must not be generated: on Django the
        # CSP header only carries a nonce if one was actually used.
        lazy = LazyNonce("l@zy")
        self.assertEqual(Media().render(attrs={"nonce": lazy}), "")
        self.assertFalse(lazy)

    @skipIf(nonce_attr is None, "Django < 6.1 has no built-in CSP support")
    def test_csp_nonce_attr_template_tag(self):
        # The real thing, on the Django versions which have it.
        lazy = DjangoLazyNonce()
        html = nonce_attr(
            {"csp_nonce": lazy},
            Media(importmap=ImportMap({"a": "/static/a.js"}), js=[Script("app.js")]),
        )
        self.assertTrue(lazy)
        self.assertEqual(
            html, f"{IMPORTMAP.format(nonce(lazy))}\n{APP_JS.format(nonce(lazy))}"
        )


class RenderPartsTest(TestCase):
    """
    ``render_css()``/``render_js()`` are ``forms.Media`` API in their own right;
    they must behave like ``render()`` regarding the nonce, and so must
    ``render_importmap()``.
    """

    def test_render_parts_apply_the_nonce(self):
        media = Media(
            nonce="stored",
            importmap=ImportMap({"a": "/static/a.js"}),
            css={"all": [Stylesheet("app.css", media="all")]},
            js=[Script("app.js")],
        )
        for value, attrs in [("stored", None), ("passed", {"nonce": "passed"})]:
            with self.subTest(attrs=attrs):
                self.assertEqual(
                    list(media.render_css(attrs=attrs)),
                    [
                        (
                            f'<link href="/static/app.css" media="all"{nonce(value)}'
                            ' rel="stylesheet">'
                        )
                    ],
                )
                self.assertEqual(
                    media.render_js(attrs=attrs), [APP_JS.format(nonce(value))]
                )
                self.assertEqual(
                    media.render_importmap(attrs=attrs),
                    [IMPORTMAP.format(nonce(value))],
                )


class GetItemTest(TestCase):
    """
    ``media["importmap"]`` / ``media["css"]`` / ``media["js"]`` -- reached as
    ``{{ media.importmap }}`` etc. from templates -- must keep our type and its
    nonce.
    """

    def test_subsets(self):
        media = Media(
            nonce="n0nce",
            importmap=ImportMap({"a": "/static/a.js"}),
            css={"all": [Stylesheet("app.css", media="all")]},
            js=[Script("app.js")],
        )
        for name, html in [
            (
                "css",
                (
                    '<link href="/static/app.css" media="all" nonce="n0nce"'
                    ' rel="stylesheet">'
                ),
            ),
            ("js", APP_JS.format(nonce("n0nce"))),
            ("importmap", IMPORTMAP.format(nonce("n0nce"))),
        ]:
            with self.subTest(name=name):
                self.assertIsInstance(media[name], Media)
                self.assertEqual(media[name].render(), html)
        with self.assertRaises(KeyError):
            media["json"]

    def test_html_safe_strings_in_subsets(self):
        # Django 6.1.0 and main mangle html-safe strings when normalizing, and
        # ``forms.Media.__getitem__`` normalizes the subset again.
        media = Media(js=[HTML_SAFE_JS])
        self.assertEqual(media["js"].render(), HTML_SAFE_JS)

    @skipIf(nonce_attr is None, "Django < 6.1 has no built-in CSP support")
    def test_csp_nonce_attr_on_a_subset(self):
        # What Django's own admin templates do: {% csp_nonce_attr media.js %}.
        lazy = DjangoLazyNonce()
        media = Media(importmap=ImportMap({"a": "/static/a.js"}), js=[Script("app.js")])
        self.assertEqual(
            nonce_attr({"csp_nonce": lazy}, media["js"]), APP_JS.format(nonce(lazy))
        )
        self.assertEqual(
            nonce_attr({"csp_nonce": lazy}, media["importmap"]),
            IMPORTMAP.format(nonce(lazy)),
        )


class ImportMapArgumentTest(TestCase):
    def test_rendered_first(self):
        media = Media(
            importmap=ImportMap({"a": "/static/a.js"}),
            css={"all": [Stylesheet("app.css", media="all")]},
            js=[Script("app.js", type="module")],
        )
        self.assertEqual(
            media.render(attrs={"nonce": "n"}),
            f"{IMPORTMAP.format(nonce('n'))}\n"
            '<link href="/static/app.css" media="all" nonce="n" rel="stylesheet">\n'
            '<script src="/static/app.js" nonce="n" type="module"></script>',
        )

    def test_merged_when_adding(self):
        app = Media(importmap=ImportMap({"lib": "/app.js", "app": "/app/app.js"}))
        project = Media(importmap=ImportMap({"lib": "/project.js"}))
        self.assertEqual(
            str(app + project),
            '<script type="importmap">{"imports": {"lib": "/project.js",'
            ' "app": "/app/app.js"}}</script>',
        )
        # Also with a plain forms.Media on either side.
        self.assertEqual(str(DjangoMedia() + project), str(project))
        self.assertEqual(str(project + DjangoMedia()), str(project))

    def test_media_definition(self):
        class Definition:
            importmap = ImportMap({"a": "/static/a.js"})
            js = ("app.js",)

        self.assertEqual(
            str(Media(Definition)), f"{IMPORTMAP.format('')}\n{APP_JS.format('')}"
        )

    def test_kept_when_copying(self):
        media = Media(importmap=ImportMap({"a": "/static/a.js"}))
        self.assertEqual(str(media.with_nonce("n")), IMPORTMAP.format(nonce("n")))
        self.assertEqual(str(Media.from_media(media)), IMPORTMAP.format(""))

    def test_widget_media_attribute(self):
        # What the README recommends for widgets instead of ``class Media``.
        class EditorWidget(forms.Textarea):
            media = Media(
                importmap=ImportMap({"editor": "editor/index.js"}),
                js=[Script("editor/init.js", type="module")],
            )

        class ArticleForm(forms.Form):
            title = forms.CharField()
            body = forms.CharField(widget=EditorWidget)

        project = Media(importmap=ImportMap({"editor": "/project/editor.js"}))
        self.assertEqual(
            str(ArticleForm().media + project),
            '<script type="importmap">{"imports": {"editor": "/project/editor.js"}}'
            "</script>\n"
            '<script src="/static/editor/init.js" type="module"></script>',
        )
