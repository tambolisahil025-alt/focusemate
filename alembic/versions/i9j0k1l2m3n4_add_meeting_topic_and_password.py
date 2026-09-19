"""Add meeting topic and password hash.

Revision ID: i9j0k1l2m3n4
Revises: h8c9d0e1f2a3
"""
from alembic import op
import sqlalchemy as sa

revision = "i9j0k1l2m3n4"
down_revision = "h8c9d0e1f2a3"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("meetings")}
    if "topic" not in columns:
        op.add_column("meetings", sa.Column("topic", sa.String(length=120), nullable=True))
    if "password_hash" not in columns:
        op.add_column("meetings", sa.Column("password_hash", sa.String(length=255), nullable=True))

def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("meetings")}
    if "password_hash" in columns:
        op.drop_column("meetings", "password_hash")
    if "topic" in columns:
        op.drop_column("meetings", "topic")
