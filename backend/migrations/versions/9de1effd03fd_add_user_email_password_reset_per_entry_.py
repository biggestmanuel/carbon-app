"""add user email, password reset, per-entry factor snapshot

Revision ID: 9de1effd03fd
Revises: 2d2690cb6c1a
Create Date: 2026-10-03 09:09:00.852450

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9de1effd03fd"
down_revision = "2d2690cb6c1a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("footprint", schema=None) as batch_op:
        batch_op.add_column(sa.Column("factors_applied", sa.JSON(), nullable=True))
        batch_op.alter_column(
            "region",
            existing_type=sa.VARCHAR(length=16),
            type_=sa.String(length=32),
            existing_nullable=False,
        )

    # updated_at is NOT NULL, so it cannot simply be added to a table that
    # already has rows. Add it nullable, backfill from created_at, then
    # tighten. Adding it NOT NULL straight away fails on a populated database.
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(length=254), nullable=True))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("password_reset_token_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("password_reset_sent_at", sa.DateTime(timezone=True), nullable=True))

    # "user" is a reserved word in Postgres, so the identifier must be quoted.
    # SQLite accepts the same double-quoted form.
    op.execute('UPDATE "user" SET updated_at = created_at WHERE updated_at IS NULL')

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        batch_op.create_index(batch_op.f("ix_user_email"), ["email"], unique=True)


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_email"))
        batch_op.drop_column("password_reset_sent_at")
        batch_op.drop_column("password_reset_token_hash")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("email")

    with op.batch_alter_table("footprint", schema=None) as batch_op:
        batch_op.alter_column(
            "region",
            existing_type=sa.String(length=32),
            type_=sa.VARCHAR(length=16),
            existing_nullable=False,
        )
        batch_op.drop_column("factors_applied")