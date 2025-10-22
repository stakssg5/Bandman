from __future__ import annotations

import os
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

# Defer heavy imports until after display is up

def main() -> None:
    from pyvirtualdisplay import Display

    # Reasonable size; tall layout like the screenshot
    with Display(visible=0, size=(900, 1600)):
        # Import Tkinter app after Xvfb is active so Tk binds to the virtual display
        import sys
        from pathlib import Path as _P
        repo_root = _P(__file__).resolve().parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from apps.wallet_checker_gui import WalletCheckerApp
        import mss

        app = WalletCheckerApp()

        def snap_and_quit() -> None:
            out_path = ASSETS_DIR / "gui_screenshot.png"
            with mss.mss() as sct:
                sct.shot(output=str(out_path))
            app.destroy()

        # Give it a moment to render and populate
        app.after(1500, snap_and_quit)
        app.mainloop()


if __name__ == "__main__":
    main()
