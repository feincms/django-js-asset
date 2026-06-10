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
- Don't rely on Django 6.2's `Media.render(attrs=...)` / `MediaAsset` /
  `Script` machinery. js_asset does its own nonce rendering so it works on 4.2.
- Cross-version gotcha: Django >= 6.2 wraps bare js/css path strings into
  `MediaAsset` objects in `Media._js`/`._css`; older Django keeps raw strings.
  `js_asset/media.py:_render_asset` handles both.

## Layout

- `js_asset/js.py` — `CSS`, `JS`, `JSON`, `ImportMap` assets and the global
  `importmap`. Each asset has `render(*, nonce="")`; `__str__` delegates to it,
  and output is byte-identical when no nonce is given (existing exact-string
  tests depend on this).
- `js_asset/media.py` — `Media(forms.Media)` subclass: merges embedded
  `ImportMap`s into one tag and applies a nonce. Implements `__add__` **and**
  `__radd__` so it keeps its type (and nonce) when combined with plain
  `forms.Media` from either side. The nonce lives on the instance (constructor
  `nonce=` or `with_nonce()` returning a copy); `render()` reads it, since
  templates call `render()` with no arguments.
- Django >= 6.2 has built-in CSP support: the `{% csp_nonce_attr media %}` tag
  (`django.utils.csp.nonce_attr`) renders media via
  `media.render(attrs={"nonce": nonce})`. `Media.render()` therefore accepts
  `attrs=` and honours its nonce — so our `Media` plugs into that tag on 6.2,
  while `with_nonce()`/constructor cover older Django.

## Docs

- `README.rst` — basic usage + the legacy global `importmap`.
- `docs/assets-importmaps-and-csp.rst` — full guide: assets, import-map
  merging via `js_asset.Media`, and CSP nonces across Django 4.2 → main.

## Lint

`prek` / `ruff` (config in `pyproject.toml`).

## Commit Style

Commit without the `Co-Authored-By` attribution line (no `--co-author` / no `Co-Authored-By: Claude` trailer).
