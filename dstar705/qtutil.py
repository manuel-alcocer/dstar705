"""Small Qt helpers."""


def safe_emit(signal, *args):
    """Emit from a worker thread; the receiving QObject may already be gone at shutdown."""
    try:
        signal.emit(*args)
    except RuntimeError:
        pass
