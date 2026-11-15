"""UTF-8 command output, including redirected pipes on Western Windows hosts."""
import sys


def utf8_console():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
