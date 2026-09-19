"""CI execution envelope. Statistical source is identical to the verified local run."""
from pathlib import Path
import json,os
from threadpoolctl import threadpool_limits
from . import study
try:
    with threadpool_limits(limits=1):study.run()
finally:
    p=study.OUT/'execution_status.json'
    if p.exists():
        status=json.loads(p.read_text())
        # Replace the local entrypoint's default location with the actual CI envelope.
        status.update(execution_location='GitHub Actions',github_commit=os.environ.get('GITHUB_SHA'),github_run=os.environ.get('GITHUB_RUN_ID'))
        p.write_text(json.dumps(status,indent=2))
