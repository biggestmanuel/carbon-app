"""two-factor authentication

Revision ID: dfe8623682a4
Revises: 830e130da68c
Create Date: 2026-10-04 23:25:10.301767

Every existing row has two-factor off, so the new flag gets a server default and
then drops it again. Without the default, Postgres rejects the ALTER on a table
that already has rows -- NOT NULL with no default is only satisfiable by a rewrite
of every row, and it fails outright on a large table. The default is removed
afterwards so the model's own default is the only thing that sets the column.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "dfe8623682a4"
down_revision = "830e130da68c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recovery_code",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        # Only hashes are stored, so a database leak yields no working codes.
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("recovery_code", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_recovery_code_user_id"), ["user_id"], unique=False)

    with op.batch_alter_table("user", schema=None) as batch_op:
        # Encrypted at rest, not hashed: verification needs the original bytes.
        batch_op.add_column(sa.Column("totp_secret", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        # The time step of the last accepted code, for replay protection.
        batch_op.add_column(sa.Column("totp_last_counter", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("totp_changed_at", sa.DateTime(timezone=True), nullable=True))

    # Leaves no server default behind, so the column behaves like every other
    # one in this schema: set by the model, never by the database.
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.alter_column("totp_enabled", server_default=None)


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("totp_changed_at")
        batch_op.drop_column("totp_last_counter")
        batch_op.drop_column("totp_enabled")
        batch_op.drop_column("totp_secret")

    with op.batch_alter_table("recovery_code", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_recovery_code_user_id"))

    op.drop_table("recovery_code")