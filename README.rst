==================================================================
django-js-asset -- JS, CSS and JSON support for django.forms.Media
==================================================================

.. image:: https://github.com/feincms/django-js-asset/workflows/Tests/badge.svg
    :target: https://github.com/feincms/django-js-asset

**Note!** `Django 5.2 adds its own support for JavaScript objects
<https://docs.djangoproject.com/en/dev/topics/forms/media/#script-objects>`__.
This library has a slightly different API and also supports much older versions
of Django, *and* it also supports CSS and JSON tags. As of the next version
``JS`` and ``CSS`` actually *produce* Django's own ``Script`` and ``Stylesheet``
objects (backported on Django versions that lack them), so js_asset assets,
plain path strings and Django's native assets share the same de-duplication
buckets in ``forms.Media`` -- see `Deduplication`_ below.

.. warning::

   **Upgrading from 3.x?** django-js-asset 4.0 is somewhat different, especially
   if you use **import maps**: the global ``importmap`` object and its context
   processor have been removed in favour of merging ``ImportMap`` objects
   through the new ``js_asset.Media`` class (see `Import maps`_ below). Read the
   `change log
   <https://github.com/feincms/django-js-asset/blob/main/CHANGELOG.rst>`_ before
   upgrading.

Usage
=====

Use this to insert a script tag via ``forms.Media`` containing additional
attributes (such as ``id`` and ``data-*`` for CSP-compatible data
injection.):

.. code-block:: python

    from js_asset import JS

    forms.Media(js=[
        JS("asset.js", {
            "id": "asset-script",
            "data-answer": "42",
        }),
    ])

The rendered media tag (via ``{{ media.js }}`` or ``{{ media }}`` will
now contain a script tag as follows, without line breaks:

.. code-block:: html

    <script type="text/javascript" src="/static/asset.js"
        data-answer="42" id="asset-script"></script>

The attributes are automatically escaped. The data attributes may now be
accessed inside ``asset.js``:

.. code-block:: javascript

    let answer = document.querySelector("#asset-script").dataset.answer;

Also, because the implementation of ``static`` differs between supported
Django versions (older do not take the presence of
``django.contrib.staticfiles`` in ``INSTALLED_APPS`` into account), a
``js_asset.static`` function is provided which does the right thing
automatically.


CSS and JSON support
====================

Since 3.0 django-js-asset also ships a ``CSS`` and ``JSON`` media object which
can be used to ship stylesheets, inline styles and JSON blobs to the frontend.
It's recommended to pass those through ``forms.Media(js=[])`` as well since
``js`` is a simple list while ``css`` uses a dictionary keyed with the media to
use for the stylesheet.

So, you can add everything at once:

.. code-block:: python

    from js_asset import CSS, JS, JSON

    forms.Media(js=[
        JSON({"configuration": 42}, id="widget-configuration"),
        CSS("widget/style.css"),
        CSS("p{color:red;}", inline=True),
        JS("widget/script.js", {"type": "module"}),
    ])

This produces:

.. code-block:: html

    <script id="widget-configuration" type="application/json">{"configuration": 42}</script>
    <link href="/static/widget/style.css" media="all" rel="stylesheet">
    <style media="all">p{color:red;}</style>
    <script src="/static/widget/script.js" type="module"></script>



Compatibility
=============

At the time of writing this app is compatible with Django 4.2 and better
(up to and including the Django main branch), but have a look at the
`tox configuration
<https://github.com/feincms/django-js-asset/blob/main/tox.ini>`_ for
definitive answers.


Deduplication
=============

``JS`` and ``CSS`` produce Django's own ``Script`` and ``Stylesheet`` objects
(backported on Django versions that lack them), so they de-duplicate against
each other, against plain path strings, and against Django's native assets when
``forms.Media`` merges the media of several forms and widgets. The rules for
what counts as a duplicate are Django's, and Django changed them between
releases:

* **Django 4.2 - 5.1 and 6.2+:** two assets are equal when both the path *and*
  the attributes match, so ``JS("a.js", {"id": "x"})`` and
  ``JS("a.js", {"id": "y"})`` are distinct and both render.
* **Django 5.2 - 6.1:** Django compares the **path only**, so those same two
  assets de-duplicate to one (whichever wins the merge) -- exactly as Django's
  own ``Script``/``Stylesheet`` behave on those versions.

A given file referenced both as a bare string and via ``JS``/``CSS`` always
de-duplicates, and nothing is ever rendered twice for the same path. The
per-version difference only affects the unusual case of the same path carried
with *different* attributes in a single merge.


Import maps
===========

django-js-asset can ship `import maps
<https://developer.mozilla.org/en-US/docs/Web/HTML/Element/script/type/importmap>`__.
They let your modules import short names (``import { Stuff } from
"my-library"``) and have the browser resolve them to the real, possibly hashed,
URLs produced by Django's ``ManifestStaticFilesStorage`` -- without rewriting
the imports in your JavaScript.

Browsers do not reliably support more than one import map per page, so all of
them have to be merged into one. ``js_asset.Media`` does this for you: drop
``ImportMap`` objects into your media wherever they are relevant -- typically
next to the module that needs them -- and they are combined into a single
``<script type="importmap">`` rendered before every other script, no matter how
many media objects were added together to get there:

.. code-block:: python

    from js_asset import ImportMap, JS, Media, static_lazy

    media = Media(js=[
        ImportMap({"imports": {"my-library": static_lazy("my-library.js")}}),
        JS("code.js", {"type": "module"}),
    ])

See `CSP nonces`_ below for per-request nonces.

.. note::

   Earlier releases shipped a single global ``importmap`` object plus a context
   processor (rendered via ``{{ importmap }}``). That approach has been removed
   in favour of the per-``Media`` merging shown above; use ``js_asset.Media``
   instead.


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
    from js_asset import ImportMap, JS, Media, static

    def dashboard(request):
        media = Media(js=[
            ImportMap({"imports": {"chart": static("chart/index.js")}}),
            JS("dashboard.js", {"type": "module"}),
        ])
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
        page = Media(js=[
            ImportMap({"imports": {"editor": static("editor/index.js")}}),
            JS("editor/init.js", {"type": "module"}),
        ])
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
    from js_asset import ImportMap, JS, Media, static

    class EditorWidget(forms.Textarea):
        @property
        def media(self):
            return Media(js=[
                ImportMap({"imports": {"editor": static("editor/index.js")}}),
                JS("editor/init.js", {"type": "module"}),
            ])

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


CSP nonces
==========

A CSP nonce is *request-scoped* -- it must change on every response, while
widget media is usually built once at class-definition time -- so the nonce is
applied when the media is rendered, not when it is constructed.
``js_asset.Media`` stores an optional nonce and applies it to every script and
stylesheet it renders (a ``JSON`` block is data, not executable, and
deliberately gets none). There are three ways to get the nonce in, depending on
your Django version.

Django 6.1 and newer (built-in CSP)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Django 6.1 ships CSP support, and ``js_asset.Media`` plugs straight into it --
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

Django 4.2 to 6.0 (with ``django-csp``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Older Django has no built-in nonce, so use the third-party `django-csp
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

``with_nonce()`` returns a *copy*, so a shared/cached widget ``media`` object is
never mutated and one request's nonce can never leak into another. If you would
rather stay in the template, drop in a small tag (the ``request`` context
processor must be enabled). It also copes with a plain ``forms.Media`` --
``Media(form.media)`` does **not** work, because ``forms.Media`` copies assets
from a media *definition*, not an *instance*, so use ``from_media``:

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can always set the nonce yourself, either on construction or per request:

.. code-block:: python

    Media(nonce=the_nonce, js=[...])      # at construction
    some_media.with_nonce(the_nonce)      # copy with a nonce
    some_media.render(nonce=the_nonce)    # one-off render


Notes
=====

* The merged import map is always rendered first, so a module added in the same
  media can rely on it.
* Browsers honour only the **first** import map on a page; make sure everything
  that needs the same map ends up in one merged ``Media`` -- a second
  ``<script type="importmap">`` reaching the page some other way is silently
  ignored.
* Import maps are subject to ``script-src``; make sure ``CSP.NONCE`` is present
  there (and in ``style-src`` if you render stylesheets).
* A stylesheet placed in ``js=[...]`` is only de-duplicated against that list.
  ``forms.Media`` keeps the ``css={...}`` dictionary in a separate slot, so the
  same file listed in both renders twice -- pick one.
* ``JSON`` blocks are data and deliberately get no nonce.
* Browser support for import maps is still uneven; merging into a single map is
  currently the only portable way to use them in production.
