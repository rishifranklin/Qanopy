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
