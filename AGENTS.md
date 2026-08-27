# django-js-asset — agent notes

`JS`, `CSS`, `JSON` support for `django.forms.Media`, plus importmap and CSP
nonce support.

## Running tests

Use **tox** (configured with `tox-uv`, so it provisions the right Python/Django
automatically — do not hand-roll a venv):

```bash
tox -e py312-dj42      # lowest supported combination
tox -e py314-dj62      # a recent combination
tox run-parallel       # the whole matrix
```

The matrix lives in `tox.ini` (`tests/manage.py test testapp`).

## Compatibility (hard constraint)

- Python `>=3.10`, Django `>=4.2`. **Django 6.2+ is NOT an acceptable floor.**
- `JS`/`CSS` *produce* Django's own `Script`/`Stylesheet` (see Layout). Where
  Django lacks them they are **backported** in `js_asset/_compat.py`, so the
  4.2 floor holds — we provide the machinery, we don't *depend* on Django
  having it. Availability in real Django: `Script` (5.2+), `Stylesheet` +
  `MediaAsset.render(attrs=)` (6.1+), attribute-aware `__eq__`/`__hash__`
  (6.2+). The `<5.2` backport mirrors the **6.2** contract.
- Don't rely on Django's `MediaAsset.render(attrs=...)` existing: it is absent
  on 5.2/6.0. `media.py:_render_asset` injects the nonce itself by rebuilding
  the tag from `element_template` + `flatatt`, which works on every version.
- Cross-version gotcha: Django >= 6.2 wraps bare js/css path strings into
  `Script`/`Stylesheet` in `Media._js`/`._css`; older Django keeps raw strings.
  `media.py:_render_{js,css}` wrap any leftover strings via `JS()`/`CSS()`, so
  `_render_asset` always sees a `MediaAsset` (or `JSON`/`ImportMap`).
- **Never test an asset with `isinstance(item, str)`.** `SafeString` is a `str`
  subclass, so `mark_safe('<script src=...></script>')` — a complete tag that
  must render verbatim — would be resolved through `static()` and
  percent-encoded. The predicate is `hasattr(item, "__html__")`; only bare
  paths get wrapped. Django made exactly this mistake in 6.1 (ticket #37262,
  fixed on its 6.1.x branch for 6.1.1), and we had it independently in
  `_render_{js,css}`.
- Because Django 6.1 mangles such strings in `forms.Media.__init__` itself,
  `media.py` also overrides `_normalize_{js,css}` with the `__html__`
  predicate — those hooks are called through `self`, so a subclass can fix
  them, and `_compat` gives us `Script`/`Stylesheet` on every supported Django
  so the wrapped output is unchanged. This covers media built *through* our
  class; assets adopted from a foreign `forms.Media` (`from_media`, `__add__`,
  and Django's widget `media_property`, which always instantiates
  `forms.Media`) arrive already normalized and cannot be recovered on 6.1.
  `test_html_safe_strings_adopted_from_foreign_media` pins that boundary via
  the `DJANGO_KEEPS_HTML_SAFE_STRINGS` probe.
- `tests/testapp/test_media.py` carries `JS_ASSETS`/`CSS_ASSETS`: one row per
  asset kind, each with its exact rendering with and without a nonce. **Add a
  row whenever a new asset kind appears** — that table is the guard against a
  rendering branch quietly mishandling one of them.
  `test_matches_django_rendering` compares us against stock `forms.Media` for
  path assets; it is what catches Django changing its normalization or tag
  format under our overrides.

## Layout

- `js_asset/_compat.py` — `MediaAsset`/`Script`/`Stylesheet`: imported from
  Django where present, backported (with the 6.2 contract) below 5.2/6.1.
- `js_asset/js.py` — `JS`/`CSS` are **factories** (a `_ProducesAsset`
  metaclass): calling them returns a Django `Script`/`Stylesheet`/`InlineStyle`
  so they dedup in `forms.Media.merge` against native assets *and* bare path
  strings; `isinstance(x, JS)` still works via `__instancecheck__`. `JSON` and
  `ImportMap` have no Django counterpart and stay standalone `@html_safe`
  objects with `render(*, nonce="")`. Output is byte-identical to native Django
  assets (flatatt sorts attributes), which the exact-string tests depend on.
  Equality is Django's, so dedup is attribute-aware on 4.2-5.1 + 6.2+ and
  path-only on 5.2-6.1 (`test_set` derives its expectation from this).
  `InlineStyle` renders its CSS **verbatim** (`path` returns `mark_safe`):
  `<style>` is a raw text element, so escaping does not round-trip there and
  `nav &gt; a` would simply not match. The constructor rejects CSS containing
  `</style` — the only sequence which could close the element early — which is
  what keeps the unescaped output safe.
- `js_asset/media.py` — `Media(forms.Media)` subclass: merges embedded
  `ImportMap`s into one tag, applies a nonce, and normalizes js/css entries by
  the `__html__` predicate (see the html-safe-string note above). Implements `__add__` **and**
  `__radd__` so it keeps its type (and nonce) when combined with plain
  `forms.Media` from either side. The nonce lives on the instance (constructor
  `nonce=` or `with_nonce()` returning a copy); `render()` reads it, since
  templates call `render()` with no arguments.
- **Every way *out* of a `Media` must keep the nonce and the import-map
  merging**, not just `render()`: `render_css()`/`render_js()` (public
  `forms.Media` API, and what Django's own `render()` calls) and `__getitem__`
  (`{{ media.css }}`/`{{ media.js }}`; the admin change list renders
  `{% csp_nonce_attr media.js %}`) are overridden for exactly that reason —
  Django's `__getitem__` hardcodes `forms.Media`. Add a test to
  `GetItemTest`/`RenderPartsTest` when a new accessor appears.
- **Never truth-test a nonce that did not come from us.** Django's `LazyNonce`
  (the `csp_nonce` context value, passed straight through by
  `{% csp_nonce_attr media %}`) is falsy until it is first read, and
  `isinstance(nonce, str)` reports the *wrapped* value's class while evaluating
  it. `Media._resolve_nonce` uses `type(nonce) is not str` and resolves lazy
  nonces with `str()` — but only when there is something to render, so an empty
  media does not cause a nonce to be generated.
- Django >= 6.2 has built-in CSP support: the `{% csp_nonce_attr media %}` tag
  (`django.utils.csp.nonce_attr`) renders media via
  `media.render(attrs={"nonce": nonce})`. `Media.render()` therefore accepts
  `attrs=` and honours its nonce — so our `Media` plugs into that tag on 6.2,
  while `with_nonce()`/constructor cover older Django.

## Docs

- `README.rst` — the single doc: assets, import-map merging via `js_asset.Media`,
  rendering in views/admin, and CSP nonces across Django 4.2 → main.

## Lint

`prek` / `ruff` (config in `pyproject.toml`).

## Commit Style

Commit without the `Co-Authored-By` attribution line (no `--co-author` / no `Co-Authored-By: Claude` trailer).
