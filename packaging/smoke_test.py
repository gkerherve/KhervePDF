"""Launch the frozen KhervePDF on a generated PDF and check it stays up.

    python packaging/smoke_test.py <path to KhervePDF executable>

Startup is where a freeze breaks (a missing module, Qt plugin or DLL
kills the process at once), so a process still alive after 20 s with a
PDF open is the pass. Runs offscreen so it works on a headless runner.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    exe = Path(sys.argv[1]).resolve()
    import pymupdf
    tmp = Path(tempfile.mkdtemp())
    pdf = tmp / "smoke.pdf"
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page().insert_text((72, 72), f"KhervePDF smoke test, page {i + 1}")
    doc.save(pdf)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    log = tmp / "khervepdf-smoke.log"
    with open(log, "w") as fh:
        proc = subprocess.Popen([str(exe), str(pdf)], stdout=fh, stderr=subprocess.STDOUT, env=env)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            print("KhervePDF still running after 20 s with a PDF open: OK")
            return 0
    print(log.read_text(errors="replace")[-4000:])
    print(f"KhervePDF exited early with code {proc.returncode}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
