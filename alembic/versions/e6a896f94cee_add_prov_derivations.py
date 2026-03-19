"""add_prov_derivations

Revision ID: e6a896f94cee
Revises: 38c468927df5
Create Date: 2026-03-19 13:27:59.349399

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6a896f94cee'
down_revision: Union[str, Sequence[str], None] = '38c468927df5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # prov_derivations: prov:wasDerivedFrom / wasInfluencedBy 関係テーブルを新規作成
    op.create_table(
        'prov_derivations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'derived_entity_id',
            sa.String(36),
            sa.ForeignKey('prov_entities.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'source_entity_id',
            sa.String(36),
            sa.ForeignKey('prov_entities.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('relation_type', sa.String(50), nullable=False, server_default='wasDerivedFrom'),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index('idx_prov_derivations_derived', 'prov_derivations', ['derived_entity_id'])
    op.create_index('idx_prov_derivations_source', 'prov_derivations', ['source_entity_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_prov_derivations_source', table_name='prov_derivations')
    op.drop_index('idx_prov_derivations_derived', table_name='prov_derivations')
    op.drop_table('prov_derivations')
