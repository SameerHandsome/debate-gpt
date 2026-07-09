"""init: debates + debate_rounds

Revision ID: 0001_init
Revises:
Create Date: 2026-07-04

Per PRD §6.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # gen_random_uuid() lives in pgcrypto; idempotent.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    op.execute(
        """
        CREATE TABLE debates (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            topic        TEXT NOT NULL,
            position_pro TEXT NOT NULL,
            position_con TEXT NOT NULL,
            status       TEXT DEFAULT 'pending',  -- pending|running|complete|error
            winner       TEXT,                    -- "pro"|"con"|"tie"|NULL
            created_at   TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        );
        """
    )

    op.execute(
        """
        CREATE TABLE debate_rounds (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            debate_id      UUID REFERENCES debates(id) ON DELETE CASCADE,
            round_number   INT NOT NULL,
            pro_argument   TEXT NOT NULL,
            con_argument   TEXT NOT NULL,
            judge_scores   JSONB NOT NULL,
            round_winner   TEXT,
            created_at     TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )
    op.create_index(
        "ix_debate_rounds_debate_id", "debate_rounds", ["debate_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_debate_rounds_debate_id", table_name="debate_rounds")
    op.execute("DROP TABLE IF EXISTS debate_rounds;")
    op.execute("DROP TABLE IF EXISTS debates;")
