import os
import sys

from PyQt6.QtWidgets import QApplication

from app.splash import SplashScreen
from app.window import DefectDetectionGUI

LOGO_PATH = os.path.join(os.path.dirname(__file__), "image", "logo.png")


def main():
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
