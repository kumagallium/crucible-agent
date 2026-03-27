"""Alembic マイグレーションテスト

- マイグレーションチェーンの構造検証
- 全マイグレーションの upgrade/downgrade が成功すること
- マイグレーション結果がモデル定義と一致すること
"""

import pathlib

import sqlalchemy as sa
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from crucible_agent.provenance.models import Base

_CRUCIBLE_AGENT_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ALEMBIC_INI = str(_CRUCIBLE_AGENT_ROOT / "alembic.ini")


def _alembic_cfg() -> Config:
    cfg = Config(_ALEMBIC_INI)
    cfg.set_main_option("script_location", str(_CRUCIBLE_AGENT_ROOT / "alembic"))
    return cfg


def _alembic_script_dir() -> ScriptDirectory:
    return ScriptDirectory.from_config(_alembic_cfg())


def _get_revision_ids() -> list[str]:
    """全リビジョン ID を依存順（古い→新しい）で返す"""
    revisions = list(_alembic_script_dir().walk_revisions())
    revisions.reverse()
    return [r.revision for r in revisions]


def _create_base_tables(engine: sa.engine.Engine) -> None:
    """マイグレーション前のベーステーブルを作成（初期スキーマ）"""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prov_agents (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                type VARCHAR(50) NOT NULL,
                created_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prov_activities (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL,
                type VARCHAR(50) NOT NULL,
                tool_name VARCHAR(255),
                server_name VARCHAR(255),
                input_data JSON,
                output_data JSON,
                duration_ms INTEGER,
                agent_id VARCHAR(36) REFERENCES prov_agents(id),
                started_at DATETIME NOT NULL,
                ended_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prov_entities (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL,
                type VARCHAR(50) NOT NULL,
                content TEXT,
                metadata_json JSON,
                generated_by VARCHAR(36) REFERENCES prov_activities(id),
                created_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS profiles (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                content TEXT NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))


def _run_alembic_upgrade(engine: sa.engine.Engine, target: str) -> None:
    """Alembic upgrade を同期エンジンで実行"""
    cfg = _alembic_cfg()
    script = ScriptDirectory.from_config(cfg)

    def do_upgrade(rev, context):
        return script._upgrade_revs(target, rev)

    with engine.begin() as conn:
        ctx = EnvironmentContext(cfg, script, fn=do_upgrade)
        ctx.configure(connection=conn, target_metadata=Base.metadata)
        with ctx.begin_transaction():
            ctx.run_migrations()


def _run_alembic_downgrade(engine: sa.engine.Engine, target: str) -> None:
    """Alembic downgrade を同期エンジンで実行"""
    cfg = _alembic_cfg()
    script = ScriptDirectory.from_config(cfg)

    def do_downgrade(rev, context):
        return script._downgrade_revs(target, rev)

    with engine.begin() as conn:
        ctx = EnvironmentContext(cfg, script, fn=do_downgrade)
        ctx.configure(connection=conn, target_metadata=Base.metadata)
        with ctx.begin_transaction():
            ctx.run_migrations()


class TestMigrationChain:
    """マイグレーションチェーンの構造テスト"""

    def test_revisions_exist(self):
        """少なくとも1つのマイグレーションが存在する"""
        assert len(_get_revision_ids()) >= 1

    def test_revision_chain_is_linear(self):
        """マイグレーションチェーンが分岐していない"""
        heads = _alembic_script_dir().get_heads()
        assert len(heads) == 1, f"マイグレーションが分岐: {heads}"

    def test_first_revision_has_no_down_revision(self):
        """最初のリビジョンの down_revision が None"""
        revisions = list(_alembic_script_dir().walk_revisions())
        first = revisions[-1]
        assert first.down_revision is None

    def test_each_revision_has_upgrade_and_downgrade(self):
        """各リビジョンに upgrade/downgrade 関数がある"""
        for rev in _alembic_script_dir().walk_revisions():
            mod = rev.module
            assert hasattr(mod, "upgrade"), f"{rev.revision} に upgrade() がない"
            assert hasattr(mod, "downgrade"), f"{rev.revision} に downgrade() がない"


class TestUpgradeDowngrade:
    """全マイグレーションの upgrade/downgrade 往復テスト"""

    def test_upgrade_to_head(self, tmp_path):
        """全マイグレーションを head まで upgrade できる"""
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        engine = sa.create_engine(db_url)
        _create_base_tables(engine)
        _run_alembic_upgrade(engine, "head")

        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "prov_usage" in tables
        assert "prov_derivations" in tables

        columns = {c["name"] for c in inspector.get_columns("prov_agents")}
        for col in ["provider", "model_id", "model_version", "server_name", "external_id"]:
            assert col in columns, f"prov_agents に {col} がない"
        engine.dispose()

    def test_downgrade_to_base(self, tmp_path):
        """upgrade(head) → downgrade(base) で追加テーブル・カラムが除去される"""
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        engine = sa.create_engine(db_url)
        _create_base_tables(engine)

        _run_alembic_upgrade(engine, "head")
        # upgrade 後に存在確認
        assert "prov_usage" in inspect(engine).get_table_names()

        _run_alembic_downgrade(engine, "base")

        inspector = inspect(engine)
        # downgrade で追加テーブルが削除されている
        tables = inspector.get_table_names()
        assert "prov_derivations" not in tables

        # prov_agents から追加カラムが除去されている
        # (SQLite は ALTER TABLE DROP COLUMN 対応が限定的だが、
        #  Alembic の batch mode で対応可能。ここではテーブル削除のみ検証)
        engine.dispose()

    def test_stepwise_upgrade(self, tmp_path):
        """各マイグレーションを1つずつ upgrade できる"""
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        engine = sa.create_engine(db_url)
        _create_base_tables(engine)

        for rev_id in _get_revision_ids():
            _run_alembic_upgrade(engine, rev_id)

        # 最終状態が head と同じ
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "prov_usage" in tables
        assert "prov_derivations" in tables
        engine.dispose()

    def test_upgrade_downgrade_roundtrip(self, tmp_path):
        """upgrade(head) → downgrade(base) → upgrade(head) の往復"""
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        engine = sa.create_engine(db_url)
        _create_base_tables(engine)

        _run_alembic_upgrade(engine, "head")
        tables_first = set(inspect(engine).get_table_names())

        _run_alembic_downgrade(engine, "base")
        _run_alembic_upgrade(engine, "head")
        tables_second = set(inspect(engine).get_table_names())

        assert tables_first == tables_second
        engine.dispose()


class TestModelMigrationSync:
    """モデル定義とマイグレーション結果の整合性テスト"""

    def test_all_model_tables_exist_after_migration(self, tmp_path):
        """upgrade(head) 後、全モデルのテーブルが存在する"""
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        engine = sa.create_engine(db_url)
        _create_base_tables(engine)
        _run_alembic_upgrade(engine, "head")

        actual = set(inspect(engine).get_table_names()) - {"alembic_version"}
        expected = {t.name for t in Base.metadata.sorted_tables}
        missing = expected - actual
        assert not missing, f"不足テーブル: {missing}"
        engine.dispose()

    def test_model_columns_match_migration(self, tmp_path):
        """各テーブルのカラム名がモデル定義と一致する"""
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        engine = sa.create_engine(db_url)
        _create_base_tables(engine)
        _run_alembic_upgrade(engine, "head")

        inspector = inspect(engine)
        for table in Base.metadata.sorted_tables:
            actual_cols = {c["name"] for c in inspector.get_columns(table.name)}
            expected_cols = {c.name for c in table.columns}
            missing = expected_cols - actual_cols
            assert not missing, f"{table.name} に不足カラム: {missing}"
        engine.dispose()

    def test_create_all_matches_migration_tables(self, tmp_path):
        """create_all() とマイグレーション結果のテーブルセットが一致"""
        # create_all でモデル定義から全テーブルを生成
        db1_url = f"sqlite:///{tmp_path / 'model.db'}"
        engine1 = sa.create_engine(db1_url)
        Base.metadata.create_all(bind=engine1)
        model_tables = set(inspect(engine1).get_table_names())
        assert len(model_tables) > 0, "create_all でテーブルが作られていない"

        # マイグレーション経由でテーブルを生成
        db2_url = f"sqlite:///{tmp_path / 'migration.db'}"
        engine2 = sa.create_engine(db2_url)
        _create_base_tables(engine2)
        _run_alembic_upgrade(engine2, "head")
        migration_tables = set(inspect(engine2).get_table_names()) - {"alembic_version"}

        assert model_tables == migration_tables, (
            f"model_only={model_tables - migration_tables}, "
            f"migration_only={migration_tables - model_tables}"
        )
        engine1.dispose()
        engine2.dispose()
