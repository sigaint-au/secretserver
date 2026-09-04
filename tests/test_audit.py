"""Unit tests (pytest). Mock DB — no Postgres required."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

import app as store
import audit
from core import db
from tests.helpers import REPO_ROOT, migrations_src
from tests.helpers import mock_conn as _conn

store.app.config["TESTING"] = True

class TestAudit:

    def test_describe_event_readable(self):
        s = audit.describe_event({'actor_email': 'a@b.c', 'action': 'revealed', 'secret_key': 'API_KEY'})
        assert 'a@b.c' in s
        assert 'revealed' in s
        assert 'API_KEY' in s

    def test_format_time_ago(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        assert audit.format_time_ago(None) == '—'
        assert audit.format_time_ago(now - timedelta(seconds=10)) == 'just now'
        assert audit.format_time_ago(now - timedelta(minutes=5)) == '5 minutes ago'
        assert audit.format_time_ago(now - timedelta(hours=3)) == '3 hours ago'
        assert audit.format_time_ago(now - timedelta(days=4)) == '4 days ago'
        abs_s = audit.format_when(now - timedelta(hours=1))
        assert 'UTC' in abs_s

    def test_global_search_requires_login(self):
        r = store.app.test_client().get('/search?q=x')
        assert r.status_code == 302

    def test_filter_clause_actor_action_dates(self):
        sql, params = audit._filter_clause(actor='bob', action='revealed', since='2026-01-01', until='2026-01-02')
        assert 'actor_email' in sql
        assert 'action' in sql
        assert 'created_at' in sql
        assert params[0] == '%bob%'
        assert params[1] == 'revealed'

    def test_invalid_action_raises(self):
        cur = MagicMock()
        with store.app.test_request_context('/'):
            with pytest.raises(ValueError):
                audit.log_secret(cur, project_id=uuid4(), action='nope')

    def test_log_secret_calls_audit_secret_fn(self):
        cur = MagicMock()
        pid, sid = (uuid4(), uuid4())
        with store.app.test_request_context('/'):
            from flask import session
            session['user_id'] = str(uuid4())
            session['email'] = 'a@b.c'
            audit.log_secret(cur, project_id=pid, secret_id=sid, secret_key='K', action='revealed')
        assert cur.execute.call_count == 1
        sql, params = (cur.execute.call_args.args[0], cur.execute.call_args.args[1])
        assert 'private.audit_secret' in sql
        assert 'NULL::uuid' in sql
        assert 'INSERT INTO api.secret_audit' not in sql
        assert params[4] == 'a@b.c'
        # trailing request-meta params (ip, user agent), blank with no headers
        assert params[-2] == ''
        assert params[-1] == ''

    def test_log_secret_emits_console_json(self):
        import json
        import logging
        cur = MagicMock()
        pid, sid = (uuid4(), uuid4())
        records: list[logging.LogRecord] = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        logger = logging.getLogger('corvus.audit')
        cap = Capture()
        logger.addHandler(cap)
        try:
            with store.app.test_request_context('/'):
                from flask import session
                session['email'] = 'siem@b.c'
                audit.log_secret(cur, project_id=pid, secret_key='API_KEY', action='revealed')
        finally:
            logger.removeHandler(cap)
        assert len(records) == 1
        payload = json.loads(records[0].getMessage())
        assert payload['event'] == 'secret_audit'
        assert payload['action'] == 'revealed'
        assert payload['actor'] == 'siem@b.c'
        assert payload['project_id'] == str(pid)
        assert payload['secret_key'] == 'API_KEY'
        # single line — SIEM shippers parse one event per line
        assert '\n' not in records[0].getMessage()

    def test_log_secret_passes_ip_and_user_agent(self):
        cur = MagicMock()
        pid = uuid4()
        with store.app.test_request_context(
            '/',
            headers={'User-Agent': 'CorvusCLI/1.0', 'X-Forwarded-For': '203.0.113.7, 70.0.0.1'},
        ):
            from flask import session
            session['email'] = 'a@b.c'
            audit.log_secret(cur, project_id=pid, secret_key='K', action='revealed')
        sql, params = (cur.execute.call_args.args[0], cur.execute.call_args.args[1])
        assert 'private.audit_secret' in sql
        assert params[-2] == '203.0.113.7'
        assert params[-1] == 'CorvusCLI/1.0'

    def test_log_org_passes_ip_and_user_agent(self):
        cur = MagicMock()
        with store.app.test_request_context(
            '/', headers={'User-Agent': 'Mozilla/5.0'},
            environ_overrides={'REMOTE_ADDR': '198.51.100.9'},
        ):
            from flask import session
            session['email'] = 'a@b.c'
            audit.log_org(cur, action='member_add', detail='x', team_id=uuid4())
        sql, params = (cur.execute.call_args.args[0], cur.execute.call_args.args[1])
        assert 'private.audit_org' in sql
        assert params[-2] == '198.51.100.9'
        assert params[-1] == 'Mozilla/5.0'

    def test_client_meta_blank_outside_request(self):
        assert audit._client_meta() == ('', '')

    def test_filter_clause_ip_and_hide_reveals(self):
        sql, params = audit._filter_clause(ip='203.0.113', hide_reveals=True)
        assert 'ip_address' in sql
        assert params[0] == '%203.0.113%'
        assert "action <> 'revealed'" in sql
        sql2, params2 = audit._filter_clause()
        assert 'ip_address' not in sql2
        assert 'revealed' not in sql2
        assert params2 == []

    def test_list_secret_audit_is_global(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{
            'actor_email': 'a@b.c', 'action': 'revealed', 'secret_key': 'API_KEY',
            'created_at': datetime.now(timezone.utc),
        }]
        rows = audit.list_secret_audit(
            cur, actor='a@', action='revealed', ip='203.0.113',
            hide_reveals=True, limit=10, offset=5,
        )
        sql, params = (cur.execute.call_args.args[0], cur.execute.call_args.args[1])
        assert 'FROM api.secret_audit' in sql
        assert 'LEFT JOIN api.projects' in sql
        assert 'project_id = %s' not in sql
        assert "action <> 'revealed'" in sql
        assert 'LIMIT %s OFFSET %s' in sql
        assert params[-2:] == (10, 5)
        assert '%a@%' in params
        assert 'revealed' in params
        assert 'a@b.c' in rows[0]['summary']
        assert 'API_KEY' in rows[0]['summary']
        assert 'when_display' in rows[0]

    def test_count_secret_audit(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'n': 7}
        assert audit.count_secret_audit(cur, q='api') == 7
        sql, params = (cur.execute.call_args.args[0], cur.execute.call_args.args[1])
        assert 'count(*)' in sql
        assert 'FROM api.secret_audit' in sql
        assert '%api%' in params

    def test_admin_audit_activity_tab_renders_rows(self):
        uid = str(uuid4())
        client = store.app.test_client()
        with client.session_transaction() as s:
            s['user_id'] = uid
            s['email'] = 'admin@ex.com'
        rows = [{
            'id': uuid4(), 'secret_id': uuid4(), 'secret_key': 'API_KEY',
            'action': 'revealed', 'created_at': datetime.now(timezone.utc),
            'actor_email': 'a@b.c', 'user_id': uid,
            'ip_address': '203.0.113.7', 'user_agent': 'CorvusCLI/1.0',
            'project_id': uuid4(), 'project_name': 'API', 'team_name': 'Platform',
            'actor_name': 'a@b.c', 'summary': 'a@b.c revealed “API_KEY”',
            'when_display': 'just now',
        }]
        conn, _cur = _conn(fetchone={'is_global_admin': True}, fetchall=[])
        with patch.object(db, 'connect_admin', return_value=conn), \
             patch.object(audit, 'count_secret_audit', return_value=1), \
             patch.object(audit, 'list_secret_audit', return_value=rows) as mock_list:
            r = client.get('/admin/audit?tab=activity&action=revealed')
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'Secret activity' in body
        assert 'API_KEY' in body
        assert 'Platform' in body
        assert mock_list.call_args.kwargs['action'] == 'revealed'

    def test_admin_audit_roles_all_passes_no_action_filter(self):
        uid = str(uuid4())
        client = store.app.test_client()
        with client.session_transaction() as s:
            s['user_id'] = uid
            s['email'] = 'admin@ex.com'
        conn, _cur = _conn(fetchone={'is_global_admin': True}, fetchall=[])
        with patch.object(db, 'connect_admin', return_value=conn), \
             patch.object(audit, 'count_org_audit', return_value=0) as mock_count, \
             patch.object(audit, 'list_org_audit', return_value=[]) as mock_list:
            r = client.get('/admin/audit?tab=roles&role_actions=all')
        assert r.status_code == 200
        assert 'All org events' in r.get_data(as_text=True)
        assert mock_count.call_args.kwargs['actions'] is None
        assert mock_list.call_args.kwargs['actions'] is None

    def test_list_queries_select_ip_and_user_agent(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        audit.list_for_project(cur, uuid4(), limit=1)
        assert 'ip_address' in cur.execute.call_args.args[0]
        assert 'user_agent' in cur.execute.call_args.args[0]
        audit.list_org_audit(cur, limit=1)
        assert 'ip_address' in cur.execute.call_args.args[0]
        assert 'user_agent' in cur.execute.call_args.args[0]
        audit.export_secret_audit(cur, limit=1)
        assert 'ip_address' in cur.execute.call_args.args[0]
        audit.export_org_audit(cur, limit=1)
        assert 'ip_address' in cur.execute.call_args.args[0]

    def test_migration_0012_adds_audit_ip_columns(self):
        sql = (REPO_ROOT / 'db' / 'migrations' / '0001_init.sql').read_text()
        assert 'api.secret_audit' in sql and 'ip_address' in sql
        assert 'api.org_audit' in sql and 'user_agent' in sql
        assert 'p_ip_address' in sql and 'p_user_agent' in sql

    def test_schema_revokes_secret_audit_insert(self):
        init = (REPO_ROOT / 'db' / 'migrations' / '0001_init.sql').read_text()
        assert 'REVOKE INSERT ON api.secret_audit FROM authenticated' in init
        assert 'CREATE OR REPLACE FUNCTION private.audit_secret' in init
        assert 'Never trust caller-supplied p_user_id' in init
        src = migrations_src()
        assert 'REVOKE INSERT ON api.secret_audit FROM authenticated' in src
        assert 'private.audit_secret' in src
        assert 'Never trust caller-supplied p_user_id' in src

