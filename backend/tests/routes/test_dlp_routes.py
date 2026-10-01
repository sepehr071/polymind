"""
DLP routes tests — auth, RBAC, scan, policy, events, stats, admin.

All helpers are inlined; no new conftest fixtures beyond what conftest.py provides.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from bson import ObjectId
from flask_jwt_extended import create_access_token


# ---------------------------------------------------------------------------
# Inline helpers
# ---------------------------------------------------------------------------

def _make_user(app, email: str, display_name: str = 'User', role: str = 'manager'):
    from app.models.user import UserModel
    with app.app_context():
        return UserModel.create(email=email, password='Pw123!@#', display_name=display_name, role=role)


def _headers(app, user: dict) -> dict:
    with app.app_context():
        tok = create_access_token(identity=str(user['_id']))
    return {'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'}


def _create_team_ws(client, headers: dict, name: str = 'Test Workspace') -> dict:
    r = client.post('/api/workspaces/create', json={'name': name}, headers=headers)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _add_member(app, workspace_id: str, user_id: str, role: str = 'editor') -> None:
    from app.models.workspace_member import WorkspaceMemberModel
    with app.app_context():
        WorkspaceMemberModel.add(workspace_id, user_id, role, status='active')


def _seed_event(app, workspace_id: str, user_id: str, **overrides) -> dict:
    """Create a DLPEventModel row directly in the DB and return the doc."""
    from app.models.dlp_event import DLPEventModel
    defaults = dict(
        user_id=user_id,
        workspace_id=workspace_id,
        project_id=None,
        source='chat',
        source_ref={},
        matches=[
            {
                'rule_id': 'anthropic_api_key',
                'rule_name': 'Anthropic API Key',
                'severity': 'critical',
                'action': 'block',
                'snippet': '***',
                'offset_start': 0,
                'offset_end': 20,
            }
        ],
        highest_action='block',
        was_sent=False,
        text_sha256='abc123',
        text_length=42,
    )
    defaults.update(overrides)
    with app.app_context():
        return DLPEventModel.create(**defaults)


# ---------------------------------------------------------------------------
# Scan endpoint
# ---------------------------------------------------------------------------

class TestDLPScan:
    def test_scan_anonymous_401(self, app, db, client):
        r = client.post(
            '/api/dlp/scan',
            json={'text': 'hello', 'workspace_id': str(ObjectId()), 'source': 'chat'},
        )
        assert r.status_code == 401

    def test_scan_returns_matches(self, app, db, client, test_user, auth_headers):
        # Create a workspace so the user is a member
        ws = _create_team_ws(client, auth_headers, name='ScanWS')
        wid = ws['_id']

        # A text containing an Anthropic API key (real-looking)
        text = 'My key is sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghij'

        # Enable DLP for this workspace
        with app.app_context():
            from app.extensions import mongo
            mongo.db.workspaces.update_one(
                {'_id': ObjectId(wid)},
                {'$set': {'settings.dlp': {'enabled': True, 'sensitivity': 'balanced'}}},
            )

        r = client.post(
            '/api/dlp/scan',
            json={'text': text, 'workspace_id': wid, 'source': 'chat'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert 'result' in data
        result = data['result']
        assert 'matches' in result
        assert 'highest_action' in result
        assert isinstance(result['matches'], list)
        # Should find at least one match for the Anthropic key
        assert len(result['matches']) >= 1
        rule_ids = [m['rule_id'] for m in result['matches']]
        assert 'anthropic_api_key' in rule_ids
        assert result['highest_action'] == 'block'

    def test_scan_no_workspace_access_403(self, app, db, client, test_user, auth_headers):
        # Create a workspace as a different user so test_user has no access
        owner = _make_user(app, 'owner_scan@example.com', 'Owner')
        h_owner = _headers(app, owner)
        ws = _create_team_ws(client, h_owner, name='OtherWS')
        wid = ws['_id']

        r = client.post(
            '/api/dlp/scan',
            json={'text': 'hello', 'workspace_id': wid, 'source': 'chat'},
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_scan_response_includes_event_id_when_persisted(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='EventIdScanWS')
        wid = ws['_id']

        # Enable DLP so block-tier match persists an event
        with app.app_context():
            from app.extensions import mongo
            mongo.db.workspaces.update_one(
                {'_id': ObjectId(wid)},
                {'$set': {'settings.dlp': {'enabled': True, 'sensitivity': 'balanced'}}},
            )

        text = 'My key is sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghij'
        r = client.post(
            '/api/dlp/scan',
            json={'text': text, 'workspace_id': wid, 'source': 'chat'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert 'event_id' in data
        assert data['event_id'] is not None and isinstance(data['event_id'], str)
        # Sanity: row landed in dlp_events
        with app.app_context():
            from app.extensions import mongo
            assert mongo.db.dlp_events.count_documents({'_id': ObjectId(data['event_id'])}) == 1

    def test_scan_response_persists_warn_events(self, app, db, client, test_user, auth_headers):
        """P2.27 — warn-level matches now persist a dlp_event row too so
        manager dashboards can spot policy drift. Event is logged with
        was_sent=False on pre-flight regardless of action level."""
        ws = _create_team_ws(client, auth_headers, name='WarnOnlyScanWS')
        wid = ws['_id']

        # 'strict' so low-severity 'email' rule fires (warn)
        with app.app_context():
            from app.extensions import mongo
            mongo.db.workspaces.update_one(
                {'_id': ObjectId(wid)},
                {'$set': {'settings.dlp': {'enabled': True, 'sensitivity': 'strict'}}},
            )

        r = client.post(
            '/api/dlp/scan',
            json={'text': 'Reach me at user@example.com', 'workspace_id': wid, 'source': 'chat'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data['result']['highest_action'] == 'warn'
        assert 'event_id' in data
        assert data['event_id'] is not None and isinstance(data['event_id'], str)
        with app.app_context():
            from app.extensions import mongo
            assert mongo.db.dlp_events.count_documents({'_id': ObjectId(data['event_id'])}) == 1

    def test_scan_rate_limit_429(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='RateLimitWS')
        wid = ws['_id']

        # Patch _RATE_LIMIT_MAX to 3 to avoid hammering 60 calls
        import app.routes.dlp as dlp_mod
        original_max = dlp_mod._RATE_LIMIT_MAX
        original_scan_rate = dlp_mod._scan_rate.copy()
        dlp_mod._RATE_LIMIT_MAX = 3
        # Reset the rate bucket for this user
        uid = str(test_user['_id'])
        dlp_mod._scan_rate.pop(uid, None)

        try:
            for i in range(3):
                r = client.post(
                    '/api/dlp/scan',
                    json={'text': 'hello', 'workspace_id': wid, 'source': 'chat'},
                    headers=auth_headers,
                )
                assert r.status_code == 200, f"Call {i+1} should succeed"

            # 4th call should be rate-limited
            r = client.post(
                '/api/dlp/scan',
                json={'text': 'hello', 'workspace_id': wid, 'source': 'chat'},
                headers=auth_headers,
            )
            assert r.status_code == 429
            data = r.get_json()
            assert data['error'] == 'rate_limited'
            assert 'retry_after' in data
        finally:
            dlp_mod._RATE_LIMIT_MAX = original_max
            dlp_mod._scan_rate.pop(uid, None)


# ---------------------------------------------------------------------------
# Test classifier playground endpoint
# ---------------------------------------------------------------------------

class TestDLPTestEndpoint:
    def test_owner_can_run_test_returns_result(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='TestPlaygroundWS')
        wid = ws['_id']

        # Enable DLP so a real builtin rule fires
        with app.app_context():
            from app.extensions import mongo
            mongo.db.workspaces.update_one(
                {'_id': ObjectId(wid)},
                {'$set': {'settings.dlp': {'enabled': True, 'sensitivity': 'strict'}}},
            )

        r = client.post(
            '/api/dlp/test',
            json={'text': 'Reach me at user@example.com', 'workspace_id': wid},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert 'result' in data
        rule_ids = [m['rule_id'] for m in data['result']['matches']]
        assert 'email' in rule_ids
        # Endpoint must NOT also return event_id (this is not /scan)
        assert 'event_id' not in data

    def test_test_endpoint_does_not_persist_event(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='NoPersistTestWS')
        wid = ws['_id']

        with app.app_context():
            from app.extensions import mongo
            mongo.db.workspaces.update_one(
                {'_id': ObjectId(wid)},
                {'$set': {'settings.dlp': {'enabled': True, 'sensitivity': 'balanced'}}},
            )
            before = mongo.db.dlp_events.count_documents({})

        text = 'My key is sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghij'
        r = client.post(
            '/api/dlp/test',
            json={'text': text, 'workspace_id': wid},
            headers=auth_headers,
        )
        assert r.status_code == 200
        # Even though this would have been a 'block' on /scan, no event row.
        with app.app_context():
            from app.extensions import mongo
            after = mongo.db.dlp_events.count_documents({})
        assert after == before

    def test_non_owner_viewer_403(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='ViewerForbiddenWS')
        wid = ws['_id']

        viewer = _make_user(app, 'viewer_test_endpoint@example.com', 'Viewer')
        _add_member(app, wid, str(viewer['_id']), role='viewer')
        h_viewer = _headers(app, viewer)

        r = client.post(
            '/api/dlp/test',
            json={'text': 'hello world', 'workspace_id': wid},
            headers=h_viewer,
        )
        assert r.status_code == 403
        data = r.get_json()
        assert data.get('code') == 'forbidden'

    def test_test_endpoint_ignores_rate_limit(self, app, db, client, test_user, auth_headers):
        """The test playground must not be rate-limited (mirrors plan §3)."""
        ws = _create_team_ws(client, auth_headers, name='NoRateLimitTestWS')
        wid = ws['_id']

        # Tighten the /scan rate limit to verify /test doesn't share the bucket.
        import app.routes.dlp as dlp_mod
        original_max = dlp_mod._RATE_LIMIT_MAX
        dlp_mod._RATE_LIMIT_MAX = 2
        uid = str(test_user['_id'])
        dlp_mod._scan_rate.pop(uid, None)

        try:
            for i in range(5):
                r = client.post(
                    '/api/dlp/test',
                    json={'text': 'just a plain message', 'workspace_id': wid},
                    headers=auth_headers,
                )
                assert r.status_code == 200, f"Test call {i + 1} should not be rate-limited"
        finally:
            dlp_mod._RATE_LIMIT_MAX = original_max
            dlp_mod._scan_rate.pop(uid, None)

    def test_test_endpoint_validates_input(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='ValidateTestWS')
        wid = ws['_id']

        r = client.post('/api/dlp/test', json={'workspace_id': wid}, headers=auth_headers)
        assert r.status_code == 400

        r = client.post('/api/dlp/test', json={'text': 'hi'}, headers=auth_headers)
        assert r.status_code == 400

        r = client.post(
            '/api/dlp/test',
            json={'text': 'hi', 'workspace_id': 'not-an-objectid'},
            headers=auth_headers,
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Policy endpoints
# ---------------------------------------------------------------------------

class TestDLPPolicy:
    def test_get_policy_default_when_unset(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='PolicyWS')
        wid = ws['_id']

        r = client.get(f'/api/workspaces/{wid}/dlp/policy', headers=auth_headers)
        assert r.status_code == 200
        data = r.get_json()
        assert 'policy' in data
        assert 'rule_catalog' in data
        # Defaults: enabled=False
        assert data['policy']['enabled'] is False
        assert data['policy']['sensitivity'] == 'balanced'

    def test_get_policy_includes_rule_catalog(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='CatalogWS')
        wid = ws['_id']

        r = client.get(f'/api/workspaces/{wid}/dlp/policy', headers=auth_headers)
        assert r.status_code == 200
        catalog = r.get_json()['rule_catalog']
        assert isinstance(catalog, list)
        assert len(catalog) > 0
        # Each entry must have id, name, severity, default_action, category
        for entry in catalog:
            assert 'id' in entry
            assert 'name' in entry
            assert 'severity' in entry
            assert 'default_action' in entry
            assert 'category' in entry
        # Check known rule is present
        ids = [e['id'] for e in catalog]
        assert 'anthropic_api_key' in ids

    def test_put_policy_owner_only(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='OwnerOnlyWS')
        wid = ws['_id']

        # Create an editor and add to workspace
        editor = _make_user(app, 'editor_policy@example.com', 'Editor')
        _add_member(app, wid, str(editor['_id']), role='editor')
        h_editor = _headers(app, editor)

        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={'enabled': True},
            headers=h_editor,
        )
        assert r.status_code == 403

    def test_put_policy_persists(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='PersistPolicyWS')
        wid = ws['_id']

        custom_pattern = {
            'name': 'Project Codename',
            'regex': r'\bPROJECT-\d{4}\b',
            'severity': 'high',
            'action': 'warn',
        }

        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={
                'enabled': True,
                'sensitivity': 'strict',
                'custom_patterns': [custom_pattern],
            },
            headers=auth_headers,
        )
        assert r.status_code == 200
        policy = r.get_json()['policy']
        assert policy['enabled'] is True
        assert policy['sensitivity'] == 'strict'
        assert len(policy['custom_patterns']) == 1
        assert policy['custom_patterns'][0]['name'] == 'Project Codename'

        # GET should return same values
        r2 = client.get(f'/api/workspaces/{wid}/dlp/policy', headers=auth_headers)
        policy2 = r2.get_json()['policy']
        assert policy2['enabled'] is True
        assert policy2['sensitivity'] == 'strict'
        assert len(policy2['custom_patterns']) == 1

    def test_put_policy_rejects_invalid_regex(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='InvalidRegexWS')
        wid = ws['_id']

        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={
                'custom_patterns': [
                    {'name': 'Bad', 'regex': '[unclosed', 'severity': 'high', 'action': 'warn'}
                ],
            },
            headers=auth_headers,
        )
        assert r.status_code == 400
        assert 'regex' in r.get_json().get('error', '').lower()

    def test_put_policy_rejects_rule_override_below_floor(self, app, db, client, test_user, auth_headers):
        """
        Severity-floor enforcement: critical rules cannot be loosened (only block),
        high rules cannot drop below block, medium rules cannot drop below warn.
        Incoming require_confirm is stored as block, not rejected.
        Custom (unknown) rule_ids bypass the floor and accept any action.
        Multiple violations are returned in a single 400 response.
        """
        ws = _create_team_ws(client, auth_headers, name='FloorWS')
        wid = ws['_id']

        # 1. Critical rule -> allow: BLOCKED
        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={'rule_overrides': {'aws_access_key': 'allow'}},
            headers=auth_headers,
        )
        assert r.status_code == 400
        data = r.get_json()
        assert data.get('error') == 'rule_override_below_floor'
        assert isinstance(data.get('violations'), list)
        rule_ids = {v['rule_id']: v for v in data['violations']}
        assert 'aws_access_key' in rule_ids
        assert rule_ids['aws_access_key']['severity'] == 'critical'
        assert rule_ids['aws_access_key']['min_action'] == 'block'

        # Confirm the policy was NOT persisted
        g = client.get(f'/api/workspaces/{wid}/dlp/policy', headers=auth_headers)
        pol = g.get_json()['policy']
        assert pol.get('rule_overrides', {}).get('aws_access_key') != 'allow'

        # 2. High rule -> warn: BLOCKED (below block floor)
        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={'rule_overrides': {'jwt_token': 'warn'}},
            headers=auth_headers,
        )
        assert r.status_code == 400
        data = r.get_json()
        assert data['error'] == 'rule_override_below_floor'
        ids = {v['rule_id'] for v in data['violations']}
        assert 'jwt_token' in ids

        # 2b. High rule -> block: ACCEPTED
        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={'rule_overrides': {'jwt_token': 'block'}},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.get_json()['policy']['rule_overrides']['jwt_token'] == 'block'

        # 2c. High rule -> require_confirm: coerced to block, not 400
        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={'rule_overrides': {'jwt_token': 'require_confirm'}},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.get_json()['policy']['rule_overrides']['jwt_token'] == 'block'

        # 3. Medium rule -> allow: BLOCKED (below warn floor)
        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={'rule_overrides': {'ipv4_private': 'allow'}},
            headers=auth_headers,
        )
        assert r.status_code == 400
        ids = {v['rule_id'] for v in r.get_json()['violations']}
        assert 'ipv4_private' in ids

        # 4. Multiple violations returned in single response
        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={'rule_overrides': {
                'aws_access_key': 'allow',
                'jwt_token': 'warn',
                'ipv4_private': 'allow',
            }},
            headers=auth_headers,
        )
        assert r.status_code == 400
        data = r.get_json()
        ids = {v['rule_id'] for v in data['violations']}
        assert ids == {'aws_access_key', 'jwt_token', 'ipv4_private'}

        # 5. Low rule -> allow: ACCEPTED (floor is allow)
        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={'rule_overrides': {'email': 'allow'}},
            headers=auth_headers,
        )
        assert r.status_code == 200
        pol = r.get_json()['policy']
        assert pol['rule_overrides']['email'] == 'allow'

        # 6. Medium rule TIGHTENED to block: ACCEPTED (tightening is fine)
        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={'rule_overrides': {'ipv4_private': 'block'}},
            headers=auth_headers,
        )
        assert r.status_code == 200
        pol = r.get_json()['policy']
        assert pol['rule_overrides']['ipv4_private'] == 'block'

        # 7. Custom (unknown) rule_id with 'allow': ACCEPTED (no floor for custom rules)
        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={'rule_overrides': {'custom_rule_abc123': 'allow'}},
            headers=auth_headers,
        )
        assert r.status_code == 200
        pol = r.get_json()['policy']
        assert pol['rule_overrides']['custom_rule_abc123'] == 'allow'

        # 8. Critical rule overridden to 'block' (redundant but allowed)
        r = client.put(
            f'/api/workspaces/{wid}/dlp/policy',
            json={'rule_overrides': {'aws_access_key': 'block'}},
            headers=auth_headers,
        )
        assert r.status_code == 200
        pol = r.get_json()['policy']
        assert pol['rule_overrides']['aws_access_key'] == 'block'


# ---------------------------------------------------------------------------
# Events endpoints
# ---------------------------------------------------------------------------

class TestDLPEvents:
    def test_events_list_owner_required(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='OwnerEventsWS')
        wid = ws['_id']
        _seed_event(app, wid, str(test_user['_id']))

        # Create a viewer member
        viewer = _make_user(app, 'viewer_events@example.com', 'Viewer')
        _add_member(app, wid, str(viewer['_id']), role='viewer')
        h_viewer = _headers(app, viewer)

        r = client.get(f'/api/workspaces/{wid}/dlp/events', headers=h_viewer)
        assert r.status_code == 403

    def test_events_list_filters_by_severity_and_source(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='FilterEventsWS')
        wid = ws['_id']
        uid = str(test_user['_id'])

        _seed_event(app, wid, uid, source='chat', matches=[
            {'rule_id': 'r1', 'rule_name': 'R1', 'severity': 'critical',
             'action': 'block', 'snippet': '***', 'offset_start': 0, 'offset_end': 5}
        ])
        _seed_event(app, wid, uid, source='arena', matches=[
            {'rule_id': 'r2', 'rule_name': 'R2', 'severity': 'low',
             'action': 'warn', 'snippet': '**', 'offset_start': 0, 'offset_end': 3}
        ], highest_action='warn')

        r = client.get(
            f'/api/workspaces/{wid}/dlp/events?source=chat',
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data['total'] >= 1
        sources = [row['source'] for row in data['rows']]
        assert all(s == 'chat' for s in sources)

        r2 = client.get(
            f'/api/workspaces/{wid}/dlp/events?severity=critical',
            headers=auth_headers,
        )
        assert r2.status_code == 200
        data2 = r2.get_json()
        assert data2['total'] >= 1

    def test_events_get_404_for_other_workspace(self, app, db, client, test_user, auth_headers):
        # Workspace A: owner creates it and seeds an event
        ws_a = _create_team_ws(client, auth_headers, name='WorkspaceA')
        wid_a = ws_a['_id']
        event_a = _seed_event(app, wid_a, str(test_user['_id']))
        event_id = str(event_a['_id'])

        # Workspace B: a second user owns it
        owner_b = _make_user(app, 'owner_b@example.com', 'Owner B')
        h_b = _headers(app, owner_b)
        ws_b = _create_team_ws(client, h_b, name='WorkspaceB')
        wid_b = ws_b['_id']

        # Fetch event_a through workspace B's URL — should 404
        r = client.get(f'/api/workspaces/{wid_b}/dlp/events/{event_id}', headers=h_b)
        assert r.status_code == 404

    def test_events_patch_updates_status_and_review_note(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='PatchEventWS')
        wid = ws['_id']
        event = _seed_event(app, wid, str(test_user['_id']))
        eid = str(event['_id'])

        r = client.patch(
            f'/api/workspaces/{wid}/dlp/events/{eid}',
            json={'status': 'reviewed', 'review_note': 'Checked by admin'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        updated = r.get_json()['event']
        assert updated['status'] == 'reviewed'
        assert updated['review_note'] == 'Checked by admin'
        assert updated['reviewed_by'] is not None
        assert updated['reviewed_at'] is not None

    def test_events_patch_invalid_status_400(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='InvalidStatusWS')
        wid = ws['_id']
        event = _seed_event(app, wid, str(test_user['_id']))
        eid = str(event['_id'])

        r = client.patch(
            f'/api/workspaces/{wid}/dlp/events/{eid}',
            json={'status': 'not_a_real_status'},
            headers=auth_headers,
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Stats endpoints
# ---------------------------------------------------------------------------

class TestDLPStats:
    def test_stats_returns_expected_shape(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='StatsWS')
        wid = ws['_id']
        _seed_event(app, wid, str(test_user['_id']))

        r = client.get(f'/api/workspaces/{wid}/dlp/stats', headers=auth_headers)
        assert r.status_code == 200
        stats = r.get_json()

        # Required keys
        assert 'total' in stats
        assert 'by_severity' in stats
        assert 'by_source' in stats
        assert 'top_users' in stats
        assert 'top_rules' in stats
        assert 'daily' in stats

        # by_severity must have all severity keys
        for k in ('low', 'medium', 'high', 'critical'):
            assert k in stats['by_severity']

        # by_source must have all source keys
        for k in ('chat', 'arena', 'workflow'):
            assert k in stats['by_source']

        # total reflects seeded events
        assert stats['total'] >= 1


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

class TestDLPAdmin:
    def test_admin_events_non_admin_403(self, app, db, client, test_user, auth_headers):
        r = client.get('/api/admin/dlp/events', headers=auth_headers)
        assert r.status_code == 403

    def test_admin_events_cross_workspace(self, app, db, client, test_user, auth_headers):
        # Seed events in two different workspaces
        owner_a = _make_user(app, 'admin_ws_a@example.com', 'Owner A')
        h_a = _headers(app, owner_a)
        ws_a = _create_team_ws(client, h_a, name='AdminWS_A')

        owner_b = _make_user(app, 'admin_ws_b@example.com', 'Owner B')
        h_b = _headers(app, owner_b)
        ws_b = _create_team_ws(client, h_b, name='AdminWS_B')

        _seed_event(app, ws_a['_id'], str(owner_a['_id']))
        _seed_event(app, ws_b['_id'], str(owner_b['_id']))

        # Admin user
        admin = _make_user(app, 'dlp_admin@example.com', 'DLP Admin', role='admin')
        h_admin = _headers(app, admin)

        r = client.get('/api/admin/dlp/events', headers=h_admin)
        assert r.status_code == 200
        data = r.get_json()
        assert 'rows' in data
        assert 'total' in data
        # Should see events from both workspaces
        assert data['total'] >= 2
        workspace_ids_seen = {row['workspace_id'] for row in data['rows']}
        assert ws_a['_id'] in workspace_ids_seen
        assert ws_b['_id'] in workspace_ids_seen

    def test_admin_stats_returns_global_shape(self, app, db, client, test_user, auth_headers):
        admin = _make_user(app, 'dlp_stats_admin@example.com', 'Stats Admin', role='admin')
        h_admin = _headers(app, admin)

        r = client.get('/api/admin/dlp/stats', headers=h_admin)
        assert r.status_code == 200
        stats = r.get_json()

        # Same base keys as workspace stats
        for k in ('total', 'by_severity', 'by_source', 'top_users', 'top_rules', 'daily'):
            assert k in stats, f"Missing key: {k}"
        # Plus top_workspaces for admin
        assert 'top_workspaces' in stats


# ---------------------------------------------------------------------------
# Former confirm-token rules are block. Confirmation does not unlock a send.
# ---------------------------------------------------------------------------

# A real-looking JWT that the jwt_token rule (severity=high, default_action=block)
# matches.
_JWT_BLOCK_SAMPLE = (
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9'
    '.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ'
    '.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c'
)


def _enable_dlp_balanced(app, wid: str) -> None:
    from app.extensions import mongo
    with app.app_context():
        mongo.db.workspaces.update_one(
            {'_id': ObjectId(wid)},
            {'$set': {'settings.dlp': {'enabled': True, 'sensitivity': 'balanced'}}},
        )


class TestDLPConfirmDoesNotUnlock:
    """jwt_token is block. /dlp/scan mints no confirm token. dlp_confirmed does not bypass."""

    def test_scan_jwt_is_block_without_confirm_token(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='ConfirmTokenScanWS')
        wid = ws['_id']
        _enable_dlp_balanced(app, wid)

        r = client.post(
            '/api/dlp/scan',
            json={'text': f'token: {_JWT_BLOCK_SAMPLE}', 'workspace_id': wid, 'source': 'chat'},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.get_json()
        data = r.get_json()
        assert data['result']['highest_action'] == 'block'
        assert 'confirm_token' not in data
        assert 'confirm_token_exp' not in data

    def test_scan_does_not_return_token_for_block(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='NoTokenForBlockWS')
        wid = ws['_id']
        _enable_dlp_balanced(app, wid)

        text = 'My key is sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghij'
        r = client.post(
            '/api/dlp/scan',
            json={'text': text, 'workspace_id': wid, 'source': 'chat'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data['result']['highest_action'] == 'block'
        # Block is non-overridable — no token should be issued
        assert 'confirm_token' not in data

    def test_scan_does_not_return_token_for_warn(self, app, db, client, test_user, auth_headers):
        ws = _create_team_ws(client, auth_headers, name='NoTokenForWarnWS')
        wid = ws['_id']
        with app.app_context():
            from app.extensions import mongo
            mongo.db.workspaces.update_one(
                {'_id': ObjectId(wid)},
                {'$set': {'settings.dlp': {'enabled': True, 'sensitivity': 'strict'}}},
            )
        r = client.post(
            '/api/dlp/scan',
            json={'text': 'Reach me at user@example.com', 'workspace_id': wid, 'source': 'chat'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data['result']['highest_action'] == 'warn'
        assert 'confirm_token' not in data

    def test_chat_stream_dlp_confirmed_does_not_bypass(self, app, db, client, test_user, auth_headers):
        """A confirmed flag plus any token still returns 403 dlp_blocked."""
        ws = _create_team_ws(client, auth_headers, name='ChatStreamNoTokenWS')
        wid = ws['_id']
        _enable_dlp_balanced(app, wid)
        with app.app_context():
            from app.extensions import mongo
            mongo.db.users.update_one(
                {'_id': ObjectId(str(test_user['_id']))},
                {'$set': {'active_workspace_id': ObjectId(wid)}},
            )

        with app.app_context():
            from app.models.llm_config import LLMConfigModel
            cfg = LLMConfigModel.create(
                name='Test Config',
                model_id='google/gemini-3.5-flash-lite',
                model_name='Gemini 3.1 Flash Lite',
                owner_id=str(test_user['_id']),
                system_prompt='',
                parameters={'temperature': 0.7, 'max_tokens': 256},
            )
            config_id = cfg['_id']

        body = {
            'config_id': str(config_id),
            'message': f'Here is a token: {_JWT_BLOCK_SAMPLE}',
            'dlp_confirmed': True,
            'dlp_confirm_token': 'not-a-real-token',
        }
        r = client.post('/api/chat/stream', json=body, headers=auth_headers)
        assert r.status_code == 403, r.get_json()
        data = r.get_json()
        assert data.get('code') == 'dlp_blocked'
        assert 'confirm_token' not in data


class TestDLPTokenHelpers:
    """Unit-test the HMAC helpers directly — independent of HTTP plumbing."""

    def test_roundtrip_sign_verify(self, app):
        from app.services.dlp_tokens import _sign_dlp_token, _verify_dlp_token
        with app.app_context():
            exp = int(time.time()) + 60
            payload = f"abc123|user42|wid99|{exp}"
            token = _sign_dlp_token(payload)
            assert _verify_dlp_token(
                token,
                text_sha256='abc123',
                user_id='user42',
                workspace_id='wid99',
            ) is True

    def test_verify_rejects_expired(self, app):
        from app.services.dlp_tokens import _sign_dlp_token, _verify_dlp_token
        with app.app_context():
            exp = int(time.time()) - 1  # already expired
            payload = f"abc123|user42|wid99|{exp}"
            token = _sign_dlp_token(payload)
            assert _verify_dlp_token(
                token,
                text_sha256='abc123',
                user_id='user42',
                workspace_id='wid99',
            ) is False

    def test_verify_rejects_wrong_user(self, app):
        from app.services.dlp_tokens import _sign_dlp_token, _verify_dlp_token
        with app.app_context():
            exp = int(time.time()) + 60
            payload = f"abc123|user42|wid99|{exp}"
            token = _sign_dlp_token(payload)
            assert _verify_dlp_token(
                token,
                text_sha256='abc123',
                user_id='somebody_else',
                workspace_id='wid99',
            ) is False

    def test_verify_rejects_malformed(self, app):
        from app.services.dlp_tokens import _verify_dlp_token
        with app.app_context():
            assert _verify_dlp_token(
                'not.a.real.token',
                text_sha256='abc',
                user_id='u',
                workspace_id='w',
            ) is False
            assert _verify_dlp_token(
                '',
                text_sha256='abc',
                user_id='u',
                workspace_id='w',
            ) is False
