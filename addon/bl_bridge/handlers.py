"""Hub: importing this module loads the core and every feature module, so all handlers are registered."""

import importlib

from . import FEATURES
from .core import *  # noqa: F401,F403
from .core import HANDLERS, call  # noqa: F401

for _name in FEATURES:
    importlib.import_module(f"{__package__}.{_name}")
