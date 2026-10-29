"""procrastinate job-queue schema

Tables, enum types and SQL functions used by the worker, the scheduler and every `defer()` made by the API.

Revision ID: 0002
Revises: 0001

This schema used to be applied by a separate `procrastinate ... schema --apply` step in the Makefile, scripts/dev.sh
and the Docker entrypoint. That CLI runs as a console script, so the current directory is not on sys.path and the
import of `app.workers.app` fails ("No module named 'app'"); the step was wrapped in `|| true` and therefore failed
silently on every machine, leaving the database without the queue. Applying the schema here makes
`alembic upgrade head` the single, idempotent source of truth. Databases that already carry the schema (applied by
hand) are left untouched.
"""
from __future__ import annotations

from alembic import op
from procrastinate.schema import SchemaManager

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PRESENT_SQL = "SELECT 1 FROM information_schema.tables WHERE table_name = 'procrastinate_jobs' LIMIT 1"

DROP_SQL = """
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'procrastinate\\_%' LOOP
    EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename);
  END LOOP;
  FOR r IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'public' AND p.proname LIKE 'procrastinate\\_%' LOOP
    EXECUTE format('DROP FUNCTION IF EXISTS %s CASCADE', r.sig);
  END LOOP;
  FOR r IN SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
           LEFT JOIN pg_class c ON c.oid = t.typrelid
           WHERE n.nspname = 'public' AND t.typname LIKE 'procrastinate\\_%'
             AND (t.typtype = 'e' OR (t.typtype = 'c' AND c.relkind = 'c')) LOOP   -- enums + standalone composites
    EXECUTE format('DROP TYPE IF EXISTS public.%I CASCADE', r.typname);
  END LOOP;
END $$;
"""


def _run(conn, sql: str) -> None:
    # exec_driver_sql() hands psycopg an (empty) parameter set, so literal `%` (plpgsql RAISE/format) must be doubled.
    conn.exec_driver_sql(sql.replace("%", "%%"))


def upgrade() -> None:
    conn = op.get_bind()
    if conn.exec_driver_sql(PRESENT_SQL).scalar():
        return
    _run(conn, SchemaManager.get_schema())


def downgrade() -> None:
    _run(op.get_bind(), DROP_SQL)
