from django.forms import Media
from django.test import TestCase

from js_asset.js import (
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
                Script("app.js", **{"id": "s", "data-the-answer": 42}),
                '<script src="/static/app.js" data-the-answer="42" id="s"></script>',
            ),
            (
                Script("https://cdn.example.org/a.js"),
                '<script src="https://cdn.example.org/a.js"></script>',
            ),
            (
                Script("app.js", bool=True, cool=False),
                '<script src="/static/app.js" bool></script>',
            ),
            (
                Stylesheet("app.css", media="screen", crossorigin="anonymous"),
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
        media1 = Media(js=["thing.js", Script("other.js"), "some.js"])
        media2 = Media(js=["thing.js", Script("other.js"), "some.js"])
        media = media1 + media2
        self.assertEqual(len(media._js), 3)
        self.assertEqual(media._js[0], "thing.js")
        self.assertEqual(media._js[2], "some.js")

    def test_set(self):
        media = [
            Script("app/asset.js", **{"id": "asset-script", "data-the-answer": 42}),
            Script("app/asset.js", **{"id": "asset-script", "data-the-answer": 42}),
            Script("app/asset.js", **{"id": "asset-script", "data-the-answer": 43}),
        ]

        # Identity follows Django's own contract: 6.1+ (and the < 5.2 backport) fold attributes into equality
        # -- the differing third asset stays distinct -> 2. Django 5.2 and 6.0
        # dedup on the path alone, so all three collapse -> 1.
        attribute_aware = media[0] != media[2]
        self.assertEqual(len(set(media)), 2 if attribute_aware else 1)

    def test_stylesheet_dedups_like_paths(self):
        # ``media="all"`` is what makes it equal to the ``Stylesheet`` Django
        # >= 6.1 wraps ``"a.css"`` into.
        self.assertEqual(
            str(
                Media(css={"all": ["a.css"]})
                + Media(css={"all": [Stylesheet("a.css", media="all")]})
            ),
            '<link href="/static/a.css" media="all" rel="stylesheet">',
        )

    def test_inline_css_cannot_close_the_style_element(self):
        # The one sequence which would let the CSS escape its element.
        for css in ("a{}</style><script>alert(1)</script>", "a{}</STYLE >"):
            with self.subTest(css=css), self.assertRaises(ValueError):
                InlineStyle(css)

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
