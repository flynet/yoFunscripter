"""Entry point of `python -m yofunscripter` and of the packaged program."""

import sys

from yofunscripter.ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
