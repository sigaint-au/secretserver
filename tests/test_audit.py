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

    def test_log_org_event_commits_and_never_raises(self):
        conn, _cur = _conn()
        conn.autocommit = False
        with patch.object(db, 'connect_admin', return_value=conn), \
             patch('audit.write.log_org') as mock_log:
            audit.log_org_event(audit.ORG_PAT_CREATED, "detail")
        mock_log.assert_called_once()
        conn.commit.assert_called_once()
        with patch.object(db, 'connect_admin', side_effect=RuntimeError('db down')):
            audit.log_org_event(audit.ORG_PAT_CREATED)

    def test_filter_access_rows(self):
        rows = [
            {'email': 'a@x.com', 'name': 'A', 'scope': 'global', 'team': '',
             'team_role': '', 'project': '', 'project_role': '',
             'access_via': 'global_admin'},
            {'email': 'b@x.com', 'name': 'B', 'scope': 'team', 'team': 'Platform',
             'team_role': 'member', 'project': '', 'project_role': '',
             'access_via': 'team:member'},
            {'email': 'c@x.com', 'name': 'C', 'scope': 'project', 'team': 'Platform',
             'team_role': '', 'project': 'API', 'project_role': 'viewer',
             'access_via': 'project:viewer'},
        ]
        assert len(audit.filter_access_rows(rows)) == 3
        team_only = audit.filter_access_rows(rows, scope='team')
        assert [r['email'] for r in team_only] == ['b@x.com']
        plat = audit.filter_access_rows(rows, q='platform')
        assert [r['email'] for r in plat] == ['b@x.com', 'c@x.com']
        assert audit.filter_access_rows(rows, scope='bogus', q='zzz') == []

    def test_list_login_failures(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{
            'email': 'a@b.c', 'ip_address': '203.0.113.9',
            'created_at': datetime.now(timezone.utc),
        }]
        rows = audit.list_login_failures(cur, q='a@', limit=5)
        sql, params = (cur.execute.call_args.args[0], cur.execute.call_args.args[1])
        assert 'FROM private.login_failures' in sql
        assert 'email ILIKE' in sql
        assert 'ip_address ILIKE' in sql
        assert params[-2:] == (5, 0)
        assert rows[0]['when_display']

    def test_count_login_failures(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'n': 4}
        assert audit.count_login_failures(cur, q='a@') == 4
        assert 'private.login_failures' in cur.execute.call_args.args[0]

    def test_purge_preview_zero_when_forever(self):
        cur = MagicMock()
        assert audit.purge_preview(cur, 0) == {
            'secret_audit': 0, 'org_audit': 0, 'login_failures': 0,
        }
        cur.execute.assert_not_called()

    def test_purge_preview_counts(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'n': 2}
        out = audit.purge_preview(cur, 30)
        assert out == {'secret_audit': 2, 'org_audit': 2, 'login_failures': 2}
        assert cur.execute.call_count == 3

    def test_export_secret_audit_filters(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        audit.export_secret_audit(
            cur, q='key', actor='a@', action='revealed', ip='203.0',
            hide_reveals=True,
        )
        sql, params = (cur.execute.call_args.args[0], cur.execute.call_args.args[1])
        assert 'FROM api.secret_audit' in sql
        assert "action <> 'revealed'" in sql
        assert '%key%' in params
        assert '%a@%' in params
        assert 'revealed' in params

    def test_export_org_audit_actions(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        audit.export_org_audit(cur, actions=audit.ROLE_CHANGE_ACTIONS, q='x', actor='y')
        sql, params = (cur.execute.call_args.args[0], cur.execute.call_args.args[1])
        assert '= ANY' in sql
        assert '%y%' in params

    def _admin_client(self):
        uid = str(uuid4())
        client = store.app.test_client()
        with client.session_transaction() as s:
            s['user_id'] = uid
            s['email'] = 'admin@ex.com'
        return client

    def test_access_tab_filters_and_paginates(self):
        rows = [
            {'email': 'a@x.com', 'name': 'A', 'scope': 'global', 'team': '',
             'team_role': '', 'project': '', 'project_role': '',
             'access_via': 'global_admin', 'user_id': 'u1',
             'is_global_admin': True, 'disabled': False},
            {'email': 'b@x.com', 'name': 'B', 'scope': 'team', 'team': 'Platform',
             'team_role': 'member', 'project': '', 'project_role': '',
             'access_via': 'team:member', 'user_id': 'u2',
             'is_global_admin': False, 'disabled': False},
        ]
        conn, _cur = _conn(fetchone={'is_global_admin': True}, fetchall=[])
        client = self._admin_client()
        with patch.object(db, 'connect_admin', return_value=conn), \
             patch.object(audit, 'access_review_rows', return_value=rows):
            r = client.get('/admin/audit?tab=access&scope=team&q=platform')
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'b@x.com' in body
        assert 'a@x.com' not in body
        assert '1 access grants' in body

    def test_logins_tab_renders(self):
        rows = [{
            'id': 1, 'email': 'victim@ex.com', 'ip_address': '203.0.113.9',
            'created_at': datetime.now(timezone.utc), 'when_display': 'just now',
        }]
        conn, _cur = _conn(fetchone={'is_global_admin': True}, fetchall=[])
        client = self._admin_client()
        with patch.object(db, 'connect_admin', return_value=conn), \
             patch.object(audit, 'count_login_failures', return_value=1), \
             patch.object(audit, 'list_login_failures', return_value=rows):
            r = client.get('/admin/audit?tab=logins')
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'Sign-in failures' in body
        assert 'victim@ex.com' in body
        assert '203.0.113.9' in body

    def test_export_tab_shows_purge_preview(self):
        conn, _cur = _conn(fetchone={'is_global_admin': True}, fetchall=[])
        client = self._admin_client()
        counts = {
            'secret_audit': 10, 'org_audit': 5, 'login_failures': 3,
            'oldest': None, 'newest': None,
        }
        preview = {'secret_audit': 4, 'org_audit': 1, 'login_failures': 2}
        with patch.object(db, 'connect_admin', return_value=conn), \
             patch.object(audit, 'audit_counts', return_value=counts), \
             patch.object(audit, 'purge_preview', return_value=preview):
            r = client.get('/admin/audit?tab=export')
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'Purging now would delete' in body
        assert 'Sign-in failures' in body

    def test_access_export_applies_filters(self):
        import json

        rows = [
            {'email': 'a@x.com', 'name': 'A', 'scope': 'global', 'team': '',
             'team_role': '', 'project': '', 'project_role': '',
             'access_via': 'global_admin', 'user_id': 'u1',
             'is_global_admin': True, 'disabled': False},
            {'email': 'b@x.com', 'name': 'B', 'scope': 'team', 'team': 'Platform',
             'team_role': 'member', 'project': '', 'project_role': '',
             'access_via': 'team:member', 'user_id': 'u2',
             'is_global_admin': False, 'disabled': False},
        ]
        conn, _cur = _conn(fetchone={'is_global_admin': True}, fetchall=[])
        client = self._admin_client()
        with patch.object(db, 'connect_admin', return_value=conn), \
             patch.object(audit, 'access_review_rows', return_value=rows):
            r = client.get('/admin/audit/access/export?format=json&scope=team')
        assert r.status_code == 200
        payload = json.loads(r.get_data(as_text=True))
        assert payload['count'] == 1
        assert payload['rows'][0]['email'] == 'b@x.com'

    def test_audit_export_org_role_actions(self):
        conn, _cur = _conn(fetchone={'is_global_admin': True}, fetchall=[])
        client = self._admin_client()
        with patch.object(db, 'connect_admin', return_value=conn), \
             patch.object(audit, 'export_org_audit', return_value=[]) as mock_exp:
            r = client.get(
                '/admin/audit/export?format=csv&source=org&role_actions=roles&actor=a@'
            )
        assert r.status_code == 200
        assert mock_exp.call_args.kwargs['actions'] == audit.ROLE_CHANGE_ACTIONS
        assert mock_exp.call_args.kwargs['actor'] == 'a@'

    def test_audit_export_secret_filters(self):
        conn, _cur = _conn(fetchone={'is_global_admin': True}, fetchall=[])
        client = self._admin_client()
        with patch.object(db, 'connect_admin', return_value=conn), \
             patch.object(audit, 'export_secret_audit', return_value=[]) as mock_exp:
            r = client.get(
                '/admin/audit/export?format=csv&source=secret'
                '&action=revealed&hide_reveals=1'
            )
        assert r.status_code == 200
        assert mock_exp.call_args.kwargs['action'] == 'revealed'
        assert mock_exp.call_args.kwargs['hide_reveals'] is True

    def test_list_queries_select_ip_and_user_agent(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        audit.list_for_project(cur, uuid4(), limit=1)
        assert 'ip_address' in cur.execute.call_args.args[0]
        assert 'user_agent' in cur.execute.call_args.args[0]
        audit.list_org_audit(cur, limit=1)
        assert 'ip_address' in cur.execute.call_args.args[0]
        assert 'user_agent' in cur.execute.call_args.args[0]
        audit.list_secret_audit(cur, limit=1)
        assert 'ip_address' in cur.execute.call_args.args[0]
        assert 'user_agent' in cur.execute.call_args.args[0]
        audit.list_login_failures(cur, limit=1)
        assert 'ip_address' in cur.execute.call_args.args[0]
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

