"""Container startup: migrate, seed once, then run the API."""

import os
import subprocess
import sys

import uvicorn


def main() -> None:
    print("Applying database migrations...", flush=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    print("Preparing the demo admin and locker...", flush=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.seed",
            "--admin-email",
            os.environ.get("ADMIN_EMAIL", "admin@example.com"),
            "--admin-password",
            os.environ.get("ADMIN_PASSWORD", "changeme123"),
        ],
        check=True,
    )
    print("Starting PrivateFind. Open /docs for the API interface.", flush=True)
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
