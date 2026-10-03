"""add token version for session revocation

Revision ID: f8690e605c7f
Revises: 9de1effd03fd
Create Date: 2026-10-03 09:15:02.910320

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f8690e605c7f"
down_revision = "9de1effd03fd"
branch_labels = None
depends_on = None


def upgrade():
    # NOT NULL with no server default, so it cannot be added straight to a
    # populated table. Add it nullable, backfill to the model's default of 1,
    # then tighten.
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("token_version", sa.Integer(), nullable=True))

    # "user" is a reserved word in Postgres, so the identifier must be quoted.
    op.execute('UPDATE "user" SET token_version = 1 WHERE token_version IS NULL')

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.alter_column(
            "token_version",
            existing_type=sa.Integer(),
            nullable=False,
        )


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("token_version")