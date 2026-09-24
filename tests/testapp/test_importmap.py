import warnings
from unittest import skipIf

import django
from django.forms import Media as DjangoMedia
from django.test import TestCase

from js_asset.js import ImportMap, MediaAsset


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
        self.assertEqual(importmap.render(), f'<script type="importmap">{html}')

    def test_render_nonce_is_deprecated(self):
        importmap = ImportMap({"imports": {"a": "/static/a.js"}})
        with self.assertWarns(DeprecationWarning):
            html = importmap.render(nonce="N", attrs={"data-x": "y"})
        self.assertEqual(
            html,
            '<script type="importmap" data-x="y" nonce="N">'
            '{"imports": {"a": "/static/a.js"}}</script>',
        )

    def test_is_a_media_asset(self):
        importmap = ImportMap({"imports": {"a": "/static/a.js"}}, **{"data-x": "y"})
        self.assertIsInstance(importmap, MediaAsset)
        self.assertEqual(
            str(importmap),
            '<script type="importmap" data-x="y">'
            '{"imports": {"a": "/static/a.js"}}</script>',
        )
        # Equality and hashing ignore the order of keys, but not attributes.
        self.assertEqual(
            ImportMap({"imports": {"a": "/a.js", "b": "/b.js"}}),
            ImportMap({"imports": {"b": "/b.js", "a": "/a.js"}}),
        )
        self.assertEqual(
            hash(ImportMap({"imports": {"a": "/a.js", "b": "/b.js"}})),
            hash(ImportMap({"imports": {"b": "/b.js", "a": "/a.js"}})),
        )
        self.assertNotEqual(importmap, ImportMap({"imports": {"a": "/static/a.js"}}))
        # Attributes survive merging.
        self.assertEqual((importmap | ImportMap({})).attributes, {"data-x": "y"})

    def test_escapes_the_json(self):
        self.assertEqual(
            str(ImportMap({"imports": {"a": "</script>"}})),
            '<script type="importmap">'
            '{"imports": {"a": "\\u003C/script\\u003E"}}</script>',
        )

    @skipIf(django.VERSION < (6, 1), "Django < 6.1 has no Media.render(attrs=)")
    def test_plain_django_media_applies_the_nonce(self):
        media = DjangoMedia(js=[ImportMap({"imports": {"a": "/static/a.js"}})])
        self.assertEqual(
            media.render(attrs={"nonce": "N"}),
            '<script type="importmap" nonce="N">'
            '{"imports": {"a": "/static/a.js"}}</script>',
        )

    def test_copies_the_data(self):
        data = {"imports": {"a": "/static/a.js"}}
        importmap = ImportMap(data)
        before = hash(importmap)
        data["imports"]["b"] = "/static/b.js"
        self.assertEqual(hash(importmap), before)
        self.assertEqual(importmap._path, {"imports": {"a": "/static/a.js"}})

    def test_merging_leaves_operands_alone(self):
        a = ImportMap({"imports": {"lib": "/a.js"}, "scopes": {"/x/": {"y": "/a"}}})
        b = ImportMap({"imports": {"lib": "/b.js"}, "scopes": {"/x/": {"y": "/b"}}})
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            combined = a | b
        self.assertEqual(
            combined._path,
            {"imports": {"lib": "/b.js"}, "scopes": {"/x/": {"y": "/b"}}},
        )
        self.assertEqual(a._path["imports"], {"lib": "/a.js"})
        self.assertEqual(b._path["imports"], {"lib": "/b.js"})

        importmap = a
        importmap |= b
        self.assertEqual(importmap, combined)
        self.assertEqual(a._path["imports"], {"lib": "/a.js"})

    def test_update_is_deprecated(self):
        data = {"imports": {"a": "/static/a.js"}}
        importmap = ImportMap(data)
        with self.assertWarns(DeprecationWarning):
            importmap.update({"imports": {"b": "/static/b.js"}})
        self.assertEqual(
            importmap._path,
            {"imports": {"a": "/static/a.js", "b": "/static/b.js"}},
        )
        self.assertEqual(data, {"imports": {"a": "/static/a.js"}})
