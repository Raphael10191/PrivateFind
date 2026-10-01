from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
LOGS_DIR = Path(__file__).parent / "logs"


class LockerValidationRequest(BaseModel):
    device_id: str
    code: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/locker/validate")
def validate_locker(request: LockerValidationRequest) -> dict[str, bool | int | str | None]:
    authorized = request.code == "1234"
    timestamp = datetime.now()

    LOGS_DIR.mkdir(exist_ok=True)
    log_file = LOGS_DIR / f"attempt_{timestamp:%Y-%m-%d_%H%M%S}.txt"
    suffix = 1
    while log_file.exists():
        log_file = LOGS_DIR / f"attempt_{timestamp:%Y-%m-%d_%H%M%S}_{suffix}.txt"
        suffix += 1

    log_file.write_text(
        f"timestamp: {timestamp:%Y-%m-%d %H:%M:%S}\n"
        f"device_id: {request.device_id}\n"
        f"code: {request.code}\n"
        f"authorized: {str(authorized).lower()}\n",
        encoding="utf-8",
    )

    if authorized:
        return {"authorized": True, "compartment": 1, "action": "pickup"}

    return {"authorized": False, "compartment": None, "action": None}
