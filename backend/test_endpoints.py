"""Convenience launcher for the end-to-end suite at the repository root.

The suite itself lives in ``test_endpoints.py`` at the project root so that it
can import ``app.*`` from ``backend/``. This shim exists so the documented
verification command (``py backend/test_endpoints.py``) works from any cwd.
"""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent.parent / "test_endpoints.py"),
    run_name="__main__",
)
