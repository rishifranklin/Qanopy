from __future__ import annotations

import random
from PyQt6.QtGui import QColor


def random_dark_qcolor() -> QColor:
    """
    Random dark-ish vivid color.
    HSV: sat high, value medium-low.
    """
    h = random.randint(0, 359)
    s = random.randint(180, 255)
    v = random.randint(90, 160)
    c = QColor()
    c.setHsv(h, s, v)
    return c
