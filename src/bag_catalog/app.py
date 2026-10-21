"""Command-line entry point."""
import argparse
import os
import sys

from PySide6.QtCore import QLoggingCategory
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from .config import DEFAULT_ROOT
from .icons import APP_ICON
from .model import MAX_ROOTS

PREFERRED_FONTS = ("Ubuntu Sans", "Inter", "Cantarell", "Noto Sans")


def print_profile(roots):
    from . import profile
    from .fmt import home_short
    from .prefs import saved_roots
    roots = [os.path.abspath(os.path.expanduser(r)) for r in roots] or saved_roots() or [DEFAULT_ROOT]
    layers = profile.load(roots)
    for e in layers.errors:
        print(f"profile: {e}", file=sys.stderr)
    header = "All bag-catalog settings in effect for " + ", ".join(map(home_short, roots)) + "\n" + (
        "from " + ", ".join(map(home_short, layers.used)) if layers.used else "(all built-in defaults)")
    sys.stdout.write(profile.dump(layers.values, header + "\n\n" + profile.SHARE_HEADER))
    return 0


def main(argv=None):
    argv = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(prog="bag-catalog", description="Browse rosbag2 recordings.")
    parser.add_argument("roots", nargs="*", metavar="FOLDER",
                        help=f"up to {MAX_ROOTS} folders to scan (default: the folders open last time, "
                             f"else {DEFAULT_ROOT})")
    parser.add_argument("--theme", choices=["auto", "light", "dark"], default=os.environ.get("BAG_CATALOG_THEME"),
                        help="colour scheme for this session (default: as chosen in Settings, else follow the desktop)")
    parser.add_argument("--print-profile", action="store_true",
                        help="print the settings in use for these folders as a commented profile file, "
                             "to start your own or share them")
    args = parser.parse_args(argv[1:])
    if len(args.roots) > MAX_ROOTS:
        parser.error(f"at most {MAX_ROOTS} folders")
    if args.print_profile:
        return print_profile(args.roots)

    # Closing a popup with a text field (e.g. the Gaps menu) on Wayland makes Qt warn that the keyboard
    # focus left an already destroyed surface. Harmless; QT_LOGGING_RULES can turn it back on.
    QLoggingCategory.setFilterRules("qt.qpa.wayland.textinput.warning=false")
    QApplication.setApplicationName("Bag Catalog")
    QApplication.setDesktopFileName("bag-catalog")
    app = QApplication(argv[:1])
    app.setStyle("Fusion")
    families = set(QFontDatabase.families())
    family = next((f for f in PREFERRED_FONTS if f in families), None)
    if family:
        app.setFont(QFont(family, 10))
    app.setWindowIcon(QIcon(APP_ICON))

    from .prefs import saved_roots
    from .ui.window import CatalogWindow  # after the app font is set; widgets read it on creation
    roots = [os.path.abspath(os.path.expanduser(r)) for r in args.roots] or saved_roots() or [DEFAULT_ROOT]
    win = CatalogWindow(roots, args.theme)
    win.show()
    return app.exec()
