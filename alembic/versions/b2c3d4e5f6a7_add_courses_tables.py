"""Add courses tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f
"""
from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_courses_id", "courses", ["id"], unique=False)
    op.create_index("ix_courses_code", "courses", ["code"], unique=False)
    op.create_table(
        "course_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "user_id", name="uq_course_member"),
    )
    op.create_index("ix_course_members_id", "course_members", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_course_members_id", table_name="course_members")
    op.drop_table("course_members")
    op.drop_index("ix_courses_code", table_name="courses")
    op.drop_index("ix_courses_id", table_name="courses")
    op.drop_table("courses")