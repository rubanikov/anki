# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Put the corpus package's own directory on the path.

The corpus tools are scripts run from a checkout, not an installed package, so
they have no importable dotted name. Same arrangement as the add-on's tests.
"""

import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

sys.path.insert(0, str(CORPUS_DIR))
