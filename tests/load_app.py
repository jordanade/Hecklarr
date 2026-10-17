"""Load an isolated Hecklarr server module for each test file."""

import importlib.util
from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).parents[1] / 'src'
SERVER_PATH = SOURCE_ROOT / 'hecklarr' / 'server.py'


def loadApp(module_name):
    """Isolate the server's mutable globals while sharing its pure submodules."""
    source_path = str(SOURCE_ROOT)
    if source_path not in sys.path:
        sys.path.insert(0, source_path)
    spec = importlib.util.spec_from_file_location(f'hecklarr.{module_name}', SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
