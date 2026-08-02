# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Put the add-on's own directory on the path.

The add-on is loaded by Anki as a package under `addons21/`, so it has no
importable name from the repo root. The two modules worth testing —
`render` and `topics` — import nothing from `aqt`, precisely so they can be
imported here without a Qt event loop.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
