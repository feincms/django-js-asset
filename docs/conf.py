import os
import sys


sys.path.append(os.path.abspath(".."))

extensions = []

templates_path = ["_templates"]

source_suffix = ".rst"

master_doc = "index"

project = "django-js-asset"
copyright = "2017 - {dt.date.today().year} Feinheit AG"

version = __import__("js_asset").__version__
release = version

pygments_style = "sphinx"

html_theme = "alabaster"

html_static_path = ["_static"]

htmlhelp_basename = "django-js-assetdoc"

latex_documents = [
    (
        "index",
        "django-js-asset.tex",
        "form-designer Documentation",
        "Feinheit AG",
        "manual",
    )
]

man_pages = [
    (
        "index",
        "django-js-asset",
        "form-designer Documentation",
        ["Feinheit AG"],
        1,
    )
]

texinfo_documents = [
    (
        "index",
        "django-js-asset",
        "form-designer Documentation",
        "Feinheit AG",
        "django-js-asset",
        "A simple form designer for Django",
        "Miscellaneous",
    )
]
