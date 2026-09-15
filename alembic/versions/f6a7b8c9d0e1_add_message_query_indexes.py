"""Add indexes for room message history queries.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-15
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_messages_room_created_at",
        "messages",
        ["room_id", "created_at"],
    )
    op.create_index(
        "ix_room_members_room_user",
        "room_members",
        ["room_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_room_members_room_user", table_name="room_members")
    op.drop_index("ix_messages_room_created_at", table_name="messages")
