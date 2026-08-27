from django.forms import Media
from django.test import TestCase

from js_asset.js import CSS, JS, JSON, InlineStyle, Script, Stylesheet


class AssetTest(TestCase):
    def test_asset(self):
        media = Media(
            css={"print": ["app/print.css"]},
            js=[
                "app/test.js",
                JS("app/asset.js", {"id": "asset-script", "data-the-answer": 42}),
                JS("app/asset-without.js", {}),
            ],
        )
        html = str(media)

        # print(html)

        self.assertInHTML(
            '<link href="/static/app/print.css" media="print" rel="stylesheet" />',
            html,
        )
        self.assertInHTML(
            '<script src="/static/app/test.js"></script>',
            html,
        )
        self.assertInHTML(
            '<script src="/static/app/asset.js" data-the-answer="42" id="asset-script"></script>',
            html,
        )
        self.assertInHTML(
            '<script src="/static/app/asset-without.js"></script>',
            html,
        )

    def test_absolute(self):
        media = Media(js=[JS("https://cdn.example.org/script.js")])
        html = str(media)

        self.assertInHTML(
            '<script src="https://cdn.example.org/script.js"></script>',
            html,
        )

    def test_asset_merging(self):
        media1 = Media(js=["thing.js", JS("other.js"), "some.js"])
        media2 = Media(js=["thing.js", JS("other.js"), "some.js"])
        media = media1 + media2
        self.assertEqual(len(media._js), 3)
        self.assertEqual(media._js[0], "thing.js")
        self.assertEqual(media._js[2], "some.js")

    def test_set(self):
        media = [
            JS("app/asset.js", {"id": "asset-script", "data-the-answer": 42}),
            JS("app/asset.js", {"id": "asset-script", "data-the-answer": 42}),
            JS("app/asset.js", {"id": "asset-script", "data-the-answer": 43}),
        ]

        # ``JS`` produces a Django ``Script``, so identity follows Django's own
        # contract: 6.2+ (and the < 5.2 backport) fold attributes into equality
        # -- the differing third asset stays distinct -> 2. Django 5.2 - 6.1
        # dedup on the path alone, so all three collapse -> 1.
        attribute_aware = media[0] != media[2]
        self.assertEqual(len(set(media)), 2 if attribute_aware else 1)

    def test_boolean_attributes(self):
        self.assertEqual(
            str(JS("app/asset.js", {"bool": True, "cool": False})),
            '<script src="/static/app/asset.js" bool></script>',
        )

    def test_css(self):
        self.assertEqual(
            str(CSS("app/style.css")),
            '<link href="/static/app/style.css" media="all" rel="stylesheet">',
        )

        self.assertEqual(
            str(CSS("app/style.css", media="screen")),
            '<link href="/static/app/style.css" media="screen" rel="stylesheet">',
        )

        self.assertEqual(
            str(CSS("p{color:red}", inline=True)),
            '<style media="all">p{color:red}</style>',
        )

    def test_inline_css_is_not_escaped(self):
        # A ``<style>`` element is raw text: escaping does not round-trip there,
        # it just corrupts the CSS.
        css = 'nav > a::after{content:"<3"}\n@media (width > 40rem){a{color:red}}'
        self.assertEqual(
            str(CSS(css, inline=True)),
            f'<style media="all">{css}</style>',
        )

    def test_inline_css_cannot_close_the_style_element(self):
        # The one sequence which would let the CSS escape its element.
        for css in ("a{}</style><script>alert(1)</script>", "a{}</STYLE >"):
            with self.subTest(css=css), self.assertRaises(ValueError):
                CSS(css, inline=True)

    def test_js_produces_script(self):
        asset = JS("app/asset.js", {"id": "x"})
        # ``JS`` is a factory producing a Django ``Script`` ...
        self.assertIsInstance(asset, Script)
        self.assertNotIsInstance(asset, Stylesheet)
        # ... while ``isinstance(x, JS)`` keeps answering truthfully.
        self.assertIsInstance(asset, JS)
        self.assertNotIsInstance(CSS("app/style.css"), JS)

    def test_css_produces_stylesheet_or_inline(self):
        link = CSS("app/style.css")
        inline = CSS("p{color:red}", inline=True)
        self.assertIsInstance(link, Stylesheet)
        self.assertIsInstance(inline, InlineStyle)
        # Both flavours answer ``isinstance(x, CSS)``.
        self.assertIsInstance(link, CSS)
        self.assertIsInstance(inline, CSS)
        self.assertNotIsInstance(JS("app/asset.js"), CSS)

    def test_json(self):
        self.assertEqual(
            str(JSON({"hello": "world"}, id="hello")),
            '<script id="hello" type="application/json">{"hello": "world"}</script>',
        )

        self.assertEqual(
            str(JSON({"hello": "world"})),
            '<script type="application/json">{"hello": "world"}</script>',
        )
