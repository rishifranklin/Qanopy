"""
Copyright 2026 [Rishi Franklin]

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

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
