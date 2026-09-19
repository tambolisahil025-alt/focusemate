"""Add server-side expiration timestamps to media messages.

Revision ID: h8c9d0e1f2a3
Revises: g7b8c9d0e1f2
"""
from alembic import op
import sqlalchemy as sa

revision = "h8c9d0e1f2a3"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("media_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("direct_messages", sa.Column("media_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_messages_media_expires_at", "messages", ["media_expires_at"], unique=False)
    op.create_index("ix_direct_messages_media_expires_at", "direct_messages", ["media_expires_at"], unique=False)


def downgrade():
    op.drop_index("ix_direct_messages_media_expires_at", table_name="direct_messages")
    op.drop_index("ix_messages_media_expires_at", table_name="messages")
    op.drop_column("direct_messages", "media_expires_at")
    op.drop_column("messages", "media_expires_at")
