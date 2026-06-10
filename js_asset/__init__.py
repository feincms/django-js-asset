__version__ = "3.1.2"

import contextlib


with contextlib.suppress(ImportError):
    from js_asset.js import *  # noqa: F403
    from js_asset.media import Media  # noqa: F401
