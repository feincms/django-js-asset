from unittest import skipIf

import django
from django.forms import Media as DjangoMedia
from django.test import TestCase

from js_asset.js import ImportMap, MediaAsset, static_lazy


class MediaTest(TestCase):
    def test_merging(self):
        a = ImportMap(
            {"a": "/static/a.js"}, integrity={"/static/a.js": "sha384-blub-a"}
        )
        b = ImportMap(
            {"b": "/static/b.js"}, integrity={"/static/b.js": "sha384-blub-b"}
        )

        self.assertEqual(
            str(a | b),
            """\
<script type="importmap">{"imports": {"a": "/static/a.js", "b": "/static/b.js"}, "integrity": {"/static/a.js": "sha384-blub-a", "/static/b.js": "sha384-blub-b"}}</script>""",
        )

        c = ImportMap(
            {"/app/": "./original-app/", "/app/helper": "./helper/index.mjs"},
            scopes={"/js": {"/app/": "./js-app/"}},
        )

        self.assertEqual(
            str(a | b | c),
            """\
<script type="importmap">{"imports": {"a": "/static/a.js", "b": "/static/b.js", "/app/": "./original-app/", "/app/helper": "./helper/index.mjs"}, "integrity": {"/static/a.js": "sha384-blub-a", "/static/b.js": "sha384-blub-b"}, "scopes": {"/js": {"/app/": "./js-app/"}}}</script>""",
        )

    def test_resolves_paths(self):
        importmap = ImportMap(
            {
                "relative": "app/a.js",
                "absolute": "/a.js",
                "document": "./a.js",
                "parent": "../a.js",
                "prefix": "app/",
                "url": "https://example.org/a.js",
                "data": "data:text/javascript,export default 1",
                "protocol-relative": "//example.org/a.js",
            },
            scopes={"/x/": {"scoped": "app/b.js"}},
            integrity={"https://example.org/a.js": "sha384-a"},
        )
        self.assertEqual(
            str(importmap),
            '<script type="importmap">{"imports": {"relative": "/static/app/a.js",'
            ' "absolute": "/a.js", "document": "./a.js", "parent": "../a.js",'
            ' "prefix": "app/", "url": "https://example.org/a.js",'
            ' "data": "data:text/javascript,export default 1",'
            ' "protocol-relative": "//example.org/a.js"},'
            ' "scopes": {"/x/": {"scoped": "/static/app/b.js"}},'
            ' "integrity": {"https://example.org/a.js": "sha384-a"}}</script>',
        )

    def test_keyword_arguments(self):
        data = {"imports": {"a": "a.js"}, "scopes": {"/x/": {"b": "b.js"}}}
        self.assertEqual(
            str(ImportMap(**data)),
            '<script type="importmap">{"imports": {"a": "/static/a.js"},'
            ' "scopes": {"/x/": {"b": "/static/b.js"}}}</script>',
        )

    def test_render_attrs(self):
        importmap = ImportMap({"a": "/static/a.js"})
        html = '{"imports": {"a": "/static/a.js"}}</script>'
        self.assertEqual(
            importmap.render(attrs={"nonce": "N", "data-x": "y"}),
            f'<script type="importmap" data-x="y" nonce="N">{html}',
        )
        self.assertEqual(importmap.render(), f'<script type="importmap">{html}')

    def test_render_nonce_is_deprecated(self):
        importmap = ImportMap({"a": "/static/a.js"})
        with self.assertWarns(DeprecationWarning):
            html = importmap.render(nonce="N", attrs={"data-x": "y"})
        self.assertEqual(
            html,
            '<script type="importmap" data-x="y" nonce="N">'
            '{"imports": {"a": "/static/a.js"}}</script>',
        )

    def test_is_a_media_asset(self):
        importmap = ImportMap({"a": "/static/a.js"}, **{"data-x": "y"})
        self.assertIsInstance(importmap, MediaAsset)
        self.assertEqual(
            str(importmap),
            '<script type="importmap" data-x="y">'
            '{"imports": {"a": "/static/a.js"}}</script>',
        )
        # Equality and hashing ignore the order of keys, but not attributes.
        self.assertEqual(
            ImportMap({"a": "/a.js", "b": "/b.js"}),
            ImportMap({"b": "/b.js", "a": "/a.js"}),
        )
        self.assertEqual(
            hash(ImportMap({"a": "/a.js", "b": "/b.js"})),
            hash(ImportMap({"b": "/b.js", "a": "/a.js"})),
        )
        self.assertNotEqual(importmap, ImportMap({"a": "/static/a.js"}))
        # Attributes survive merging.
        self.assertEqual((importmap | ImportMap({})).attributes, {"data-x": "y"})

    def test_escapes_the_json(self):
        self.assertEqual(
            str(ImportMap({"</script>": "/</script>"})),
            '<script type="importmap">'
            '{"imports": {"\\u003C/script\\u003E": "/\\u003C/script\\u003E"}}</script>',
        )

    @skipIf(django.VERSION < (6, 1), "Django < 6.1 has no Media.render(attrs=)")
    def test_plain_django_media_applies_the_nonce(self):
        media = DjangoMedia(js=[ImportMap({"a": "/static/a.js"})])
        self.assertEqual(
            media.render(attrs={"nonce": "N"}),
            '<script type="importmap" nonce="N">'
            '{"imports": {"a": "/static/a.js"}}</script>',
        )

    def test_copies_the_data(self):
        data = {"a": "/static/a.js"}
        importmap = ImportMap(data)
        before = hash(importmap)
        data["b"] = "/static/b.js"
        self.assertEqual(hash(importmap), before)
        self.assertEqual(importmap._path, {"imports": {"a": "/static/a.js"}})

    def test_merging_leaves_operands_alone(self):
        a = ImportMap({"lib": "/a.js"}, scopes={"/x/": {"y": "/a"}})
        b = ImportMap({"lib": "/b.js"}, scopes={"/x/": {"y": "/b"}})
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

    def test_is_immutable(self):
        self.assertFalse(hasattr(ImportMap({}), "update"))

    def test_hash_consistent_with_equality(self):
        a = ImportMap({}, async_=True)
        b = ImportMap({}, async_=1)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))


class DeprecatedFullImportMapTest(TestCase):
    """
    ``ImportMap`` used to take a full import map. That still works, with a
    deprecation warning, and its paths are never passed through ``static()``.
    """

    def full(self, data):
        with self.assertWarnsMessage(DeprecationWarning, "full import map"):
            return ImportMap(data)

    def test_merging(self):
        a = self.full(
            {
                "imports": {"a": "/static/a.js"},
                "integrity": {"/static/a.js": "sha384-blub-a"},
                "_unknown_": "Automatically dropped when merging.",
            }
        )
        b = self.full(
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

    def test_paths_are_not_resolved(self):
        importmap = self.full(
            {
                "imports": {"a": "app/a.js", "lazy": static_lazy("lazy.js")},
                "scopes": {"/x/": {"b": "app/b.js"}},
            }
        )
        # Merging with a new-style import map keeps the old paths as they are.
        self.assertEqual(
            str(importmap | ImportMap({"c": "app/c.js"})),
            '<script type="importmap">{"imports": {"a": "app/a.js",'
            ' "lazy": "/static/lazy.js", "c": "/static/app/c.js"},'
            ' "scopes": {"/x/": {"b": "app/b.js"}}}</script>',
        )

    def test_equal_to_new_form(self):
        self.assertEqual(
            self.full({"imports": {"a": "/a.js"}}), ImportMap({"a": "/a.js"})
        )
