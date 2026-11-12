#!/usr/bin/env python3
"""
Backward-compatibility shim for moved cll/search.py.
Delegates to cll.search.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from cll.search import main

if __name__ == "__main__":
    main()
