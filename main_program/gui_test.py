import os
import sys

import cv2
from PyQt6.QtWidgets import QApplication

from app.splash import SplashScreen
from app.window import DefectDetectionGUI

LOGO_PATH = os.path.join(os.path.dirname(__file__), "image", "logo.png")


def main():
    # OpenCV's Linux wheels set paths for their bundled Qt, which can
    # conflict with PyQt6. Keep any paths explicitly configured elsewhere.
    cv2_dir = os.path.dirname(os.path.realpath(cv2.__file__))
    for key in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_FONTDIR"):
        value = os.environ.get(key)
        if value and os.path.realpath(value).startswith(cv2_dir + os.sep):
            os.environ.pop(key)

    app = QApplication(sys.argv)

    splash = SplashScreen(LOGO_PATH, duration_ms=1000)

    window = DefectDetectionGUI()

    def _launch():
        splash.finish(window)
        window.show()

    splash.show_and_close_after(_launch)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
