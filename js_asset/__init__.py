__version__ = "4.1.0"

import contextlib


with contextlib.suppress(ImportError):
    from js_asset.js import *  # noqa: F403
    from js_asset.media import Media  # noqa: F401
