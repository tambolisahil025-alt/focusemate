"""Add approval-based course join requests."""
from alembic import op
import sqlalchemy as sa


revision = "l2m3n4o5p6q7"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "course_join_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_course_join_requests_course_id", "course_join_requests", ["course_id"])
    op.create_index("ix_course_join_requests_user_id", "course_join_requests", ["user_id"])


def downgrade():
    op.drop_index("ix_course_join_requests_user_id", table_name="course_join_requests")
    op.drop_index("ix_course_join_requests_course_id", table_name="course_join_requests")
    op.drop_table("course_join_requests")