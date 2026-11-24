"""交班前的补巡派车规划。

约束：
- 补巡从给定起点出发，车程限额按实际行驶里程计，经过已巡段同样占用限额；
- 断链两侧是两条独立线路，不能当作一条路直达；
- 缺陷旁的缺口优先，其次才按缺口长度从长到短；
- 新批次报文若补上部分缺口，原缺口作废，规划必须重算；
- 规划里程只是计划，不计入覆盖对账的实测映射。
"""
from app.coverage.intervals import length, subtract, union


def _mapped_union(coverage):
    return {track['chain']: union(track['mapped_parts']) for track in coverage['tracks']}


def _batch_union(new_batch):
    grouped = {}
    for span in new_batch['chainage']['segments']:
        left, right = span['left'], span['right']
        lo, hi = sorted((left['station_mm'], right['station_mm']))
        grouped.setdefault(left['chain'], []).append((lo, hi))
    return {chain: union(parts) for chain, parts in grouped.items()}


def refresh_gaps(stages, new_batch=None):
    """用新批次的有效区间冲减原缺口，返回重算后的缺证片段。

    新批次只合并有效覆盖，不回写原归档；原缺口中已被补上的部分直接消失，
    剩余部分保留原始断档原因与证据行。
    """
    coverage = stages['coverage']
    original = coverage['missing_parts']
    if not new_batch:
        return [dict(item) for item in original], False
    fills = _batch_union(new_batch)
    remaining = []
    for part in original:
        for lo, hi in subtract([[part['start_mm'], part['end_mm']]],
                               fills.get(part['chain'], [])):
            remaining.append(dict(part, start_mm=lo, end_mm=hi))
    return remaining, True


def _near_defect(gap, defects):
    """缺陷落在缺口内（含贴边）即视为缺陷旁缺口。"""
    for cluster in defects:
        if cluster['chain'] != gap['chain']:
            continue
        if cluster['start_mm'] <= gap['end_mm'] and cluster['end_mm'] >= gap['start_mm']:
            return True
    return False


def _is_covered(coverage, chain, lo, hi):
    if lo == hi:
        return True
    for part_lo, part_hi in _mapped_union(coverage).get(chain, []):
        if part_lo <= lo and hi <= part_hi:
            return True
    return False


def plan_dispatch(stages, start, budget_mm, *, new_batch=None):
    """在单链线性里程上贪心安排一趟补巡。

    每次从当前位置开到目标缺口最近端，补完该缺口后停在远端；
    同链移动全部计入车程，已巡段重复经过也计费。预算不足的缺口留待下一班，
    其他链因断链不可直达，直接标记为不可达。
    """
    if not isinstance(budget_mm, int) or budget_mm < 0:
        raise ValueError('BUDGET_INVALID')
    gaps, refreshed = refresh_gaps(stages, new_batch)
    defects = stages['defects']['clusters']
    chain = start['chain']
    chain_gaps = [gap for gap in gaps if gap['chain'] == chain]
    unassigned = [dict(gap, state='UNREACHABLE') for gap in gaps if gap['chain'] != chain]

    def order_key(gap):
        # 缺陷旁优先；同级再按缺口长度从长到短，长度一致时按里程稳定排序。
        return (0 if _near_defect(gap, defects) else 1,
                -(gap['end_mm'] - gap['start_mm']), gap['start_mm'])

    cursor = start['station_mm']
    remaining_budget = budget_mm
    route, legs, assigned = [], [], []
    for gap in sorted(chain_gaps, key=order_key):
        lo, hi = gap['start_mm'], gap['end_mm']
        if cursor <= lo:
            entry, far_end = lo, hi
        elif cursor >= hi:
            entry, far_end = hi, lo
        else:
            # 起点已在缺口内：先补较长的一侧，行程即该侧长度。
            entry, far_end = cursor, (hi if hi - cursor >= cursor - lo else lo)
        travel = abs(entry - cursor) + abs(far_end - entry)
        if travel > remaining_budget:
            unassigned.append(dict(gap, state='BUDGET_EXCEEDED'))
            continue
        legs.append({'from_mm': cursor, 'to_mm': entry,
                     'reused': _is_covered(stages['coverage'], chain,
                                           min(cursor, entry), max(cursor, entry))})
        route.append({'chain': chain, 'start_mm': min(entry, far_end),
                      'end_mm': max(entry, far_end), 'near_defect': _near_defect(gap, defects),
                      'reasons': list(gap['reasons']), 'sources': list(gap['sources'])})
        assigned.append(dict(gap, near_defect=_near_defect(gap, defects)))
        remaining_budget -= travel
        cursor = far_end

    return {'start': dict(start), 'budget_mm': budget_mm,
            'driven_mm': budget_mm - remaining_budget,
            'remaining_budget_mm': remaining_budget,
            'planned_mm': length((item['start_mm'], item['end_mm']) for item in route),
            'route': route, 'legs': legs, 'assigned_gaps': assigned,
            'unassigned_gaps': sorted(unassigned, key=lambda item: (item['chain'], item['start_mm'])),
            'refreshed': refreshed}
