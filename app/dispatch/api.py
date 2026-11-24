from collections import OrderedDict

from flask import Blueprint, current_app, jsonify, request

from app.archive.save import retrieve
from app.dispatch.planner import plan_dispatch
from app.errors import TrackError
from app.manifest import canonical, digest
from app.pipeline import inspect

dispatch_api = Blueprint('track_dispatch', __name__)


class DispatchLedger:
    """进程内派车台账：同一请求指纹重放原计划，重试不会重复派车。"""

    def __init__(self, capacity=128):
        self._capacity = capacity
        self._plans = OrderedDict()

    def key(self, payload):
        return digest(canonical(payload))

    def remember(self, key, plan):
        self._plans[key] = plan
        self._plans.move_to_end(key)
        while len(self._plans) > self._capacity:
            self._plans.popitem(last=False)

    def get(self, key):
        plan = self._plans.get(key)
        if plan is not None:
            self._plans.move_to_end(key)
        return plan


def _load_batch(raw):
    # 新批次走完整流水线，只取其有效双基点区间参与缺口重算。
    return inspect(raw, 'coverage')


def _parse_start(body, coverage):
    start = body.get('start')
    if not isinstance(start, dict) or set(start) != {'chain', 'station_mm'}:
        raise TrackError('BAD_START')
    chain = start['chain']
    station = start['station_mm']
    if not isinstance(chain, str) or not isinstance(station, int) or isinstance(station, bool):
        raise TrackError('BAD_START')
    for track in coverage['tracks']:
        if track['chain'] == chain and track['start_mm'] <= station <= track['end_mm']:
            return {'chain': chain, 'station_mm': station}
    raise TrackError('BAD_START')


def _parse_budget(body):
    budget = body.get('budget_mm')
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 0:
        raise TrackError('BAD_BUDGET')
    return budget


@dispatch_api.post('/api/runs/<run_id>/dispatch')
def dispatch(run_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - {'start', 'budget_mm', 'batch_csv'}:
        raise TrackError('BAD_BODY')
    snapshot = retrieve(current_app.track_archive, run_id)
    stages = snapshot['stages']
    start = _parse_start(body, stages['coverage'])
    budget = _parse_budget(body)
    batch_raw = None
    new_batch = None
    if 'batch_csv' in body:
        if not isinstance(body['batch_csv'], str):
            raise TrackError('BAD_BODY')
        batch_raw = body['batch_csv'].encode('utf-8')
        new_batch = _load_batch(batch_raw)

    ledger = current_app.dispatch_ledger
    identity = {'run_id': run_id, 'start': start, 'budget_mm': budget,
                'batch_sha256': digest(batch_raw) if batch_raw is not None else None}
    key = ledger.key(identity)
    cached = ledger.get(key)
    if cached is not None:
        return jsonify(dict(cached, reused=True))

    plan = plan_dispatch(stages, start, budget, new_batch=new_batch)
    plan.update({'run_id': run_id, 'dispatch_id': key})
    ledger.remember(key, plan)
    return jsonify(plan), 201
