"""add_skills_table

Revision ID: a1b2c3d4e5f6
Revises: 25a080f739da
Create Date: 2026-05-16 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a1'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create the independent skills table
    op.create_table('skills',
        sa.Column('name', sa.String(length=100), nullable=False, index=True, comment='技能名称'),
        sa.Column('description', sa.Text(), nullable=True, comment='技能描述'),
        sa.Column('skill_type', sa.String(length=50), nullable=False, comment='技能类型: prompt/template/function'),
        sa.Column('content', sa.Text(), nullable=True, comment='技能内容'),
        sa.Column('config', sa.JSON(), nullable=False, comment='技能配置'),
        sa.Column('id', sa.String(length=36), nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='更新时间'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='软删除时间'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='skills_name_unique'),
        comment='独立技能表'
    )

    # 2. Migrate existing data from agent_skills to skills (deduplicate by name, pick first row per name)
    op.execute("""
        INSERT INTO skills (id, name, description, skill_type, content, config, created_at, updated_at, deleted_at)
        SELECT DISTINCT ON (name)
            gen_random_uuid()::text,
            name,
            description,
            skill_type,
            content,
            config,
            created_at,
            updated_at,
            deleted_at
        FROM agent_skills
        ORDER BY name, created_at ASC
    """)

    # 3. Add skill_id column to agent_skills (nullable temporarily)
    op.add_column('agent_skills', sa.Column('skill_id', sa.String(length=36), nullable=True, comment='关联的技能ID'))

    # 4. Populate skill_id based on skill name
    op.execute("""
        UPDATE agent_skills
        SET skill_id = skills.id
        FROM skills
        WHERE agent_skills.name = skills.name
    """)

    # 5. Make skill_id non-nullable and add foreign key
    op.alter_column('agent_skills', 'skill_id', nullable=False)
    op.create_foreign_key('agent_skills_skill_id_fk', 'agent_skills', 'skills', ['skill_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_agent_skills_skill_id'), 'agent_skills', ['skill_id'], unique=False)

    # 6. Drop old columns from agent_skills
    op.drop_constraint('agent_skills_unique', 'agent_skills', type_='unique')
    op.drop_column('agent_skills', 'name')
    op.drop_column('agent_skills', 'description')
    op.drop_column('agent_skills', 'skill_type')
    op.drop_column('agent_skills', 'content')
    op.drop_column('agent_skills', 'config')

    # 7. Add new unique constraint on (agent_id, skill_id)
    op.create_unique_constraint('agent_skill_unique', 'agent_skills', ['agent_id', 'skill_id'])


def downgrade() -> None:
    # 1. Restore old columns to agent_skills
    op.add_column('agent_skills', sa.Column('name', sa.String(length=100), nullable=True))
    op.add_column('agent_skills', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('agent_skills', sa.Column('skill_type', sa.String(length=50), nullable=True))
    op.add_column('agent_skills', sa.Column('content', sa.Text(), nullable=True))
    op.add_column('agent_skills', sa.Column('config', sa.JSON(), nullable=True))

    # 2. Copy data back from skills to agent_skills
    op.execute("""
        UPDATE agent_skills
        SET
            name = skills.name,
            description = skills.description,
            skill_type = skills.skill_type,
            content = skills.content,
            config = skills.config
        FROM skills
        WHERE agent_skills.skill_id = skills.id
    """)

    # 3. Make restored columns non-nullable where needed
    op.alter_column('agent_skills', 'name', nullable=False)
    op.alter_column('agent_skills', 'skill_type', nullable=False)

    # 4. Drop junction table columns and constraints
    op.drop_constraint('agent_skill_unique', 'agent_skills', type_='unique')
    op.drop_index(op.f('ix_agent_skills_skill_id'), table_name='agent_skills')
    op.drop_constraint('agent_skills_skill_id_fk', 'agent_skills', type_='foreignkey')
    op.drop_column('agent_skills', 'skill_id')

    # 5. Restore old unique constraint
    op.create_unique_constraint('agent_skills_unique', 'agent_skills', ['agent_id', 'name'])

    # 6. Drop skills table
    op.drop_table('skills')
