"""Start-up progress on PyInstaller's native splash screen (packaged builds only)."""

STEPS = 6

try:
    import pyi_splash       # only exists inside a PyInstaller build with a splash screen
except ImportError:
    pyi_splash = None


def progress(step, text):
    """Show 'step' of STEPS with a text bar, e.g. '▰▰▰▱▱▱  Loading reflectors…'."""
    if pyi_splash is None:
        return
    try:
        pyi_splash.update_text("▰" * step + "▱" * (STEPS - step) + "  " + text)
    except Exception:  # the splash may already be closed
        pass


def done():
    if pyi_splash is None:
        return
    try:
        pyi_splash.close()
    except Exception:
        pass
