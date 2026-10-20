from django.forms import Media
from django.test import TestCase

from js_asset.js import (
    CSS,
    JS,
    JSON,
    InlineStyle,
    MediaAsset,
    Script,
    Stylesheet,
)


class AssetTest(TestCase):
    def test_render(self):
        for asset, html in [
            (
                JS("app.js", **{"id": "s", "data-the-answer": 42}),
                '<script src="/static/app.js" data-the-answer="42" id="s"></script>',
            ),
            (
                JS("https://cdn.example.org/a.js"),
                '<script src="https://cdn.example.org/a.js"></script>',
            ),
            (
                JS("app.js", bool=True, cool=False),
                '<script src="/static/app.js" bool></script>',
            ),
            (
                CSS("app.css", media="screen", crossorigin="anonymous"),
                (
                    '<link href="/static/app.css" crossorigin="anonymous"'
                    ' media="screen" rel="stylesheet">'
                ),
            ),
            (InlineStyle("p{color:red}"), "<style>p{color:red}</style>"),
            (
                JSON({"hello": "world"}, id="hello"),
                (
                    '<script id="hello" type="application/json">{"hello": "world"}'
                    "</script>"
                ),
            ),
            (
                # Escaped so that the data cannot close the element.
                JSON({"a": "</script>"}),
                (
                    '<script type="application/json">{"a": "\\u003C/script\\u003E"}'
                    "</script>"
                ),
            ),
        ]:
            with self.subTest(html=html):
                self.assertEqual(str(asset), html)

    def test_asset_merging(self):
        media1 = Media(js=["thing.js", JS("other.js"), "some.js"])
        media2 = Media(js=["thing.js", JS("other.js"), "some.js"])
        media = media1 + media2
        self.assertEqual(len(media._js), 3)
        self.assertEqual(media._js[0], "thing.js")
        self.assertEqual(media._js[2], "some.js")

    def test_set(self):
        media = [
            JS("app/asset.js", **{"id": "asset-script", "data-the-answer": 42}),
            JS("app/asset.js", **{"id": "asset-script", "data-the-answer": 42}),
            JS("app/asset.js", **{"id": "asset-script", "data-the-answer": 43}),
        ]

        # ``JS`` produces a Django ``Script``, so identity follows Django's own
        # contract: 6.1+ (and the < 5.2 backport) fold attributes into equality
        # -- the differing third asset stays distinct -> 2. Django 5.2 and 6.0
        # dedup on the path alone, so all three collapse -> 1.
        attribute_aware = media[0] != media[2]
        self.assertEqual(len(set(media)), 2 if attribute_aware else 1)

    def test_deprecated_signatures(self):
        # ``JS``/``CSS`` will become aliases of ``Script``/``Stylesheet``. Until
        # then, the old forms keep working and render the same as before.
        cases = [
            (
                lambda: JS("app.js", {"id": "x"}),
                '<script src="/static/app.js" id="x"></script>',
            ),
            (
                lambda: JS("app.js", attrs={"id": "x"}),
                '<script src="/static/app.js" id="x"></script>',
            ),
            (
                lambda: CSS("app.css"),
                '<link href="/static/app.css" media="all" rel="stylesheet">',
            ),
            (
                lambda: CSS("app.css", "print"),
                '<link href="/static/app.css" media="print" rel="stylesheet">',
            ),
            (
                lambda: CSS("app.css", media="all", attrs={"id": "s"}),
                '<link href="/static/app.css" id="s" media="all" rel="stylesheet">',
            ),
            (
                lambda: CSS("p{color:red}", inline=True),
                '<style media="all">p{color:red}</style>',
            ),
            (
                lambda: CSS("p{color:red}", "print", inline=True, attrs={"id": "s"}),
                '<style id="s" media="print">p{color:red}</style>',
            ),
        ]
        for produce, html in cases:
            with self.subTest(html=html):
                with self.assertWarns(DeprecationWarning) as cm:
                    asset = produce()
                self.assertEqual(str(asset), html)
                self.assertEqual(cm.filename, __file__)

    def test_inline_css_cannot_close_the_style_element(self):
        # The one sequence which would let the CSS escape its element.
        for css in ("a{}</style><script>alert(1)</script>", "a{}</STYLE >"):
            with self.subTest(css=css), self.assertRaises(ValueError):
                InlineStyle(css)

    def test_isinstance_both_ways(self):
        # ``JS``/``CSS`` produce Django's assets, and Django's assets count as
        # ``JS``/``CSS``, so checks against either name keep working.
        self.assertIs(type(JS("a.js")), Script)
        self.assertIs(type(CSS("a.css", media="all")), Stylesheet)
        self.assertIsInstance(Script("a.js"), JS)
        self.assertIsInstance(Stylesheet("a.css"), CSS)
        self.assertIsInstance(InlineStyle("a{}"), CSS)
        self.assertTrue(issubclass(Script, JS))
        self.assertTrue(issubclass(Stylesheet, CSS))
        self.assertFalse(issubclass(Script, CSS))
        self.assertFalse(issubclass(Stylesheet, JS))
        self.assertNotIsInstance(JSON({}), JS)
        self.assertNotIsInstance("a.js", JS)

    def test_json(self):
        data = {"hello": "world"}
        asset = JSON(data, id="hello")
        self.assertIsInstance(asset, MediaAsset)
        self.assertEqual((asset.data, asset.id), ({"hello": "world"}, "hello"))
        self.assertEqual(JSON({}).id, "")
        self.assertEqual(
            asset.render(attrs={"nonce": "N"}),
            '<script id="hello" nonce="N" type="application/json">'
            '{"hello": "world"}</script>',
        )
        with self.assertWarns(DeprecationWarning):
            asset.render(nonce="N")
        with self.assertRaisesMessage(ValueError, "conflicting attributes: type"):
            asset.render(attrs={"type": "text/plain"})

        # The data is copied in both directions.
        data["hello"] = "changed"
        asset.data["hello"] = "changed"
        self.assertEqual(asset.data, {"hello": "world"})

        # Equality ignores the order of keys, but not attributes.
        self.assertEqual(JSON({"a": 1, "b": 2}), JSON({"b": 2, "a": 1}))
        self.assertEqual(hash(JSON({"a": 1, "b": 2})), hash(JSON({"b": 2, "a": 1})))
        self.assertNotEqual(JSON({"a": 1}, id="x"), JSON({"a": 1}))
