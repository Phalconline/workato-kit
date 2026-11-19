"""Offline tests of the repository tooling: no Workato call, no network, no real credential.

Importing this package puts scripts/ on sys.path, so a test imports a script by its module name
(`import sync_recipes`) and the shared code as `from lib import cli, wkrepo`.
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
