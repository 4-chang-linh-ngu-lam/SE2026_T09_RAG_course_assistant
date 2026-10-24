"""Preserve literal Windows arguments, including JSX quotes and multiline prompts."""
import json, subprocess, sys
from pathlib import Path
request=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
result=subprocess.run([request["executable"],*request["arguments"]],capture_output=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.stdout.buffer.flush()
sys.stderr.buffer.flush()
raise SystemExit(result.returncode)
