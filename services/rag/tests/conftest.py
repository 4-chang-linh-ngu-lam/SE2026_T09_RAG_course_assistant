import os
from pathlib import Path

# A local optional Poppler install does not require a machine-wide PATH change.
binary = next(
    (Path(__file__).parents[1] / ".venv/poppler").glob("*/Library/bin/pdftotext.exe"),
    None,
)
if binary is not None:
    os.environ["PATH"] = str(binary.parent) + os.pathsep + os.environ.get("PATH", "")
