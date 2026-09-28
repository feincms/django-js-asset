__version__ = "5.0a1"

import contextlib


with contextlib.suppress(ImportError):
    from js_asset.js import *  # noqa: F403
    from js_asset.media import Media  # noqa: F401
