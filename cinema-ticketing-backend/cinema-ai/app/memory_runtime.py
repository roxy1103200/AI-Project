"""Launch local memory services with explicit paths and dotenv configuration."""

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


def main() -> None:
    """Start the persistent loopback server or private index worker."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", choices=["chroma", "memory"], required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    load_dotenv(root / "cinema-ai" / ".env")
    os.environ.setdefault("MEMORY_MODEL_PATH", str(root / "data" / "models" / "bge-small-zh-v1.5"))
    if args.service == "chroma":
        subprocess.run(
            [
                str(Path(sys.executable).with_name("chroma.exe")),
                "run",
                "--path",
                str(root / "data" / "chroma"),
                "--host",
                "127.0.0.1",
                "--port",
                os.getenv("CHROMA_PORT", "8030"),
            ],
            check=True,
        )
    else:
        from app.memory_worker import run

        asyncio.run(run())


if __name__ == "__main__":
    main()
