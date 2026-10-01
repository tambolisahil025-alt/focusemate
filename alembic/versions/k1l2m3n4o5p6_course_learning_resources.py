"""Add course preparation resources and learning activity tracking."""
from alembic import op
import sqlalchemy as sa


revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "course_resources" not in tables:
        op.create_table(
            "course_resources",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("added_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("topic", sa.String(length=200), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("resource_type", sa.String(length=32), nullable=False, server_default="study_link"),
            sa.Column("thumbnail_url", sa.Text(), nullable=True),
            sa.Column("source", sa.String(length=200), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        op.create_index("ix_course_resources_course_id", "course_resources", ["course_id"])
        op.create_index("ix_course_resources_added_by_id", "course_resources", ["added_by_id"])
        op.create_index("ix_course_resources_topic", "course_resources", ["topic"])

    if "learning_activities" not in tables:
        op.create_table(
            "learning_activities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("activity_type", sa.String(length=40), nullable=False),
            sa.Column("topic", sa.String(length=200), nullable=True),
            sa.Column("xp_earned", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("event_key", sa.String(length=200), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.UniqueConstraint("event_key", name="uq_learning_activity_event_key"),
        )
        op.create_index("ix_learning_activities_user_id", "learning_activities", ["user_id"])
        op.create_index("ix_learning_activities_activity_type", "learning_activities", ["activity_type"])
        op.create_index("ix_learning_activities_topic", "learning_activities", ["topic"])
        op.create_index("ix_learning_activities_created_at", "learning_activities", ["created_at"])

    inspector = sa.inspect(bind)
    quiz_columns = {column["name"] for column in inspector.get_columns("quiz_attempts")}
    if "course_id" not in quiz_columns:
        op.add_column("quiz_attempts", sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=True))
    if "source" not in quiz_columns:
        op.add_column("quiz_attempts", sa.Column("source", sa.String(length=32), nullable=False, server_default="topic"))
    if "resource_ids" not in quiz_columns:
        op.add_column("quiz_attempts", sa.Column("resource_ids", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "quiz_attempts" in tables:
        columns = {column["name"] for column in inspector.get_columns("quiz_attempts")}
        for column in ("resource_ids", "source", "course_id"):
            if column in columns:
                op.drop_column("quiz_attempts", column)

    if "learning_activities" in tables:
        op.drop_table("learning_activities")
    if "course_resources" in tables:
        op.drop_table("course_resources")
