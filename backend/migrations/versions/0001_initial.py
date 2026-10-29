"""initial schema (doc 16 DDL) + updated_at triggers + RLS policies

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import op

from app.config import settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TRIGGER_FN = """
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    conn = op.get_bind()
    ddl = (Path(__file__).parent / "0001_initial.sql").read_text().replace("{DIMS}", str(settings.embedding_dims))
    conn.exec_driver_sql(ddl)
    conn.exec_driver_sql(TRIGGER_FN)
    rows = conn.exec_driver_sql(
        "SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='updated_at'").fetchall()
    for (t,) in rows:
        conn.exec_driver_sql(f'DROP TRIGGER IF EXISTS trg_{t}_updated_at ON "{t}"; '
                             f'CREATE TRIGGER trg_{t}_updated_at BEFORE UPDATE ON "{t}" FOR EACH ROW EXECUTE FUNCTION set_updated_at();')
    rows = conn.exec_driver_sql(
        "SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='workspace_id' "
        "AND table_name NOT IN ('events_outbox','audit_logs','oauth_states','prompt_templates')").fetchall()
    for (t,) in rows:
        conn.exec_driver_sql(
            f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY; DROP POLICY IF EXISTS ws_isolation ON "{t}"; '
            f'CREATE POLICY ws_isolation ON "{t}" USING (workspace_id = NULLIF(current_setting(\'app.workspace_id\', true), \'\')::uuid) '
            f'WITH CHECK (workspace_id = NULLIF(current_setting(\'app.workspace_id\', true), \'\')::uuid);')


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
