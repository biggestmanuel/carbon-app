"""email verification and per-device sessions

Revision ID: d37d942354df
Revises: f8690e605c7f
Create Date: 2026-10-03 12:03:44.509735

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d37d942354df"
down_revision = "f8690e605c7f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_session",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("user_agent", sa.String(length=200), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("user_session", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_session_user_id"), ["user_id"], unique=False)

    # email_verified is NOT NULL with no server default, so it cannot be added
    # straight to a table that already has rows. Add it nullable, backfill to
    # false, then tighten.
    #
    # Existing accounts are deliberately left unverified: nobody has proved
    # those addresses yet, and treating them as verified would preserve exactly
    # the hole this column exists to close. They must request a confirmation.
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email_verified", sa.Boolean(), nullable=True))
        batch_op.add_column(
            sa.Column("email_verification_token_hash", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("email_verification_sent_at", sa.DateTime(timezone=True), nullable=True)
        )

    # "user" is a reserved word in Postgres, so the identifier must be quoted.
    #
    # false, not 0: SQLite silently coerces 0 to FALSE, Postgres rejects an
    # integer for a boolean column outright. The keyword works on both.
    op.execute('UPDATE "user" SET email_verified = false WHERE email_verified IS NULL')

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.alter_column(
            "email_verified",
            existing_type=sa.Boolean(),
            nullable=False,
        )


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("email_verification_sent_at")
        batch_op.drop_column("email_verification_token_hash")
        batch_op.drop_column("email_verified")

    with op.batch_alter_table("user_session", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_session_user_id"))

    op.drop_table("user_session")