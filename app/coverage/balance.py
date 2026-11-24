from collections import defaultdict

from .intervals import intersect, length, subtract, union


def _span_bounds(item):
    if 'left' in item:
        chain = item['left']['chain']
        lo, hi = item['left']['station_mm'], item['right']['station_mm']
    else:
        chain, lo, hi = item['chain'], item['start_mm'], item['end_mm']
    # 下行链标称里程递减，统一翻转为左闭右开的正向区间。
    return chain, min(lo, hi), max(lo, hi)


def _by_chain(intervals):
    grouped = defaultdict(list)
    for item in intervals:
        chain, lo, hi = _span_bounds(item)
        if lo != hi:
            grouped[chain].append((lo, hi))
    return {chain: union(parts) for chain, parts in grouped.items()}


def _gap_reasons(gaps, chain, lo, hi):
    """收集与缺证片段相交的断档原因；没有断档证据时回落到 NO_COVERAGE。"""
    reasons, sources = [], []
    for gap in gaps:
        same = gap['chain'] == chain or gap.get('next_chain') == chain
        if same and gap['start_mm'] < hi and gap['end_mm'] > lo:
            code = gap['reason']
            if code not in reasons:
                reasons.append(code)
            for line in gap['sources']:
                if line not in sources:
                    sources.append(line)
    if not reasons:
        reasons.append('NO_COVERAGE')
    return reasons, sources


def _merge_parts(parts):
    """同链相接且原因、证据行一致的缺证片段合并，避免把一条缺口拆成多段。"""
    merged = []
    for part in sorted(parts, key=lambda item: (item['chain'], item['start_mm'])):
        if (merged and merged[-1]['chain'] == part['chain']
                and merged[-1]['end_mm'] == part['start_mm']
                and merged[-1]['reasons'] == part['reasons']
                and merged[-1]['sources'] == part['sources']):
            merged[-1]['end_mm'] = part['end_mm']
        else:
            merged.append(dict(part))
    return merged


def balance(plan, segments, gaps):
    plan_by_chain = _by_chain(plan)
    valid_by_chain = _by_chain(segments)
    # 原始有效区间不跨断链合并到同一条轨，只在同链内保留重复巡检的长度。
    raw_by_chain = defaultdict(list)
    for item in segments:
        chain, lo, hi = _span_bounds(item)
        raw_by_chain[chain].append((lo, hi))
    tracks, missing_parts = [], []
    planned_total = mapped_total = missing_total = overlap_total = 0

    for chain in sorted(plan_by_chain):
        planned = plan_by_chain[chain]
        valid = valid_by_chain.get(chain, [])
        covered = intersect(planned, valid)
        missing = subtract(planned, covered)
        planned_mm, mapped_mm = length(planned), length(covered)
        start_mm = planned[0][0]
        tracks.append({'chain': chain, 'start_mm': start_mm, 'end_mm': planned[-1][1],
                       'planned_mm': planned_mm, 'mapped_mm': mapped_mm,
                       'mapped_parts': covered})
        for lo, hi in missing:
            reasons, sources = _gap_reasons(gaps, chain, lo, hi)
            missing_parts.append({'chain': chain, 'start_mm': lo, 'end_mm': hi,
                                  'reasons': reasons, 'sources': sources})
        # 原始有效长度按计划逐段裁剪后求和，超出并集的部分即重复巡检。
        raw_credit = sum(max(0, min(hi, p_hi) - max(lo, p_lo))
                         for lo, hi in planned for p_lo, p_hi in raw_by_chain.get(chain, []))
        planned_total += planned_mm
        mapped_total += mapped_mm
        missing_total += length(missing)
        overlap_total += raw_credit - mapped_mm

    return {'planned_mm': planned_total, 'mapped_mm': mapped_total,
            'missing_mm': missing_total, 'overlap_mm': overlap_total,
            'tracks': tracks, 'missing_parts': _merge_parts(missing_parts)}
