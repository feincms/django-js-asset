import datetime as dt
import re
from pathlib import Path


extensions = []

templates_path = ["_templates"]

source_suffix = ".rst"

master_doc = "index"

project = "django-js-asset"
copyright = f"2017 - {dt.date.today().year} Feinheit AG"

# Read the version like hatch does, importing js_asset would require Django.
version = re.search(
    r'__version__ = "([^"]+)"',
    (Path(__file__).parent.parent / "js_asset" / "__init__.py").read_text(),
)[1]
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
