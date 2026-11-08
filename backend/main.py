"""PrivateFind backend. Start with:  uvicorn backend.main:app --reload --host 0.0.0.0"""
from fastapi import FastAPI

from backend.api import admin, deposits, device, lost_reports

app = FastAPI(title="PrivateFind")
app.include_router(deposits.router)
app.include_router(lost_reports.router)
app.include_router(device.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
