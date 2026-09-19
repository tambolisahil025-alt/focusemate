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
    op.add_column("meetings", sa.Column("topic", sa.String(length=120), nullable=True))
    op.add_column("meetings", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column("meetings", "password_hash")
    op.drop_column("meetings", "topic")
