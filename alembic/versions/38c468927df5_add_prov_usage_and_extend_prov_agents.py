"""add_prov_usage_and_extend_prov_agents

Revision ID: 38c468927df5
Revises:
Create Date: 2026-03-19 13:16:31.228846

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '38c468927df5'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # prov_agents: LLM/MCP Tool/User 識別情報カラムを追加
    op.add_column('prov_agents', sa.Column('provider', sa.String(50), nullable=True))
    op.add_column('prov_agents', sa.Column('model_id', sa.String(100), nullable=True))
    op.add_column('prov_agents', sa.Column('model_version', sa.String(50), nullable=True))
    op.add_column('prov_agents', sa.Column('server_name', sa.String(100), nullable=True))
    op.add_column('prov_agents', sa.Column('external_id', sa.String(255), nullable=True))

    # prov_usage: prov:used 関係テーブルを新規作成
    op.create_table(
        'prov_usage',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('activity_id', sa.String(36), sa.ForeignKey('prov_activities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('entity_id', sa.String(36), sa.ForeignKey('prov_entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('idx_prov_usage_activity', 'prov_usage', ['activity_id'])
    op.create_index('idx_prov_usage_entity', 'prov_usage', ['entity_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_prov_usage_entity', table_name='prov_usage')
    op.drop_index('idx_prov_usage_activity', table_name='prov_usage')
    op.drop_table('prov_usage')

    op.drop_column('prov_agents', 'external_id')
    op.drop_column('prov_agents', 'server_name')
    op.drop_column('prov_agents', 'model_version')
    op.drop_column('prov_agents', 'model_id')
    op.drop_column('prov_agents', 'provider')
