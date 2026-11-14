import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pgserver
import psycopg

bins = Path(pgserver.__file__).parent / "pginstall/bin"
with tempfile.TemporaryDirectory(prefix="vt034_pg_") as directory:
    data = Path(directory) / "data"
    subprocess.run(
        [
            str(bins / "initdb"),
            "-D",
            str(data),
            "-E",
            "UTF8",
            "-A",
            "trust",
            "-U",
            "agent",
            "--no-locale",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (Path(directory) / "server.log").open("w") as log:
        process = subprocess.Popen(
            [str(bins / "postgres"), "-D", str(data), "-k", "", "-h", "127.0.0.1", "-p", str(port)],
            stdout=log,
            stderr=log,
        )
        uri = f"postgresql://agent@127.0.0.1:{port}/postgres"
        try:
            for _ in range(100):
                try:
                    with psycopg.connect(uri):
                        pass
                    break
                except psycopg.OperationalError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("Postgres did not start")
            env = dict(
                os.environ,
                TEST_DATABASE_URL=uri.replace("postgresql:", "postgresql+psycopg:"),
                PYTHONPATH=".",
            )
            result = subprocess.run(sys.argv[1:], env=env, check=False)
        finally:
            process.terminate()
            process.wait(timeout=10)
    sys.exit(result.returncode)
