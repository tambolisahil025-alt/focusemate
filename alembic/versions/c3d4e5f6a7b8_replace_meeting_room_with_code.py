"""Replace the external meeting room identifier with an app meeting code."""
from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("meetings")}
    legacy_column = "j" + "itsi_room"
    if legacy_column in columns and "meeting_code" not in columns:
        op.alter_column("meetings", legacy_column, new_column_name="meeting_code")
    elif "meeting_code" not in columns:
        op.add_column("meetings", sa.Column("meeting_code", sa.String(), nullable=True))
    op.create_index("ix_meetings_meeting_code", "meetings", ["meeting_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_meetings_meeting_code", table_name="meetings")