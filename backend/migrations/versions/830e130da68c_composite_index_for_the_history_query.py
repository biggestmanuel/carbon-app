"""composite index for the history query

Revision ID: 830e130da68c
Revises: d37d942354df
Create Date: 2026-10-04 20:48:20.415389

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "830e130da68c"
down_revision = "d37d942354df"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_footprint_user_created"
COLUMNS = ["user_id", "created_at", "id"]


def upgrade():
    # An index only, so this applies instantly on a populated table: no table is
    # rebuilt and no row is written. id is included because history() orders by
    # created_at DESC, id DESC, and without it the sort is not fully covered.
    with op.batch_alter_table("footprint", schema=None) as batch_op:
        batch_op.create_index(INDEX_NAME, COLUMNS, unique=False)


def downgrade():
    with op.batch_alter_table("footprint", schema=None) as batch_op:
        batch_op.drop_index(INDEX_NAME)
