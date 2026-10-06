"""Connection to the MySQL database.

The connection data comes from the .env file in the project folder, e.g.
DATABASE_URL=mysql+pymysql://pf:pf_pass@localhost:3306/privatefind
The .env file is not in Git, so every team member has their own.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is missing. Copy .env.example to .env and enter your database data."
    )

# pool_pre_ping checks the connection before use, so a restarted MySQL does not crash the app
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# A session is one "conversation" with the database (read, write, commit)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """Gives one session per request (for FastAPI: db: Session = Depends(get_db))."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
