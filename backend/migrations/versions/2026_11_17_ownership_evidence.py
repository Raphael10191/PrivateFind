"""Track verification outcomes and previous owner-facing disclosures."""

import sqlalchemy as sa
from alembic import op

revision = "a9c4305b5d16"
down_revision = "c3c3ff57c7f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ownership_evidence", sa.Column("attempt_no", sa.SmallInteger()))
    op.add_column("claim", sa.Column("verification_state", sa.String(30)))
    op.add_column("item_attribute", sa.Column("observation_state", sa.String(12)))
    op.add_column("claim", sa.Column("next_action", sa.String(30)))
    op.add_column("lost_report", sa.Column("material", sa.String(50)))
    op.add_column("lost_report", sa.Column("ranked_at", sa.DateTime()))
    with op.batch_alter_table("lost_report") as batch:
        batch.alter_column("lost_from", existing_type=sa.DateTime(), nullable=True)
        batch.alter_column("lost_to", existing_type=sa.DateTime(), nullable=True)
    op.add_column(
        "found_item",
        sa.Column("owner_details_exposed", sa.Boolean(), server_default="0", nullable=False),
    )
    op.execute(
        sa.text(
            "UPDATE found_item SET owner_details_exposed = 1 "
            "WHERE public_summary IS NOT NULL AND EXISTS ("
            "SELECT 1 FROM match_candidate WHERE match_candidate.item_id = found_item.item_id)"
        )
    )


def downgrade() -> None:
    op.drop_column("item_attribute", "observation_state")
    op.drop_column("found_item", "owner_details_exposed")
    op.execute(
        sa.text(
            "UPDATE lost_report SET lost_from = COALESCE(lost_from, created_at), "
            "lost_to = COALESCE(lost_to, lost_from, created_at)"
        )
    )
    with op.batch_alter_table("lost_report") as batch:
        batch.alter_column("lost_from", existing_type=sa.DateTime(), nullable=False)
        batch.alter_column("lost_to", existing_type=sa.DateTime(), nullable=False)
    op.drop_column("lost_report", "ranked_at")
    op.drop_column("lost_report", "material")
    op.drop_column("claim", "next_action")
    op.drop_column("claim", "verification_state")
    op.drop_column("ownership_evidence", "attempt_no")
