import pytest

from app.dispatch.planner import plan_dispatch, refresh_gaps


def make_stages(gaps, defects, planned=None, covered=None):
    """用缺口和缺陷群构造规划器所需的最小阶段数据。"""
    chains = {gap['chain'] for gap in gaps}
    if planned is None:
        planned = {chain: (min(g['start_mm'] for g in gaps if g['chain'] == chain),
                           max(g['end_mm'] for g in gaps if g['chain'] == chain))
                   for chain in chains}
    covered = covered or {}
    tracks = [{'chain': chain, 'start_mm': lo, 'end_mm': hi,
               'planned_mm': hi - lo, 'mapped_mm': 0,
               'mapped_parts': covered.get(chain, [])}
              for chain, (lo, hi) in planned.items()]
    missing = [dict(gap, reasons=list(gap.get('reasons', ['NO_COVERAGE'])),
                    sources=list(gap.get('sources', []))) for gap in gaps]
    coverage = {'tracks': tracks, 'missing_parts': missing}
    clusters = [{'chain': d[0], 'kind': d[1], 'start_mm': d[2], 'end_mm': d[3],
                 'members': [], 'sources': []} for d in defects]
    return {'coverage': coverage, 'defects': {'clusters': clusters}}


def gap(chain, lo, hi, reasons=None):
    return {'chain': chain, 'start_mm': lo, 'end_mm': hi,
            'reasons': reasons or ['NO_COVERAGE'], 'sources': []}


def test_short_gap_next_to_defect_jumps_the_longest():
    # 长缺口 200m，短缺口 50m 但贴着缺陷；先补短缺口。
    stages = make_stages(
        [gap('UP', 1000, 1200), gap('UP', 1500, 1550)],
        [('UP', '裂纹', 1550, 1550)])
    plan = plan_dispatch(stages, {'chain': 'UP', 'station_mm': 0}, 10000)
    first = plan['route'][0]
    assert (first['start_mm'], first['end_mm'], first['near_defect']) == (1500, 1550, True)
    assert plan['assigned_gaps'][0]['near_defect'] is True


def test_pure_length_tiebreak_without_defect():
    stages = make_stages([gap('UP', 1000, 1100), gap('UP', 1200, 1500)], [])
    plan = plan_dispatch(stages, {'chain': 'UP', 'station_mm': 0}, 10000)
    assert [(r['start_mm'], r['end_mm']) for r in plan['route']] == [(1200, 1500), (1000, 1100)]


def test_travel_over_covered_track_consumes_budget():
    # 起点在 0，先穿过 1000m 已巡段才到缺口；预算只够单程缺口 100m 时无法覆盖。
    stages = make_stages([gap('UP', 1000, 1100)], [],
                         planned={'UP': (0, 1100)}, covered={'UP': [[0, 1000]]})
    tight = plan_dispatch(stages, {'chain': 'UP', 'station_mm': 0}, 1050)
    assert tight['route'] == []
    assert tight['unassigned_gaps'][0]['state'] == 'BUDGET_EXCEEDED'
    fit = plan_dispatch(stages, {'chain': 'UP', 'station_mm': 0}, 1100)
    assert fit['driven_mm'] == 1100 and fit['remaining_budget_mm'] == 0
    assert fit['legs'][0]['reused'] is True


def test_break_means_other_chain_is_unreachable():
    stages = make_stages([gap('UP-A', 1000, 1200), gap('UP-B', 2000, 2100)], [])
    plan = plan_dispatch(stages, {'chain': 'UP-A', 'station_mm': 1000}, 100000)
    assert [r['chain'] for r in plan['route']] == ['UP-A']
    assert plan['unassigned_gaps'] == [
        dict(gap('UP-B', 2000, 2100), state='UNREACHABLE')]


def test_invalid_budget_rejected():
    stages = make_stages([gap('UP', 1000, 1100)], [])
    with pytest.raises(ValueError):
        plan_dispatch(stages, {'chain': 'UP', 'station_mm': 0}, -1)


def test_new_batch_clears_covered_part_and_replans():
    stages = make_stages([gap('UP', 1000, 1200), gap('UP', 1500, 1550)],
                         [('UP', '裂纹', 1550, 1550)])
    # 新批次的有效双基点区间覆盖 1500–1550，缺陷旁短缺口被补上。
    batch = {'chainage': {'segments': [
        {'left': {'chain': 'UP', 'station_mm': 1500},
         'right': {'chain': 'UP', 'station_mm': 1550}}], 'gaps': []}}
    remaining, refreshed = refresh_gaps(stages, batch)
    assert refreshed is True
    assert [(g['start_mm'], g['end_mm']) for g in remaining] == [(1000, 1200)]
    plan = plan_dispatch(stages, {'chain': 'UP', 'station_mm': 0}, 10000, new_batch=batch)
    assert plan['refreshed'] is True
    assert [(r['start_mm'], r['end_mm']) for r in plan['route']] == [(1000, 1200)]
    # 规划里程不回写覆盖对账。
    assert stages['coverage']['missing_parts'][0]['end_mm'] == 1200


def test_partial_fill_splits_gap_keeps_evidence():
    stages = make_stages([gap('UP', 1000, 1200, reasons=['SIGNAL_GAP'])], [])
    batch = {'chainage': {'segments': [
        {'left': {'chain': 'UP', 'station_mm': 1100},
         'right': {'chain': 'UP', 'station_mm': 1150}}], 'gaps': []}}
    remaining, _ = refresh_gaps(stages, batch)
    assert [(g['start_mm'], g['end_mm']) for g in remaining] == [(1000, 1100), (1150, 1200)]
    assert all(g['reasons'] == ['SIGNAL_GAP'] for g in remaining)
