"""Add quiz attempts for learning progress and XP."""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("difficulty", sa.String(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("correct_answers", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("percentage", sa.Integer(), nullable=False),
        sa.Column("xp_earned", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_quiz_attempts_id", "quiz_attempts", ["id"])
    op.create_index("ix_quiz_attempts_user_id", "quiz_attempts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_quiz_attempts_user_id", table_name="quiz_attempts")
    op.drop_index("ix_quiz_attempts_id", table_name="quiz_attempts")
    op.drop_table("quiz_attempts")