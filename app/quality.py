"""Display semantics only: source coverage and orthogonal notice classifications."""
from datetime import timedelta
from zoneinfo import ZoneInfo

LONG_TERM_DAYS = 30  # Desk convention, not an ENTSO-E status.

def classify_notice(row):
    kind = {'A53':'planned','A54':'forced'}.get(row.get('business'),'unknown')
    start = row.get('event_start') or row.get('start')
    end = row.get('event_end') or row.get('end')
    if not start or not end or end <= start:
        duration = 'unknown'
    elif end.astimezone(ZoneInfo('Europe/Berlin')).year >= 2100:
        duration = 'open_ended'
    elif end - start >= timedelta(days=LONG_TERM_DAYS):
        duration = 'long_term'
    else:
        duration = 'bounded'
    return {'notice_type':kind, 'duration_class':duration}


def outage_breakdown(rows, complete):
    """One capacity contribution per resource in each separate partition.

    Different classifications on overlapping notices go to mixed/unknown;
    no arbitrary assignment of the entire unit to planned or forced.
    """
    units = {}
    for row in rows:
        key = (row.get('zone'), row.get('resource_id') or (row.get('doc_mrid'), row.get('ts_mrid')))
        units.setdefault(key,[]).append(row)
    axes = {'notice_type':('planned','forced','mixed_unknown'),
            'duration_class':('bounded','long_term','open_ended','mixed_unknown')}
    result = {}
    for axis, labels in axes.items():
        buckets = {label:{'mw':0.0 if complete else None,'resources':0} for label in labels}
        for records in units.values():
            classes = {classify_notice(r)[axis] for r in records}
            category = next(iter(classes)) if len(classes)==1 else 'mixed_unknown'
            if category not in buckets:category='mixed_unknown'
            buckets[category]['resources'] += 1
            if complete:
                buckets[category]['mw'] += max(float(r.get('unavailable') or 0) for r in records)
        for bucket in buckets.values():
            if bucket['mw'] is not None:bucket['mw']=round(bucket['mw'],1)
        result[axis]=buckets
    return {**result,'long_term_days':LONG_TERM_DAYS,'resource_count':len(units),
            'note':'Separate partitions of the same selected-source total; never add the two axes. '
                   'Long-term = event duration >=30 days. End year >=2100 in Europe/Berlin is an open-ended marker, not proof of retirement. '
                   'Overlapping notices with different classifications are mixed/unknown.'}


def panel_quality(panel, data):
    series=data.get('series',{})
    def present(name):return bool(series.get(name))
    any_data=any(bool(v) for v in series.values())
    if panel=='outages':
        complete=bool(data.get('kpi',{}).get('coverage_complete'))
        any_data=any_data or bool(data.get('kpi',{}).get('reportable_events'))
    elif panel=='borders':
        complete=all(data.get('coverage',{}).get(k) for k in ('physical_total_complete','scheduled_total_complete'))
    elif panel=='renewables':
        complete=present('RES Actual') and present('RES Forecast')
    elif panel=='load':
        complete=all(present(k) for k in ('Load Actual','Load Forecast','Residual Load Actual','Residual Load Forecast','Residual Load Surprise'))
    elif panel=='balancing':
        complete=all(data.get('sources',{}).get(k,{}).get('state')=='ok' for k in ('12.3.E','A85','A86'))
        complete=complete and present('Net activation') and present('Net imbalance volume') and any(present(k) for k in ('Imbalance price','Imbalance price long','Imbalance price short'))
        any_data=any_data or any(area.get('net') for areas in data.get('activation_areas',{}).values() for area in areas.values())
    else:complete=False
    return {'state':'complete' if complete else 'partial' if any_data else 'unavailable',
            'basis':'Usable series in the selected scope; not a guarantee of freshness or complete physical-market coverage.'}
