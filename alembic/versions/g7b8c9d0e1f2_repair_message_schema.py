"""Ensure message fields and indexes exist on deployed databases.

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-15
"""
from typing import Sequence, Union

from alembic import op


revision: str = "g7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS "
        "is_edited BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_room_created_at "
        "ON messages (room_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_room_members_room_user "
        "ON room_members (room_id, user_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_room_members_room_user")
    op.execute("DROP INDEX IF EXISTS ix_messages_room_created_at")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS is_edited")
