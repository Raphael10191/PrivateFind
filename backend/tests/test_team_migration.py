"""Upgrade a populated Simon database; validate relationships and ORM compatibility."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def test_populated_team_database_upgrade(tmp_path):
    database = tmp_path / "team.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database.as_posix()}"}
    backend = Path(__file__).resolve().parents[1]

    def alembic(*args):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    alembic("upgrade", "c37e42452449")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO user
            (user_id, username, email, password_hash, role, created_at)
            VALUES (7, 'simon', 'simon@example.com', 'hash', 'owner', '2026-11-01')""")
        )
        connection.execute(
            text("""INSERT INTO locker
            (locker_id, device_id, device_key_hash, location)
            VALUES (3, 'locker_01', 'existing-key-hash', 'Library')""")
        )
        connection.execute(
            text("""INSERT INTO compartment
            (compartment_id, locker_id, number, state) VALUES (5, 3, 1, 'occupied')""")
        )
        connection.execute(
            text("""INSERT INTO found_item
            (item_id, compartment_id, category, location, finder_note, status, ai_status,
             found_at, created_at)
            VALUES (11, 5, 'wallet', 'Library', 'keep this note', 'open', 'done',
                    '2026-11-01', '2026-11-01')""")
        )
        connection.execute(
            text("""INSERT INTO lost_report
            (report_id, user_id, category, location, lost_from, lost_to, status, created_at)
            VALUES (13, 7, 'wallet', 'Library', '2026-11-01', '2026-11-02',
                    'open', '2026-11-01')""")
        )
        connection.execute(
            text("""INSERT INTO match_candidate
            (match_id, report_id, item_id, category_score, location_score, time_score,
             attribute_score, semantic_score, total_score, created_at)
            VALUES (17, 13, 11, 100, 100, 100, 100, 100, 100, '2026-11-01')""")
        )
        connection.execute(
            text("""INSERT INTO claim
            (claim_id, match_id, user_id, status, attempt_no, created_at)
            VALUES (19, 17, 7, 'in_review', 1, '2026-11-01')""")
        )
    alembic("upgrade", "head")
    alembic("check")
    with engine.connect() as connection:
        assert len(inspect(connection).get_table_names()) == 14  # 13 + alembic_version
        assert (
            connection.execute(text("SELECT match_id FROM claim WHERE claim_id=19")).scalar() == 17
        )
        assert (
            connection.execute(text("SELECT locker_id FROM found_item WHERE item_id=11")).scalar()
            == 3
        )
        assert (
            connection.execute(text("SELECT finder_note FROM found_item WHERE item_id=11")).scalar()
            == "keep this note"
        )
        assert (
            connection.execute(
                text("SELECT device_key_hash FROM locker WHERE locker_id=3")
            ).scalar()
            == "existing-key-hash"
        )
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    # The additive revision can be reversed independently of Simon's baseline.
    alembic("downgrade", "c37e42452449")
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT match_id FROM claim WHERE claim_id=19")).scalar() == 17
        )
    engine.dispose()
