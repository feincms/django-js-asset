==========================================================
Assets, import maps and CSP with ``django-js-asset``
==========================================================

This guide shows how the pieces shipped by ``django-js-asset`` fit together:
plain JavaScript/CSS/JSON assets, import maps, the ``js_asset.Media`` subclass,
and Content-Security-Policy (CSP) nonces -- on Django 4.2 all the way up to the
main branch.

If you only want a script tag with a few extra attributes, the ``README`` is
enough. Come here when you want module scripts behind import maps and/or a CSP
nonce on everything ``forms.Media`` renders.


The building blocks
===================

``js_asset`` ships four asset objects and a ``forms.Media`` subclass:

``JS(src, attrs={})``
    A ``<script src="...">`` tag with arbitrary attributes.

``CSS(src, media="all", *, inline=False)``
    A ``<link rel="stylesheet">`` tag, or an inline ``<style>`` block.

``JSON(data, *, id="")``
    A ``<script type="application/json">`` data block.

``ImportMap(importmap)``
    A ``<script type="importmap">`` tag. Import maps merge with ``|`` and, more
    importantly, are merged automatically by ``js_asset.Media`` (see below).

``Media(*, nonce="", css=None, js=None)``
    A drop-in superset of ``django.forms.Media`` that merges import maps and
    applies a CSP nonce.

All of them can live inside a single ``js`` list -- ``css`` is a dictionary
keyed by media type, so passing everything through ``js=[...]`` is simpler and
keeps one predictable source order:

.. code-block:: python

    from js_asset import CSS, JS, JSON, ImportMap, Media

    media = Media(
        js=[
            JSON({"answer": 42}, id="widget-config"),
            CSS("widget/style.css"),
            ImportMap({"imports": {"widget": static("widget/index.js")}}),
            JS("widget/code.js", {"type": "module"}),
        ],
    )

.. note::

   A stylesheet placed in ``js=[...]`` is only de-duplicated against the other
   entries in that list. ``forms.Media`` keeps the ``css`` dictionary and the
   ``js`` list in separate slots, so if the *same* file is also pulled in
   through ``css={...}`` somewhere -- for example via another widget's media
   that gets merged in -- it lives in the other slot and is rendered twice. Put
   a given stylesheet in ``js=[...]`` **or** in ``css={...}``, not both.


Import maps without a global
============================

`Import maps <https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script/type/importmap>`__
let a module import ``"widget"`` and have the browser resolve it to the real,
possibly hashed, URL produced by ``ManifestStaticFilesStorage`` -- without
rewriting the imports in your JavaScript.

Browsers do not (yet) reliably support *multiple* import maps on a page, so all
of them have to be merged into one. ``django-js-asset`` historically did this
with a single global ``importmap`` object (still available, see the
``README``). The drawback is that the global is always the same, regardless of
which assets the current page actually needs.

``js_asset.Media`` removes that limitation: drop ``ImportMap`` objects wherever
they are relevant -- typically next to the module that needs them -- and they
are merged into a single ``<script type="importmap">``, rendered *before* every
other script, no matter how many media objects were combined to get there:

.. code-block:: python

    a = Media(js=[
        ImportMap({"imports": {"htmx": static("htmx.js")}}),
        JS("uses-htmx.js", {"type": "module"}),
    ])
    b = Media(js=[
        ImportMap({"imports": {"chart": static("chart.js")}}),
        JS("uses-chart.js", {"type": "module"}),
    ])

    print(a + b)
    # <script type="importmap">{"imports": {"htmx": "...", "chart": "..."}}</script>
    # <script src="/static/uses-htmx.js" type="module"></script>
    # <script src="/static/uses-chart.js" type="module"></script>

.. warning::

   Pick **one** import-map strategy per page and never mix them. The global
   ``importmap`` (rendered via ``{{ importmap }}``, see the ``README``) and the
   per-``Media`` import maps merged here each emit their *own*
   ``<script type="importmap">``. Browsers only honour the first import map on a
   page and ignore every later one, so combining both styles means some imports
   silently fail to resolve -- a hard-to-debug recipe for disaster. Use the
   global object everywhere, or embed ``ImportMap`` objects in your media
   everywhere; never both.


Why ``js_asset.Media`` is a subclass (and why that is safe)
===========================================================

Django collects the media of a form by adding the media of all its widgets
together. Plain ``forms.Media`` always produces a plain ``forms.Media`` from
``a + b``, so a naive subclass would be silently downgraded the moment it ended
up on the *right-hand side* of an addition.

``js_asset.Media`` implements both ``__add__`` **and** ``__radd__``, so it keeps
its type -- and its nonce -- regardless of operand position. This relies only on
Python's standard operator dispatch (a subclass' ``__radd__`` is tried before
the base class' ``__add__``); **no patching of** ``forms.Media`` **is required**.

In practice: define your widget/form media with ``js_asset.Media`` and the
combined ``form.media`` will be a ``js_asset.Media`` too.

.. code-block:: python

    class MyWidget(forms.Widget):
        @property
        def media(self):
            return Media(js=[
                ImportMap({"imports": {"widget": static("widget/index.js")}}),
                JS("widget/code.js", {"type": "module"}),
            ])


CSP nonces
==========

A CSP nonce is *request-scoped*: it must change on every response, while widget
media is usually built once at class-definition time. So the nonce is applied
when the media is rendered, not when it is constructed.

``js_asset.Media`` stores an optional nonce and applies it to every script and
stylesheet it renders (a ``type="application/json"`` block from ``JSON`` is data,
not executable, and is intentionally left without a nonce). There are three ways
to get the nonce in, depending on your Django version.


Django 6.2 and newer (built-in CSP)
-----------------------------------

Django 6.2 ships CSP support, and ``js_asset.Media`` plugs straight into it --
no extra wiring. Configure CSP as usual:

.. code-block:: python

    # settings.py
    from django.utils.csp import CSP

    MIDDLEWARE = [
        # ...
        "django.middleware.csp.ContentSecurityPolicyMiddleware",
    ]

    SECURE_CSP = {
        "default-src": [CSP.SELF],
        "script-src": [CSP.SELF, CSP.NONCE],
        "style-src": [CSP.SELF, CSP.NONCE],
    }

    TEMPLATES = [{
        # ...
        "OPTIONS": {
            "context_processors": [
                # ...
                "django.template.context_processors.csp",
            ],
        },
    }]

Then render the media with the built-in ``{% csp_nonce_attr %}`` tag, which
calls ``media.render(attrs={"nonce": ...})`` for you:

.. code-block:: html

    {% csp_nonce_attr form.media %}

That single tag emits the merged import map and every script/stylesheet, each
carrying the per-request nonce.


Django 4.2 to 6.1 (with ``django-csp``)
---------------------------------------

Older Django has no built-in nonce, so use the third-party
`django-csp <https://django-csp.readthedocs.io/>`__ package. Install it, add its
middleware, and make sure the nonce is part of the relevant directives.

With django-csp 4.x the policy is a single setting and the nonce is a sentinel
from ``csp.constants``:

.. code-block:: python

    # settings.py (django-csp 4.x)
    from csp.constants import NONCE, SELF

    MIDDLEWARE = [
        # ...
        "csp.middleware.CSPMiddleware",
    ]

    CONTENT_SECURITY_POLICY = {
        "DIRECTIVES": {
            "default-src": [SELF],
            "script-src": [SELF, NONCE],
            "style-src": [SELF, NONCE],
        },
    }

django-csp 3.x uses individual settings instead, and you opt the nonce into
directives with ``CSP_INCLUDE_NONCE_IN``:

.. code-block:: python

    # settings.py (django-csp 3.x)
    CSP_DEFAULT_SRC = ("'self'",)
    CSP_SCRIPT_SRC = ("'self'",)
    CSP_STYLE_SRC = ("'self'",)
    CSP_INCLUDE_NONCE_IN = ("script-src", "style-src")

Either way the middleware exposes the per-request nonce as ``request.csp_nonce``.
It is lazy: django-csp only adds the nonce to the response header once the value
has actually been *used*. Rendering the media with it counts as using it, so you
do not have to do anything special -- just make sure you render through
``js_asset``.

Attach the nonce in the view and render the copy:

.. code-block:: python

    def my_view(request):
        form = MyForm()
        return render(request, "page.html", {
            "form_media": form.media.with_nonce(request.csp_nonce),
        })

.. code-block:: html

    {{ form_media }}

``with_nonce()`` returns a *copy*, so a shared/cached widget ``media`` object is
never mutated and one request's nonce can never leak into another.

If you would rather stay in the template, drop in a small tag (the
``request`` context processor must be enabled). It also copes with a plain
``forms.Media`` -- ``Media(form.media)`` does **not** work, because
``forms.Media`` copies assets from a media *definition*, not an *instance*, so
use ``from_media``:

.. code-block:: python

    # yourapp/templatetags/js_asset_csp.py
    from django import template
    from js_asset import Media

    register = template.Library()

    @register.simple_tag(takes_context=True)
    def media_with_nonce(context, media):
        nonce = getattr(context.get("request"), "csp_nonce", "")
        if not isinstance(media, Media):
            media = Media.from_media(media)
        return media.with_nonce(nonce).render()

.. code-block:: html

    {% load js_asset_csp %}
    {% media_with_nonce form.media %}


Anywhere: set the nonce explicitly
----------------------------------

You can always set the nonce yourself, either on construction or per request:

.. code-block:: python

    Media(nonce=the_nonce, js=[...])      # at construction
    some_media.with_nonce(the_nonce)      # copy with a nonce
    some_media.render(nonce=the_nonce)    # one-off render


A complete example
==================

A widget that needs a module behind an import map, rendered with a nonce on
Django 6.2:

.. code-block:: python

    # widgets.py
    from django import forms
    from js_asset import JS, ImportMap, Media, static

    class EditorWidget(forms.Textarea):
        @property
        def media(self):
            return Media(js=[
                ImportMap({"imports": {"editor": static("editor/index.js")}}),
                JS("editor/init.js", {"type": "module"}),
            ])

.. code-block:: html

    {# template.html, with the CSP context processor enabled #}
    <head>
        {% csp_nonce_attr form.media %}
    </head>

On Django < 6.2, render with the ``{% media_with_nonce form.media %}`` tag from
the previous section instead.

Rendered output (nonce abbreviated):

.. code-block:: html

    <script type="importmap" nonce="r4nd0m">{"imports": {"editor": "/static/editor/index.abc123.js"}}</script>
    <script src="/static/editor/init.js" nonce="r4nd0m" type="module"></script>


Caveats
=======

* The merged import map is always rendered first, so a module added in the same
  media can rely on it.
* Import maps are subject to ``script-src``; make sure ``CSP.NONCE`` is present
  there (and in ``style-src`` if you render stylesheets).
* ``JSON`` blocks are data and deliberately get no nonce.
* Browser support for import maps is still uneven; merging into a single map is
  currently the only portable way to use them in production.
