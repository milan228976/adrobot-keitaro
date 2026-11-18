from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stream_drafts",
        sa.Column("stream_id", sa.Integer(), autoincrement=False, primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("baseline", sa.JSON(), nullable=False),
        sa.Column("pending", sa.JSON(), nullable=True),
        sa.Column("pins", sa.JSON(), nullable=False),
        sa.Column("pending_pins", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("stream_drafts")
