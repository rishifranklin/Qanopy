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

import atexit
import sys
import traceback
import ctypes
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon

from qanopy.ui.main_window import MainWindow
from qanopy.utils.errors import install_qt_exception_hook

import qanopy.resources.resources

def main() -> None:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Qanopy.Qanopy.App")

    app = QApplication(sys.argv)
    app.setApplicationName("Qanopy")
    app.setOrganizationName("Qanopy")

    #  add your desired icon here
    icon = QIcon(":/icons/assets/tech_ram_icon_156951.ico")
    app.setWindowIcon(icon)
    
    # attempt cleanup even on abrupt exit
    window = MainWindow()
    
    atexit.register(window.safe_shutdown)

    # Install exception hook (logs + tries to shutdown CAN gracefully)
    install_qt_exception_hook(window.safe_shutdown)

    window.show()
    window.setWindowIcon(icon)
    sys.exit(app.exec())
