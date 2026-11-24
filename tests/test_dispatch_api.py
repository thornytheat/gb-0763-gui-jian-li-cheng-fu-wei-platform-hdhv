from app.capture.dialect import FIELDS
from app.inputs import sample


def archived_run(client, label='dirty'):
    return client.post('/api/runs', json={'sample': label}).json['run_id']


def test_dispatch_from_issue_page_data(client):
    run_id = archived_run(client)
    resp = client.post(f'/api/runs/{run_id}/dispatch',
                       json={'start': {'chain': 'UP-B', 'station_mm': 2100000},
                             'budget_mm': 250000})
    assert resp.status_code == 201
    plan = resp.json
    assert plan['run_id'] == run_id
    assert plan['driven_mm'] == 200000
    assert plan['planned_mm'] == 200000
    assert plan['route'][0]['start_mm'] == 2100000
    assert plan['remaining_budget_mm'] == 50000


def test_retry_returns_same_plan_without_new_dispatch(client):
    run_id = archived_run(client)
    payload = {'start': {'chain': 'UP-B', 'station_mm': 2100000}, 'budget_mm': 250000}
    first = client.post(f'/api/runs/{run_id}/dispatch', json=payload)
    second = client.post(f'/api/runs/{run_id}/dispatch', json=payload)
    assert first.status_code == 201 and second.status_code == 200
    assert second.json['reused'] is True
    assert second.json['dispatch_id'] == first.json['dispatch_id']
    # 计划里程不进实测：再次对账缺证仍是 200000 mm。
    coverage = client.get('/api/coverage?sample=dirty').json
    assert coverage['missing_mm'] == 200000


def test_start_outside_plan_rejected(client):
    run_id = archived_run(client)
    resp = client.post(f'/api/runs/{run_id}/dispatch',
                       json={'start': {'chain': 'UP-B', 'station_mm': 999}, 'budget_mm': 1000})
    assert (resp.status_code, resp.json['error']) == (422, 'BAD_START')


def test_bad_budget_and_body(client):
    run_id = archived_run(client)
    base = '/api/runs/' + run_id + '/dispatch'
    assert client.post(base, json={'start': {'chain': 'UP-B', 'station_mm': 2100000},
                                   'budget_mm': -1}).json['error'] == 'BAD_BUDGET'
    assert client.post(base, json={'start': {'chain': 'GHOST', 'station_mm': 0},
                                   'budget_mm': 10}).json['error'] == 'BAD_START'
    assert client.post(base, json={'budget_mm': 10}).json['error'] == 'BAD_START'
    assert client.post(base, json={'nope': 1}).json['error'] == 'BAD_BODY'


def test_dispatch_unknown_run(client):
    resp = client.post('/api/runs/ghost/dispatch',
                       json={'start': {'chain': 'UP-B', 'station_mm': 2100000},
                             'budget_mm': 1000})
    assert (resp.status_code, resp.json['error']) == (404, 'RUN_MISSING')


def test_new_batch_invalidates_and_replans(client):
    run_id = archived_run(client)
    url = f'/api/runs/{run_id}/dispatch'
    start = {'chain': 'UP-B', 'station_mm': 2000000}
    first = client.post(url, json={'start': start, 'budget_mm': 500000}).json
    assert len(first['route']) == 1 and first['refreshed'] is False

    # 新批次 B1→B2 的有效双基点区间（2100000–2300000）把整段缺口补齐。
    rows = [','.join(FIELDS),
            'c0,R20,anchor,2026-11-22T00:00:00Z,0,B1,3',
            'c1,R20,anchor,2026-11-22T00:01:00Z,100000,B2,3']
    batch = '\n'.join(rows)
    second = client.post(url, json={'start': start, 'budget_mm': 500000,
                                    'batch_csv': batch})
    assert second.status_code == 201
    assert second.json['refreshed'] is True
    # 缺口已被新批次补齐，本趟无段可补，原安排失效后重算为空计划。
    assert second.json['route'] == []
    assert second.json['assigned_gaps'] == []
    assert second.json['dispatch_id'] != first['dispatch_id']


def test_distinct_budgets_get_distinct_plans(client):
    run_id = archived_run(client)
    url = f'/api/runs/{run_id}/dispatch'
    start = {'chain': 'UP-B', 'station_mm': 2100000}
    full = client.post(url, json={'start': start, 'budget_mm': 250000}).json
    short = client.post(url, json={'start': start, 'budget_mm': 50}).json
    assert full['dispatch_id'] != short['dispatch_id']
    assert short['route'] == [] and short['unassigned_gaps'][0]['state'] == 'BUDGET_EXCEEDED'


def test_issue_page_renders_dispatch_panel(client):
    run_id = archived_run(client)
    page = client.get(f'/work/issue?run={run_id}').get_data(as_text=True)
    for marker in ('交班补巡派车', 'dispatch-form', 'dispatch-chain', 'dispatch-budget',
                   'dispatch-batch', 'UP-B'):
        assert marker in page


def test_dispatch_does_not_mutate_archived_coverage(client):
    run_id = archived_run(client)
    before = client.get(f'/api/runs/{run_id}').json['stages']['coverage']['missing_parts']
    client.post(f'/api/runs/{run_id}/dispatch',
                json={'start': {'chain': 'UP-B', 'station_mm': 2100000}, 'budget_mm': 250000})
    after = client.get(f'/api/runs/{run_id}').json['stages']['coverage']['missing_parts']
    assert before == after
