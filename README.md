# PrivateFind

AI-assisted campus lost-and-found system with private ownership verification and smart-locker handover.
Sejong University · Software Engineering · Team **Roaster**.

| Member | Role |
|---|---|
| Zohidjon Mahmudjonov | Team Leader · AI & Backend |
| Umarov Muslimbek | UI & Frontend |
| Gerthofer Simon | Database & Matching |
| Falk Raphael | IoT & Locker |

## Documentation
- [Project proposal](docs/PrivateFind_Project_Proposal_v2.pdf)
- [Task checklist](docs/TASKS.md)
- [System architecture](docs/design/architecture.md)
- [Frontend API integration guide](docs/api/frontend-integration.md)
- [OpenAPI specification](docs/api/openapi.json) · [Postman collection](docs/api/postman-collection.json)

## Start with Docker

Start Docker Desktop, then run from this repository's root:

```bash
docker compose up --build
```

This starts MySQL and the backend, applies migrations, and creates an admin account
and the one-compartment demo locker. Open [the API interface](http://localhost:8000/docs).
No frontend or AI API key is needed: mock AI is enabled by default.

- Demo admin: `admin@example.com` / `changeme123`.
- Locker: `L1`, device: `locker_01`, compartment: `1`.
- The device key appears in backend logs on the first startup; save it for the ESP32.
- Database records and uploaded photos persist in Docker volumes.

Stop with `docker compose down`. For more commands and configuration, see
the [backend setup guide](backend/README.md).

## Stack
Python 3.13 · FastAPI (async) · SQLAlchemy 2 + Alembic · MySQL 8 · Jinja2 + Bootstrap 5 · Claude API · ESP32 (Arduino C++)
