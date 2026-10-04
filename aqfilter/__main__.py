"""Allow ``python -m aqfilter ...``."""

from aqfilter.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
