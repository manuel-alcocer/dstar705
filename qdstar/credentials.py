"""Passwords and tokens in the system keyring (Secret Service/KWallet, Windows Credential Manager).

Without a usable keyring they fall back to QDStar's settings file, like the radio password,
and the caller is told so it can warn the user. Secrets are never logged.
"""

from . import config

SERVICE = "QDStar"
FALLBACK_PREFIX = "credentials/"


def _keyring():
    try:
        import keyring
        from keyring.backends import fail
        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring):
            return None
        return keyring
    except Exception:       # not installed, or no D-Bus / backend at all
        return None


def available():
    """True when secrets go to the system keyring."""
    return _keyring() is not None


def store(key, secret):
    """Save (or with an empty secret, delete) a secret. Returns 'keyring' or 'settings'."""
    kr = _keyring()
    if kr is not None:
        try:
            if secret:
                kr.set_password(SERVICE, key, secret)
            else:
                try:
                    kr.delete_password(SERVICE, key)
                except Exception:
                    pass
            config.settings().remove(FALLBACK_PREFIX + key)   # no stale copy in the settings file
            return "keyring"
        except Exception:
            pass
    if secret:
        config.put(FALLBACK_PREFIX + key, secret)
    else:
        config.settings().remove(FALLBACK_PREFIX + key)
    return "settings"


def load(key):
    kr = _keyring()
    if kr is not None:
        try:
            secret = kr.get_password(SERVICE, key)
            if secret:
                return secret
        except Exception:
            pass
    return config.settings().value(FALLBACK_PREFIX + key, "") or ""
