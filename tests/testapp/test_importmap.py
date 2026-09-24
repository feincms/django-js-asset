import warnings

from django.test import TestCase

from js_asset.js import ImportMap


class MediaTest(TestCase):
    def test_merging(self):
        a = ImportMap(
            {
                "imports": {"a": "/static/a.js"},
                "integrity": {"/static/a.js": "sha384-blub-a"},
                "_unknown_": "Automatically dropped when merging.",
            }
        )
        b = ImportMap(
            {
                "imports": {"b": "/static/b.js"},
                "integrity": {"/static/b.js": "sha384-blub-b"},
            }
        )

        self.assertEqual(
            str(a | b),
            """\
<script type="importmap">{"imports": {"a": "/static/a.js", "b": "/static/b.js"}, "integrity": {"/static/a.js": "sha384-blub-a", "/static/b.js": "sha384-blub-b"}}</script>""",
        )

        c = ImportMap(
            {
                "imports": {
                    "/app/": "./original-app/",
                    "/app/helper": "./helper/index.mjs",
                },
                "scopes": {"/js": {"/app/": "./js-app/"}},
            }
        )

        self.assertEqual(
            str(a | b | c),
            """\
<script type="importmap">{"imports": {"a": "/static/a.js", "b": "/static/b.js", "/app/": "./original-app/", "/app/helper": "./helper/index.mjs"}, "integrity": {"/static/a.js": "sha384-blub-a", "/static/b.js": "sha384-blub-b"}, "scopes": {"/js": {"/app/": "./js-app/"}}}</script>""",
        )

    def test_render_attrs(self):
        importmap = ImportMap({"imports": {"a": "/static/a.js"}})
        html = '{"imports": {"a": "/static/a.js"}}</script>'
        self.assertEqual(
            importmap.render(attrs={"nonce": "N", "data-x": "y"}),
            f'<script type="importmap" data-x="y" nonce="N">{html}',
        )
        self.assertEqual(
            importmap.render(nonce="N"), f'<script type="importmap" nonce="N">{html}'
        )
        self.assertEqual(
            importmap.render(nonce="N", attrs={"data-x": "y"}),
            f'<script type="importmap" data-x="y" nonce="N">{html}',
        )
        self.assertEqual(importmap.render(), f'<script type="importmap">{html}')

    def test_bool(self):
        self.assertFalse(ImportMap({}))
        self.assertTrue(ImportMap({"imports": {"a": "/static/a.js"}}))

    def test_copies_the_data(self):
        data = {"imports": {"a": "/static/a.js"}}
        importmap = ImportMap(data)
        before = hash(importmap)
        data["imports"]["b"] = "/static/b.js"
        self.assertEqual(hash(importmap), before)
        self.assertEqual(importmap._importmap, {"imports": {"a": "/static/a.js"}})

    def test_merging_leaves_operands_alone(self):
        a = ImportMap({"imports": {"lib": "/a.js"}, "scopes": {"/x/": {"y": "/a"}}})
        b = ImportMap({"imports": {"lib": "/b.js"}, "scopes": {"/x/": {"y": "/b"}}})
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            combined = a | b
        self.assertEqual(
            combined._importmap,
            {"imports": {"lib": "/b.js"}, "scopes": {"/x/": {"y": "/b"}}},
        )
        self.assertEqual(a._importmap["imports"], {"lib": "/a.js"})
        self.assertEqual(b._importmap["imports"], {"lib": "/b.js"})

        importmap = a
        importmap |= b
        self.assertEqual(importmap, combined)
        self.assertEqual(a._importmap["imports"], {"lib": "/a.js"})

    def test_update_is_deprecated(self):
        data = {"imports": {"a": "/static/a.js"}}
        importmap = ImportMap(data)
        with self.assertWarns(DeprecationWarning):
            importmap.update({"imports": {"b": "/static/b.js"}})
        self.assertEqual(
            importmap._importmap,
            {"imports": {"a": "/static/a.js", "b": "/static/b.js"}},
        )
        self.assertEqual(data, {"imports": {"a": "/static/a.js"}})
