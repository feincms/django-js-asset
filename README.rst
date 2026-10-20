=============================================================================
django-js-asset -- Script, Stylesheet and JSON support for django.forms.Media
=============================================================================

.. image:: https://github.com/feincms/django-js-asset/workflows/Tests/badge.svg
    :target: https://github.com/feincms/django-js-asset

django-js-asset brings Django's object-based media assets to every supported
Django version and adds what Django doesn't have yet:

* `Script and Stylesheet
  <https://docs.djangoproject.com/en/dev/topics/forms/media/#script-objects>`__
  are Django's own classes where Django has them (``Script`` arrived in 5.2,
  ``Stylesheet`` in 6.1) and backports otherwise.
* ``InlineStyle`` and ``JSON`` render ``<style>`` blocks and JSON data blocks.
* ``ImportMap`` and ``js_asset.Media`` merge the import maps of all media into
  a single ``<script type="importmap">``.
* ``js_asset.Media`` applies CSP nonces on every Django version.

It supports Django 4.2 and newer, up to and including the main branch; the
`tox configuration
<https://github.com/feincms/django-js-asset/blob/main/tox.ini>`_ has the
definitive answers. 5.0 changes import maps and attributes in
backwards-incompatible ways, read the `change log
<https://github.com/feincms/django-js-asset/blob/main/CHANGELOG.rst>`_ before
upgrading.


Assets
======

.. code-block:: python

    from js_asset import JSON, InlineStyle, Script, Stylesheet

    forms.Media(js=[
        JSON({"configuration": 42}, id="widget-configuration"),
        Stylesheet("widget/style.css", media="all"),
        InlineStyle("p{color:red;}"),
        Script("widget/script.js", type="module"),
        Script("widget/data.js", **{"id": "data-script", "data-answer": "42"}),
    ])

This renders (via ``{{ media }}`` or ``{{ media.js }}``):

.. code-block:: html

    <script id="widget-configuration" type="application/json">{"configuration": 42}</script>
    <link href="/static/widget/style.css" media="all" rel="stylesheet">
    <style>p{color:red;}</style>
    <script src="/static/widget/script.js" type="module"></script>
    <script src="/static/widget/data.js" data-answer="42" id="data-script"></script>

Import ``Script`` and ``Stylesheet`` from ``django.forms`` once your project
only supports Django versions which have them. Use ``**{...}`` for attributes
which aren't valid Python identifiers, such as ``data-*`` attributes, which
are a CSP-compatible way to pass data to a script
(``document.querySelector("#data-script").dataset.answer``). Attributes are
escaped.

All assets can go into ``js=[...]``, which is a simple list, while ``css``
needs a dictionary keyed by medium. A stylesheet in ``js`` is only
de-duplicated against that list though, ``forms.Media`` keeps ``css`` in a
separate slot.

Inline CSS is rendered verbatim -- a ``<style>`` element is raw text, so HTML
escapes would not be decoded inside it and would break the CSS instead. For the
same reason the CSS must not contain ``</style``, which would end the element
early; passing such CSS raises a ``ValueError``.

``JS`` and ``CSS`` are deprecated and will be removed in 6.0. They produce
``Script`` and ``Stylesheet`` objects, so replacing them changes nothing
except for one detail: ``CSS(href)`` adds ``media="all"`` when no media is
given, ``Stylesheet(href)`` doesn't. Replace it with
``Stylesheet(href, media="all")``, see below. Other deprecated forms, which
still work until then: an attributes dict (``JS("a.js", {...})``,
``attrs={...}``), a positional media (``CSS("a.css", "print")``) and
``CSS(..., inline=True)`` (use ``InlineStyle``). Deprecations raise a
``js_asset.RemovedInDjangoJsAsset60Warning``, a ``DeprecationWarning``
subclass, so you can turn exactly these into errors, e.g. in your test
settings:

.. code-block:: python

    import warnings

    from js_asset import RemovedInDjangoJsAsset60Warning

    warnings.simplefilter("error", RemovedInDjangoJsAsset60Warning)


Deduplication
=============

``Script`` and ``Stylesheet`` de-duplicate against each other, against plain
path strings and against Django's native assets when ``forms.Media`` merges
the media of several forms and widgets. The rules are Django's, which changed
between releases:

* **Django 4.2 - 5.1 and 6.1+:** two assets are equal when both the path *and*
  the attributes match, so ``Script("a.js", id="x")`` and
  ``Script("a.js", id="y")`` are distinct and both render.
* **Django 5.2 and 6.0:** Django compares the **path only**, so those two
  de-duplicate to one (whichever wins the merge).

A bare path string is equal to a ``Script`` without attributes, and to a
``Stylesheet`` whose ``media`` is the key of the ``css`` dictionary it is
listed under. On Django 6.1+, ``"a.css"`` in ``css={"all": [...]}`` and
``Stylesheet("a.css")`` without ``media`` are distinct and render twice; pass
``media="all"`` to avoid that.


Import maps
===========

`Import maps
<https://developer.mozilla.org/en-US/docs/Web/HTML/Element/script/type/importmap>`__
let your modules import short names (``import { Stuff } from "my-library"``)
and have the browser resolve them to the real, possibly hashed, URLs produced
by Django's ``ManifestStaticFilesStorage`` -- without rewriting the imports in
your JavaScript.

Browsers do not reliably support more than one import map per page, and none
can apply entries to modules which have already been loaded. ``js_asset.Media``
therefore merges them: pass an ``ImportMap`` to your media wherever it is
relevant -- typically next to the module that needs it -- and the import maps of
all media objects added together are combined into a single
``<script type="importmap">``, rendered before every other script:

.. code-block:: python

    from js_asset import ImportMap, Media, Script

    media = Media(
        importmap=ImportMap({"my-library": "my-library.js"}),
        js=[Script("code.js", type="module")],
    )

``ImportMap`` takes the ``imports`` of the import map, and ``scopes=`` and
``integrity=`` keyword arguments for the other parts (passing a full import map
is deprecated). Paths are resolved when rendering, like ``Script`` paths: relative
paths are passed through ``static()``, so defining import maps at module level
works with ``ManifestStaticFilesStorage``. URLs with a scheme (e.g.
``https:``) and paths starting with ``/`` are used as they are. Prefix mappings
such as ``{"my-library/": "my-library/"}`` are resolved too, but ``static()``
doesn't hash directories, so modules loaded through them use their unhashed
names.

Scope prefixes and the URLs in ``integrity`` are never resolved, so
``integrity={"app/a.js": ...}`` doesn't apply to ``/static/app/a.js`` --
``integrity`` needs the final URLs, e.g. of modules loaded from a CDN:

.. code-block:: python

    ImportMap(
        {"lit": "https://cdn.example.com/lit@3/index.js"},
        integrity={"https://cdn.example.com/lit@3/index.js": "sha384-..."},
    )

.. note::

   Integrity metadata for paths resolved through ``static()`` is supposed to
   be added automatically once static files storages can calculate it, as
   proposed by `DEP 0021 <https://github.com/django/deps/pull/122>`__. Explicit
   ``integrity`` entries will then only be needed for other modules.

Import maps are merged when adding media objects, so the media added later
(e.g. the project's) overrides entries of earlier ones (e.g. of apps). Make
sure everything that needs the same map ends up in one merged ``Media``.
``{{ media }}`` renders the import map, the CSS and the JavaScript;
``{{ media.importmap }}`` renders only the import map, and ``{{ media.js }}``
doesn't include it.

Import maps aren't media assets: ``js_asset.Media`` raises a ``TypeError`` when
rendering one from a ``js`` list. Django's ``forms.Media`` doesn't know about
import maps, so widgets and forms can't use ``class Media`` for them. Define
``media`` directly instead:

.. code-block:: python

    class EditorWidget(forms.Textarea):
        media = Media(
            importmap=ImportMap({"editor": "editor/index.js"}),
            js=[Script("editor/init.js", type="module")],
        )

Import maps are subject to ``script-src``, see `CSP nonces`_ for per-request
nonces.


Rendering media in views and the admin
======================================

``js_asset.Media`` renders exactly like ``forms.Media``: ``{{ media }}`` (i.e.
``str(media)``) in a template emits the merged import map followed by every
stylesheet and script -- the import map first, so the modules can rely on it.
What changes from one situation to the next is only how you obtain the right
``Media`` object.

In a front-facing view
~~~~~~~~~~~~~~~~~~~~~~~

When you own the template, build or collect the media in the view and put it in
the context:

.. code-block:: python

    from django.shortcuts import render
    from js_asset import ImportMap, Media, Script

    def dashboard(request):
        media = Media(
            importmap=ImportMap({"chart": "chart/index.js"}),
            js=[Script("dashboard.js", type="module")],
        )
        return render(request, "dashboard.html", {"media": media})

``form.media`` is already a ``js_asset.Media`` as soon as one of its widgets
returns one, so you can render it directly. Combine your own assets with a
form's by simply adding them -- as long as one side is a ``js_asset.Media`` the
result stays one (regardless of order) and merges import maps. If neither side
is, wrap one with ``Media.from_media`` first (``Media(form.media)`` does **not**
work, because ``forms.Media`` copies from a media *definition*, not an
*instance*):

.. code-block:: python

    def edit(request):
        form = MyForm()
        page = Media(
            importmap=ImportMap({"editor": "editor/index.js"}),
            js=[Script("editor/init.js", type="module")],
        )
        media = page + form.media            # or: Media.from_media(form.media)
        return render(request, "edit.html", {"form": form, "media": media})

.. code-block:: html

    {# edit.html #}
    <head>{{ media }}</head>
    ...
    {{ form }}

Attach a per-request CSP nonce with ``media.with_nonce(request.csp_nonce)`` --
see `CSP nonces`_ below.

In the Django admin
~~~~~~~~~~~~~~~~~~~

In the admin you write **no** view code: the admin collects ``ModelAdmin.media``
together with every form's and widget's media itself and renders it in the
change form. All you have to do is make sure the widget that needs the import
map returns a ``js_asset.Media``:

.. code-block:: python

    from django.contrib import admin
    from django import forms
    from js_asset import ImportMap, Media, Script

    class EditorWidget(forms.Textarea):
        media = Media(
            importmap=ImportMap({"editor": "editor/index.js"}),
            js=[Script("editor/init.js", type="module")],
        )

    class ArticleForm(forms.ModelForm):
        class Meta:
            model = Article
            fields = "__all__"
            widgets = {"body": EditorWidget}

    @admin.register(Article)
    class ArticleAdmin(admin.ModelAdmin):
        form = ArticleForm

Because ``js_asset.Media`` keeps its type through the additions Django performs
while combining ``ModelAdmin.media`` with the form media, the object the admin
finally renders is a ``js_asset.Media`` -- so the import maps your widgets
contribute are merged into the single tag automatically, ahead of the admin's
own scripts. The same widget works unchanged outside the admin.

The admin adds ``ModelAdmin.media`` before the media of forms, widgets and
inlines, so an import map on a ``ModelAdmin`` cannot override entries of import
maps added by widgets.

The admin's change list renders ``{{ media.css }}`` and ``{{ media.js }}``
separately, so it doesn't render import maps, e.g. of widgets used with
``list_editable``. Add them using a template which extends the admin's own:

.. code-block:: html+django

    {# templates/admin/change_list.html #}
    {% extends "admin/change_list.html" %}

    {% block extrahead %}{{ media.importmap }}{{ block.super }}{% endblock %}

Use ``{% csp_nonce_attr media.importmap %}`` instead of ``{{ media.importmap }}``
with Django's CSP support (Django 6.1 and newer).


CSP nonces
==========

A CSP nonce is *request-scoped* -- it must change on every response, while
widget media is usually built once at class-definition time -- so the nonce is
applied when the media is rendered, not when it is constructed.
``js_asset.Media`` stores an optional nonce and applies it to every script and
stylesheet it renders. There are a few ways to get the nonce in, depending on
your Django version.

Don't pass a ``nonce`` attribute to assets themselves: Like Django's own
``forms.Media``, rendering such an asset with a nonce raises a ``ValueError``.

Django 6.1 and newer (built-in CSP)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Django 6.1 added the ``csp_nonce_attr`` template tag with ``forms.Media``
support, and ``js_asset.Media`` plugs straight into it -- no extra wiring.
Configure CSP as usual:

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

Django 6.0 (built-in CSP, no ``csp_nonce_attr``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Django 6.0 has the built-in CSP middleware, the ``SECURE_CSP`` setting and the
``csp`` context processor, but not the ``csp_nonce_attr`` tag (that arrived in
6.1). Configure CSP exactly as for `Django 6.1 and newer (built-in CSP)`_
above; the only difference is that you apply the nonce yourself.

Drop in a small tag. The built-in ``{{ csp_nonce }}`` value is lazy and reads as
falsy until first used, so the tag wraps it in ``str()``. It also copes with a
plain ``forms.Media`` -- ``Media(form.media)`` does **not** work, because
``forms.Media`` copies assets from a media *definition*, not an *instance*, so
use ``from_media``:

.. code-block:: python

    # yourapp/templatetags/js_asset_csp.py
    from django import template
    from js_asset import Media

    register = template.Library()

    @register.simple_tag(takes_context=True)
    def media_with_nonce(context, media):
        nonce = context.get("csp_nonce", "")
        if not isinstance(media, Media):
            media = Media.from_media(media)
        return media.with_nonce(str(nonce)).render()

.. code-block:: html

    {% load js_asset_csp %}
    {% media_with_nonce form.media %}

``with_nonce()`` returns a *copy*, so a shared/cached widget ``media`` object is
never mutated and one request's nonce can never leak into another.

Django 4.2 to 5.x (with ``django-csp``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Older Django has no built-in CSP, so use the third-party `django-csp
<https://django-csp.readthedocs.io/>`__ package. Install it, add its
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

Either way the middleware exposes the per-request nonce as
``request.csp_nonce``. It is lazy: django-csp only adds the nonce to the
response header once the value has actually been *used*. Rendering the media
with it counts as using it, so you do not have to do anything special -- just
make sure you render through ``js_asset``. Attach the nonce in the view and
render the copy:

.. code-block:: python

    def my_view(request):
        form = MyForm()
        return render(request, "page.html", {
            "form_media": form.media.with_nonce(request.csp_nonce),
        })

.. code-block:: html

    {{ form_media }}

If you would rather stay in the template, the ``media_with_nonce()`` approach
is exactly the same as for `Django 6.0 (built-in CSP, no csp_nonce_attr)`_ above,
only its *source* changes. The template tag's nonce line can read
``request.csp_nonce`` (the ``request`` context processor must be enabled):

.. code-block:: python

    nonce = getattr(context.get("request"), "csp_nonce", "")

Anywhere: set the nonce explicitly
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can always set the nonce yourself, either on construction or per request:

.. code-block:: python

    Media(nonce=the_nonce, js=[...])               # at construction
    some_media.with_nonce(the_nonce)               # copy with a nonce
    some_media.render(attrs={"nonce": the_nonce})  # one-off render
