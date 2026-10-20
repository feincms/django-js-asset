from django.forms import Media as DjangoMedia
from django.test import TestCase

from js_asset.js import (
    ImportMap,
    MediaAsset,
    RemovedInDjangoJsAsset60Warning,
    static_lazy,
)
from js_asset.media import Media


class ImportMapTest(TestCase):
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
            {"/app/": "/original-app/", "/app/helper": "/helper/index.mjs"},
            scopes={"/js": {"/app/": "/js-app/"}},
        )

        self.assertEqual(
            str(a | b | c),
            """\
<script type="importmap">{"imports": {"a": "/static/a.js", "b": "/static/b.js", "/app/": "/original-app/", "/app/helper": "/helper/index.mjs"}, "integrity": {"/static/a.js": "sha384-blub-a", "/static/b.js": "sha384-blub-b"}, "scopes": {"/js": {"/app/": "/js-app/"}}}</script>""",
        )

    def test_merging_leaves_operands_alone(self):
        a = ImportMap({"lib": "/a.js"}, scopes={"/x/": {"y": "/a"}})
        b = ImportMap({"lib": "/b.js"}, scopes={"/x/": {"y": "/b"}})
        combined = a | b
        self.assertEqual(
            combined._data,
            {"imports": {"lib": "/b.js"}, "scopes": {"/x/": {"y": "/b"}}},
        )
        self.assertEqual(a._data["imports"], {"lib": "/a.js"})
        self.assertEqual(b._data["imports"], {"lib": "/b.js"})

        importmap = a
        importmap |= b
        self.assertEqual(importmap, combined)
        self.assertEqual(a._data["imports"], {"lib": "/a.js"})

    def test_resolves_paths(self):
        importmap = ImportMap(
            {
                "relative": "app/a.js",
                "lazy": static_lazy("app/lazy.js"),
                "absolute": "/a.js",
                "prefix": "app/",
                "url": "https://example.org/a.js",
                "protocol-relative": "//example.org/a.js",
            },
            scopes={"/x/": {"scoped": "app/b.js"}},
            integrity={"https://example.org/a.js": "sha384-a"},
        )
        self.assertEqual(
            str(importmap),
            '<script type="importmap">{"imports": {"relative": "/static/app/a.js",'
            ' "lazy": "/static/app/lazy.js",'
            ' "absolute": "/a.js", "prefix": "/static/app/",'
            ' "url": "https://example.org/a.js",'
            ' "protocol-relative": "//example.org/a.js"},'
            ' "scopes": {"/x/": {"scoped": "/static/app/b.js"}},'
            ' "integrity": {"https://example.org/a.js": "sha384-a"}}</script>',
        )

    def test_escapes_the_json(self):
        self.assertEqual(
            str(ImportMap({"</script>": "/</script>"})),
            '<script type="importmap">'
            '{"imports": {"\\u003C/script\\u003E": "/\\u003C/script\\u003E"}}</script>',
        )

    def test_attributes(self):
        importmap = ImportMap({"a": "/static/a.js"}, **{"data-x": "y"})
        self.assertNotIsInstance(importmap, MediaAsset)
        html = '{"imports": {"a": "/static/a.js"}}</script>'
        self.assertEqual(str(importmap), f'<script type="importmap" data-x="y">{html}')
        self.assertEqual(
            importmap.render(attrs={"nonce": "N"}),
            f'<script type="importmap" data-x="y" nonce="N">{html}',
        )
        with self.assertWarns(RemovedInDjangoJsAsset60Warning):
            self.assertEqual(
                importmap.render(nonce="N"),
                f'<script type="importmap" data-x="y" nonce="N">{html}',
            )
        # Attributes survive merging.
        self.assertEqual((importmap | ImportMap({})).attributes, {"data-x": "y"})

        with self.assertRaisesMessage(ValueError, "conflicting attributes: data-x"):
            importmap.render(attrs={"data-x": "z"})
        with self.assertRaisesMessage(ValueError, "doesn't accept a type"):
            ImportMap({"a": "/static/a.js"}, type="module")
        with self.assertRaisesMessage(ValueError, "conflicting attributes: type"):
            ImportMap({"a": "/static/a.js"}).render(attrs={"type": "module"})

    def test_equality(self):
        # Equality ignores the order of keys, but not attributes.
        self.assertEqual(
            ImportMap({"a": "/a.js", "b": "/b.js"}),
            ImportMap({"b": "/b.js", "a": "/a.js"}),
        )
        self.assertNotEqual(
            ImportMap({"a": "/a.js"}, **{"data-x": "y"}), ImportMap({"a": "/a.js"})
        )

    def test_copies_the_data(self):
        data = {"a": "/static/a.js"}
        importmap = ImportMap(data)
        data["b"] = "/static/b.js"
        self.assertEqual(importmap._data, {"imports": {"a": "/static/a.js"}})

    def test_not_supported_in_js_lists(self):
        media = Media(js=[ImportMap({"a": "/static/a.js"})])
        with self.assertRaisesMessage(TypeError, "Media(importmap=...)"):
            str(media)
        # Also when adopted from a plain forms.Media, e.g. of a widget.
        media = Media() + DjangoMedia(js=[ImportMap({"a": "/static/a.js"})])
        with self.assertRaisesMessage(TypeError, "Media(importmap=...)"):
            str(media)
        # And when accessing ``{{ media.js }}``.
        with self.assertRaisesMessage(TypeError, "Media(importmap=...)"):
            media["js"]

    def test_deprecated_full_import_map(self):
        with self.assertWarnsMessage(
            RemovedInDjangoJsAsset60Warning, "full import map"
        ):
            importmap = ImportMap(
                {
                    "imports": {"a": "/a.js"},
                    "_unknown_": "Automatically dropped when merging.",
                }
            )
        self.assertEqual(
            importmap | ImportMap({"b": "/b.js"}),
            ImportMap({"a": "/a.js", "b": "/b.js"}),
        )
