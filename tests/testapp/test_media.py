from django.forms import Media as DjangoMedia
from django.test import TestCase

from js_asset import CSS, JS, ImportMap, Media


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
