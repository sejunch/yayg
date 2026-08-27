#!/usr/bin/env python3
"""yayg 실행: python3 run.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yayg.app import main

if __name__ == "__main__":
    raise SystemExit(main())
