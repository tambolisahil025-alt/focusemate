"""Ensure meeting topic and password columns exist."""
from alembic import op
import sqlalchemy as sa

revision = "i9j0k1l2m3n4"
down_revision = "h8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    # Older production databases should already have meetings from the original migration.
    # Do not silently recreate the entire application schema here.
    if "meetings" not in tables:
        return
    columns = {c["name"] for c in inspector.get_columns("meetings")}
    if "topic" not in columns:
        op.add_column("meetings", sa.Column("topic", sa.String(length=120), nullable=True))
    if "password_hash" not in columns:
        op.add_column("meetings", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "meetings" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("meetings")}
    if "password_hash" in columns:
        op.drop_column("meetings", "password_hash")
    if "topic" in columns:
        op.drop_column("meetings", "topic")
