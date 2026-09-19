"""Ensure meeting tables exist on deployments where the original migration was stamped incompletely."""
from alembic import op
import sqlalchemy as sa

revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "meetings" not in tables:
        op.create_table(
            "meetings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("room_id", sa.Integer(), sa.ForeignKey("rooms.id"), nullable=False),
            sa.Column("host_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("meeting_code", sa.String(), nullable=True),
            sa.Column("topic", sa.String(120), nullable=True),
            sa.Column("password_hash", sa.String(255), nullable=True),
            sa.Column("status", sa.String(), nullable=True, server_default="lobby"),
            sa.Column("auto_accept", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        )
        tables.add("meetings")

    columns = {c["name"] for c in inspector.get_columns("meetings")}
    if "meeting_code" not in columns:
        op.add_column("meetings", sa.Column("meeting_code", sa.String(), nullable=True))
    if "topic" not in columns:
        op.add_column("meetings", sa.Column("topic", sa.String(120), nullable=True))
    if "password_hash" not in columns:
        op.add_column("meetings", sa.Column("password_hash", sa.String(255), nullable=True))
    if "status" not in columns:
        op.add_column("meetings", sa.Column("status", sa.String(), nullable=True, server_default="lobby"))
    if "auto_accept" not in columns:
        op.add_column("meetings", sa.Column("auto_accept", sa.Boolean(), nullable=True, server_default=sa.text("false")))
    if "created_at" not in columns:
        op.add_column("meetings", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True))
    if "ended_at" not in columns:
        op.add_column("meetings", sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "meeting_participants" not in tables:
        op.create_table(
            "meeting_participants",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("meeting_id", sa.Integer(), sa.ForeignKey("meetings.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("role", sa.String(), nullable=True, server_default="participant"),
            sa.Column("status", sa.String(), nullable=True, server_default="pending"),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("banned", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        )

    if "meeting_invitations" not in tables:
        op.create_table(
            "meeting_invitations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("meeting_id", sa.Integer(), sa.ForeignKey("meetings.id"), nullable=False),
            sa.Column("inviter_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used", sa.Boolean(), nullable=True, server_default=sa.text("false")),
            sa.Column("single_use", sa.Boolean(), nullable=True, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        )

    inspector = sa.inspect(bind)
    meeting_indexes = {i["name"] for i in inspector.get_indexes("meetings")}
    if "ix_meetings_meeting_code" not in meeting_indexes:
        op.create_index("ix_meetings_meeting_code", "meetings", ["meeting_code"], unique=True)


def downgrade():
    # Intentionally non-destructive: this repair migration must never delete live meeting data.
    pass
