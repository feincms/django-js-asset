
.. _changelog:

Change log
==========

Next version
~~~~~~~~~~~~

4.1 (2026-08-28)
~~~~~~~~~~~~~~~~

- Fixed ``js_asset.Media`` crashing with an ``AttributeError`` when rendering an
  asset that only implements Django's plain ``__html__`` contract (neither a
  ``MediaAsset`` nor one of our ``ImportMap``/``JSON`` types). Such assets now
  fall back to ``__html__()`` exactly like ``django.forms.Media`` does; the
  nonce cannot be threaded into an opaque ``__html__`` asset, same as with stock
  Django.
- Fixed ``js_asset.Media`` treating html-safe strings -- e.g.
  ``mark_safe('<script defer src="..."></script>')``, a long-documented Django
  idiom for embedding a complete asset tag -- as asset paths, so they were run
  through ``static()`` and percent-encoded instead of being rendered verbatim.
  Anything providing ``__html__()`` now takes the verbatim path, matching
  ``django.forms.Media`` (see Django's ticket #37262).
- ``js_asset.Media`` additionally renders html-safe strings correctly on Django
  6.1, whose own ``forms.Media`` mangles them (fixed in Django for 6.1.1). Only
  media built through ``js_asset.Media`` benefits; assets adopted from a plain
  ``forms.Media`` -- including widget ``Media`` declarations, which Django
  always builds with ``forms.Media`` -- are already normalized before we see
  them.
- Fixed ``js_asset.Media`` dropping the CSP nonce when rendering through
  Django's ``{% csp_nonce_attr media %}`` template tag. The tag passes the lazy
  ``csp_nonce`` object, which is deliberately falsy until it is first read, so
  truth-testing it looked like "no nonce at all". Lazy nonces are now resolved
  (still only when there is something to render, so an empty media does not
  cause a nonce to be generated).
- Fixed ``js_asset.Media.render_css()`` and ``.render_js()`` -- part of
  ``forms.Media``'s public API -- rendering neither the CSP nonce nor the merged
  import map. Only the full ``render()`` did.
- Fixed ``media["css"]`` / ``media["js"]`` -- what ``{{ media.css }}`` and
  ``{{ media.js }}`` resolve to in templates, and what Django's admin renders
  with ``{% csp_nonce_attr media.js %}`` -- returning a plain
  ``django.forms.Media``, therefore losing the CSP nonce and the import-map
  merging. They now return a ``js_asset.Media`` carrying the same nonce.
- Fixed inline CSS (``CSS(css, inline=True)``) being HTML-escaped. A
  ``<style>`` element is raw text -- character references are not decoded inside
  it -- so escaping silently broke every rule containing ``>``, ``"``, ``'`` or
  ``&``: ``nav &gt; a`` matches nothing. Inline CSS now renders verbatim, and
  CSS containing ``</style`` (the one sequence which could close the element
  early) is rejected with a ``ValueError``.
- Corrected the docs around Django 6.1 support. Thanks James Bligh!
- Finally set up a documentation site at Read the Docs for django-js-asset.


4.0 (2026-06-11)
~~~~~~~~~~~~~~~~

This is a major release. Most code keeps working unchanged and the rendered
HTML is the same, but **if you use import maps the upgrade is not automatic** --
see the import-map note at the end.

- Added ``js_asset.Media``, a ``django.forms.Media`` subclass with two extra
  abilities. First, it merges every embedded ``ImportMap`` into a single
  ``<script type="importmap">`` rendered before any other script -- this
  replaces the old global ``importmap`` object and works no matter how many
  media objects Django combines. Second, it applies a request-scoped CSP nonce
  to the tags it renders. It implements ``__add__`` **and** ``__radd__``, so it
  keeps its type -- and its nonce -- when combined with a plain ``forms.Media``
  from either side (e.g. while Django collects form and widget media). The nonce
  can be passed to the constructor (``nonce=``), copied onto a clone with
  ``with_nonce()``, or passed to ``render(nonce=...)``; ``render()`` also accepts
  ``attrs={"nonce": ...}`` so it plugs straight into Django 6.2's
  ``{% csp_nonce_attr %}`` tag. ``Media.from_media()`` wraps an existing
  ``forms.Media`` instance (e.g. ``form.media``).
- ``JS`` and ``CSS`` now *produce* Django's own ``Script`` and ``Stylesheet``
  objects (backported via ``js_asset._compat`` on Django versions that lack
  them) instead of being standalone dataclasses. They therefore share merge
  buckets with native Django assets and with bare path strings, so the same
  file is no longer rendered more than once when ``js_asset`` assets, plain
  strings and Django's auto-wrapped assets meet in ``forms.Media.merge()``.
  ``isinstance(x, JS)`` / ``isinstance(x, CSS)`` keep working (via a metaclass).
  Inline CSS (``CSS(src, inline=True)``) is rendered by a small dedicated
  ``InlineStyle`` asset. Rendered output is unchanged.
- ``Script``, ``Stylesheet``, ``MediaAsset`` and ``InlineStyle`` can now be
  imported from ``js_asset`` -- prefer these in ``isinstance`` checks over
  ``JS``/``CSS`` going forward.
- Equality now follows Django's own contract: identity is attribute-aware on
  Django 4.2–5.1 and 6.2+, and path-only on 5.2–6.1 (matching native Django on
  those versions). Previously all fields were part of identity on every
  version. If you relied on ``JS``/``CSS`` objects with differing attributes for
  the same path staying distinct, note that they de-duplicate on 5.2–6.1.
- Added a ``static_lazy`` helper (a lazy wrapper around ``static()``, handy for
  values resolved at import time such as import-map entries).
- **Backwards-incompatible (import maps):** Removed the global ``importmap``
  object and the ``js_asset.context_processors.importmap`` context processor.
  Instead, embed ``ImportMap`` objects directly in a ``js_asset.Media`` next to
  the assets that need them; they are merged into a single
  ``<script type="importmap">`` automatically. To upgrade: render the relevant
  media as a ``js_asset.Media`` (e.g. via your widgets, or ``Media.from_media``),
  and remove both ``js_asset.context_processors.importmap`` from your
  ``TEMPLATES`` and every ``{{ importmap }}`` tag from your templates.


3.1 (2025-02-28)
~~~~~~~~~~~~~~~~

- Made the ``id`` argument to ``JSON`` keyword-only. Also made the ``inline``
  argument to ``CSS`` keyword-only.
- Added the ``media`` attribute to ``CSS`` classes.
- Added experimental support for shipping importmaps.


3.0 (2024-12-17)
~~~~~~~~~~~~~~~~

- Rewrite the internals using dataclasses, drop compatibility with Django < 4.2
  and Python < 3.10.
- Added a ``CSS`` and ``JSON`` class which can also be used with
  ``forms.Media``. It's recommended to pass them as JavaScript entries to
  ``forms.Media(js=[])`` because the ``js`` list doesn't use a media
  dictionary.
- Added Django 5.1, Python 3.13.


2.2 (2023-12-12)
~~~~~~~~~~~~~~~~

- Started running the tests periodically to detect breakages early.
- Added Django 5.0, Python 3.12.
- Fixed building with hatchling 1.19. Thanks Michał Górny!


2.1 (2023-06-28)
~~~~~~~~~~~~~~~~

- Added Django 4.1, 4.2 and Python 3.11 to the CI.
- Removed the pytz dependency from the tests.
- Dropped Python < 3.8, Django < 3.2 from the CI.
- Switched to hatchling and ruff.


`2.0`_ (2022-02-10)
~~~~~~~~~~~~~~~~~~~

.. _2.0: https://github.com/feincms/django-js-asset/compare/1.2...2.0

- Raised the minimum supported versions of Python to 3.6, Django to 2.2.
- Added pre-commit.
- Replaced the explicit configuration of whether ``static()`` should be used or
  not with automatic configuration. The ``static`` argument is still accepted
  but ignored and will be removed at a later time.
- Added support for boolean attributes when using Django 4.1 or better.


Released as 1.2.1 and 1.2.2:
----------------------------

- Made ``JS()`` objects hashable so that they can be put into sets in
  preparation for a possible fix for media ordering in Django #30179.
- Confirmed support for Django 3.0 and 3.1a1.
- Django dropped ``type="text/javascript"`` in 3.1, changed our tests to
  pass again.
- Switched from Travis CI to GitHub actions.
- Dropped Django 1.7 from the CI jobs list because it somehow didn't
  discover our tests.
- Renamed the main branch to ``main``.
- Added CI testing for Django 3.2.


`1.2`_ (2019-02-08)
~~~~~~~~~~~~~~~~~~~

- Reformatted the code using Black.
- Added equality of ``JS()`` objects to avoid adding the same script
  more than once in the same configuration.
- Determine the ``static`` callable at module import time, not each time
  a static path is generated.
- Customized the ``repr()`` of ``JS()`` objects.
- Added Python 3.7 and Django 2.2 to the test matrix.


`1.1`_ (2018-04-19)
~~~~~~~~~~~~~~~~~~~

- Added support for skipping ``static()``, mostly useful when adding
  external scripts via ``JS()`` (e.g for adding ``defer="defer"``).
- Made the attributes dictionary optional.


`1.0`_ (2018-01-16)
~~~~~~~~~~~~~~~~~~~

- Added an export of the ``js_asset.static()`` helper (which does the
  right thing regarding ``django.contrib.staticfiles``)
- Fixed the documentation to not mention internal (and removed) API of
  Django's ``Media()`` class.
- Switched to using tox_ for running tests and style checks locally.
- Added more versions of Python and Django to the CI matrix.


`0.1`_ (2017-04-19)
~~~~~~~~~~~~~~~~~~~

- Initial public release extracted from django-content-editor_.


.. _Django: https://www.djangoproject.com/
.. _django-content-editor: https://django-content-editor.readthedocs.io/
.. _tox: https://tox.readthedocs.io/

.. _0.1: https://github.com/feincms/django-js-asset/commit/e335c79a87
.. _1.0: https://github.com/feincms/django-js-asset/compare/0.1...1.0
.. _1.1: https://github.com/feincms/django-js-asset/compare/1.0...1.1
.. _1.2: https://github.com/feincms/django-js-asset/compare/1.1...1.2
