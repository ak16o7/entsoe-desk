import io
import inspect
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.main import (
    BERLIN,
    CACHE,
    DEFAULT_NEIGHBORS,
    _directional_net,
    _latest_outage_rows,
    fetch_balancing,
    fetch_borders,
    fetch_outages,
    fetch_renewables,
    add_series_complete,
    api_borders,
    api_outages,
    change_windows,
    parse_aggregated_bids,
    parse_iso_duration,
    parse_timeseries,
)

XML = b'''<?xml version="1.0"?><GL_MarketDocument xmlns="urn:test"><TimeSeries><MktPSRType><psrType>B16</psrType></MktPSRType><Period><timeInterval><start>2026-08-28T00:00Z</start><end>2026-08-28T01:00Z</end></timeInterval><resolution>PT15M</resolution><Point><position>1</position><quantity>100</quantity></Point><Point><position>2</position><quantity>120</quantity></Point></Period></TimeSeries></GL_MarketDocument>'''

A03_XML = b'''<?xml version="1.0"?><GL_MarketDocument xmlns="urn:test"><revisionNumber>2</revisionNumber><createdDateTime>2026-08-28T00:05Z</createdDateTime><TimeSeries><curveType>A03</curveType><Period><timeInterval><start>2026-08-28T00:00Z</start><end>2026-08-28T01:00Z</end></timeInterval><resolution>PT15M</resolution><Point><position>1</position><quantity>100</quantity></Point><Point><position>3</position><quantity>200</quantity></Point></Period></TimeSeries></GL_MarketDocument>'''

A24_XML = b'''<?xml version="1.0"?><GL_MarketDocument xmlns="urn:test"><revisionNumber>1</revisionNumber><createdDateTime>2026-08-28T12:01Z</createdDateTime><TimeSeries><mRID>x</mRID><flowDirection.direction>A01</flowDirection.direction><curveType>A03</curveType><Period><timeInterval><start>2026-08-28T12:00Z</start><end>2026-08-28T12:30Z</end></timeInterval><resolution>PT15M</resolution><Point><position>1</position><quantity>300</quantity><secondaryQuantity>120</secondaryQuantity></Point></Period></TimeSeries></GL_MarketDocument>'''


def generation_xml(solar: float, offshore: float, onshore: float) -> bytes:
    parts = []
    for psr, value in (("B16", solar), ("B18", offshore), ("B19", onshore)):
        parts.append(f'''<TimeSeries><MktPSRType><psrType>{psr}</psrType></MktPSRType><Period><timeInterval><start>2026-08-27T22:00Z</start><end>2026-08-27T22:15Z</end></timeInterval><resolution>PT15M</resolution><Point><position>1</position><quantity>{value}</quantity></Point></Period></TimeSeries>''')
    return ('<?xml version="1.0"?><GL_MarketDocument xmlns="urn:test">' + ''.join(parts) + '</GL_MarketDocument>').encode()


def imbalance_price_zip() -> bytes:
    xml = b'''<?xml version="1.0"?><GL_MarketDocument xmlns="urn:test"><TimeSeries><Period><timeInterval><start>2026-08-28T12:00Z</start><end>2026-08-28T12:30Z</end></timeInterval><resolution>PT15M</resolution><Point><position>1</position><imbalance_Price.amount>53.37</imbalance_Price.amount><imbalance_Price.category>A04</imbalance_Price.category></Point><Point><position>2</position><imbalance_Price.amount>61.22</imbalance_Price.amount><imbalance_Price.category>A05</imbalance_Price.category></Point></Period></TimeSeries></GL_MarketDocument>'''
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('prices.xml', xml)
    return buf.getvalue()


class CoreTests(unittest.TestCase):
    def setUp(self):
        CACHE.clear()

    def test_duration(self):
        self.assertEqual(parse_iso_duration('PT15M').total_seconds(), 900)

    def test_timeseries(self):
        rows = parse_timeseries(XML)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['psr'], 'B16')
        self.assertEqual(rows[1]['value'], 120.0)
        self.assertEqual((rows[1]['ts'] - rows[0]['ts']).total_seconds(), 900)

    def test_r3_a03_blocks_are_forward_filled(self):
        rows = parse_timeseries(A03_XML)
        self.assertEqual([r['value'] for r in rows], [100.0, 100.0, 200.0, 200.0])
        self.assertTrue(all(r['curve_type'] == 'A03' for r in rows))

    def test_imbalance_price_zip_and_category(self):
        rows = parse_timeseries(imbalance_price_zip())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['value'], 53.37)
        self.assertEqual(rows[0]['category'], 'A04')
        self.assertEqual(rows[1]['category'], 'A05')

    def test_complete_sum_requires_every_component(self):
        rows = parse_timeseries(XML)
        a = {r['ts']: r['value'] for r in rows}
        b = {rows[0]['ts']: 10.0}
        total = add_series_complete(a, b)
        self.assertEqual(len(total), 1)
        self.assertEqual(next(iter(total.values())), 110.0)

    def test_change_windows(self):
        rows = parse_timeseries(XML)
        base = rows[0]['ts']
        s = {base + timedelta(minutes=15*i): float(100+i*10) for i in range(5)}
        c = change_windows(s, base + timedelta(hours=1))
        self.assertEqual(c['d15_mw'], 10.0)
        self.assertEqual(c['d30_mw'], 20.0)
        self.assertEqual(c['d60_mw'], 40.0)

    def test_renewables_keeps_forecast_processes_separate(self):
        actual = generation_xml(100, 20, 80)
        day_ahead = generation_xml(90, 18, 75)
        intraday = generation_xml(95, 19, 78)
        current = generation_xml(98, 21, 79)

        def fake_request(params, start, end):
            if params['documentType'] == 'A75':
                return actual
            return {'A01': day_ahead, 'A40': intraday, 'A18': current}[params['processType']]

        with patch('app.main.entsoe_request', side_effect=fake_request):
            data = fetch_renewables('2026-08-28', force=True)

        self.assertEqual(data['series']['Solar Actual'][0]['v'], 100.0)
        self.assertEqual(data['series']['Solar Current'][0]['v'], 98.0)
        self.assertEqual(data['series']['Solar Intraday'][0]['v'], 95.0)
        self.assertEqual(data['series']['Solar Day-ahead'][0]['v'], 90.0)
        self.assertEqual(data['series']['RES Actual'][0]['v'], 200.0)
        self.assertEqual(data['series']['RES Current'][0]['v'], 198.0)
        self.assertEqual(data['series']['RES Intraday'][0]['v'], 192.0)
        self.assertEqual(data['series']['RES Day-ahead'][0]['v'], 183.0)
        self.assertEqual(data['kpi']['forecast_basis'], 'current')
        self.assertEqual(data['scope']['type'], 'Member State')
        self.assertIn('08:00', data['forecast_definitions']['intraday'])
        self.assertIn('18:00', data['forecast_definitions']['day_ahead'])

    def test_directional_net_does_not_zero_fill_gaps(self):
        t0 = datetime(2026, 8, 28, 12, 0, tzinfo=BERLIN)
        t1 = t0 + timedelta(minutes=15)
        net, state = _directional_net({t0: 100, t1: 110}, 'ok', {t0: 30}, 'ok')
        self.assertEqual(state, 'ok')
        self.assertEqual(net, {t0: 70})
        one_way, state = _directional_net({t0: 100, t1: 110}, 'ok', {}, 'no_data')
        self.assertEqual(state, 'single_direction')
        self.assertEqual(one_way[t1], 110)
        failed, state = _directional_net({t0: 100}, 'ok', {}, 'error')
        self.assertEqual(failed, {})
        self.assertEqual(state, 'error')

    def test_border_total_is_suppressed_when_one_selected_border_is_missing(self):
        t = datetime(2026, 8, 28, 12, 0, tzinfo=BERLIN)

        def fake_one_flow(doc_type, source, dest, start, end, contract=None):
            if doc_type == 'A11' and (source == 'PL' or dest == 'PL'):
                return {}, 'error'
            # Different import/export values keep the series visibly nonzero.
            return ({t: 100.0} if dest == 'DE_LU' else {t: 25.0}), 'ok'

        with patch('app.main._one_flow', side_effect=fake_one_flow):
            data = fetch_borders('2026-08-28', list(DEFAULT_NEIGHBORS), force=True)
        self.assertFalse(data['coverage']['physical_total_complete'])
        self.assertEqual(data['series']['Net Physical Import'], [])
        self.assertIsNone(data['kpi']['net_import_mw'])
        self.assertEqual(data['coverage']['physical_series'], len(DEFAULT_NEIGHBORS)-1)

    def test_outage_latest_cancelled_revision_is_removed(self):
        t0 = datetime(2026, 8, 28, 0, 0, tzinfo=BERLIN)
        base = dict(zone='DE_LU', document_type='A80', doc_mrid='doc1', ts_mrid='ts1', resource_id='unit1', start=t0, end=t0+timedelta(hours=1), unavailable=100.0, plant='Unit 1', psr=None, business=None)
        rows = [
            {**base, 'revision': '1', 'created': '2026-08-27T10:00Z', 'docstatus': 'A05'},
            {**base, 'revision': '2', 'created': '2026-08-27T11:00Z', 'docstatus': 'A09'},
        ]
        self.assertEqual(_latest_outage_rows(rows), [])

    def test_outages_use_a80_without_adding_a77_and_count_unique_events(self):
        start = datetime(2026, 8, 28, 0, 0, tzinfo=BERLIN)
        end = start + timedelta(days=1)
        common = dict(zone='DE_LU', document_type='A80', doc_mrid='doc1', ts_mrid='ts1', resource_id='unit1', start=start, end=end, plant='Unit 1', psr=None, business=None, revision='1', created='2026-08-27T10:00Z', docstatus='A05')
        a80 = [{**common, 'unavailable': 100.0}, {**common, 'unavailable': 120.0}]
        a77 = [{**common, 'document_type':'A77', 'doc_mrid':'prod1', 'resource_id':'plant1', 'unavailable':500.0}]

        def fake_pages(zone, document_type, _start, _end, max_pages=25):
            if zone == 'DE_LU' and document_type == 'A80': return a80, 'ok', 1
            if zone == 'DE_LU' and document_type == 'A77': return a77, 'ok', 1
            return [], 'no_data', 0

        with patch('app.main._fetch_outage_pages', side_effect=fake_pages):
            data = fetch_outages('2026-08-28', force=True)
        self.assertTrue(data['kpi']['coverage_complete'])
        self.assertEqual(data['selected_source']['DE_LU'], 'A80')
        self.assertEqual(data['kpi']['unavailable_mw'], 120.0)
        self.assertEqual(data['kpi']['reportable_events'], 1)
        self.assertEqual(data['kpi']['active_events'], 1)

    def test_a24_aggregated_bids_expands_blocks(self):
        rows = parse_aggregated_bids(A24_XML, 'A51')
        self.assertEqual(len(rows), 2)
        self.assertEqual([r['activated'] for r in rows], [120.0, 120.0])
        self.assertEqual(rows[0]['direction'], 'A01')
        self.assertEqual(rows[0]['process'], 'A51')

    def test_balancing_headline_is_a86_only_and_12_3_e_is_separate(self):
        t0 = datetime(2026, 8, 28, 12, 0, tzinfo=BERLIN)
        afrr = [{'ts':t0, 'direction':'A01', 'process':'A51', 'mrid':'a', 'offered':200.0, 'activated':50.0, 'revision':'1', 'created':'2026-08-28T12:01Z'}]
        mfrr = [{'ts':t0, 'direction':'A02', 'process':'A47', 'mrid':'m', 'offered':100.0, 'activated':20.0, 'revision':'1', 'created':'2026-08-28T12:01Z'}]
        volume = [{'ts':t0, 'value':120.0, 'business':None, 'direction':'A01', 'category':None, 'source_area':'50HERTZ', 'revision':'1', 'created':'2026-08-28T12:01Z'}]
        price = [{'ts':t0, 'value':88.0, 'business':None, 'direction':None, 'category':None, 'source_area':'50HERTZ', 'revision':'1', 'created':'2026-08-28T12:01Z'}]

        def fake_bids(process, start, end, area):
            if process not in ('A51', 'A47'): return [], 'no_data'
            source = afrr if process == 'A51' else mfrr
            r = {**source[0], 'source_area':area, 'activated': source[0]['activated']/4}
            zero = {**r, 'direction':'A02' if r['direction']=='A01' else 'A01', 'activated':0.0}
            return [r, zero], 'ok' 
        def fake_doc(doc, start, end):
            return (price, {'DE':'ok'}, 'DE') if doc == 'A85' else (volume, {'DE':'ok'}, 'DE')

        with patch('app.main._query_aggregated_bids', side_effect=fake_bids), patch('app.main._query_balancing_doc_with_fallback', side_effect=fake_doc):
            data = fetch_balancing('2026-08-28', force=True)
        self.assertEqual(data['kpi']['basis'], 'A86 total imbalance volume')
        self.assertEqual(data['kpi']['imbalance_volume_mwh'], 120.0)
        self.assertEqual(data['kpi']['imbalance_state'], 'surplus')
        self.assertEqual(data['kpi']['net_activation_mw'], 30.0)
        self.assertNotIn('system_stress_value', data['kpi'])
        self.assertEqual(data['sources']['12.3.E']['state'], 'ok')
        self.assertEqual(data['sources']['A86']['state'], 'ok')

    def test_partial_control_area_a86_is_not_presented_as_germany_total(self):
        t0 = datetime(2026, 8, 28, 12, 0, tzinfo=BERLIN)
        volume = [{'ts':t0, 'value':120.0, 'business':None, 'direction':'A01', 'category':None, 'source_area':'50HERTZ', 'revision':'1', 'created':'2026-08-28T12:01Z'}]

        def fake_bids(process, start, end, area):
            return [], 'no_data'
        def fake_doc(doc, start, end):
            if doc == 'A86':
                return volume, {'50HERTZ':'ok', 'AMPRION':'no_data', 'TENNET_DE':'no_data', 'TRANSNETBW':'no_data'}, 'German control areas (partial)'
            return [], {'50HERTZ':'no_data'}, 'none'

        with patch('app.main._query_aggregated_bids', side_effect=fake_bids), patch('app.main._query_balancing_doc_with_fallback', side_effect=fake_doc):
            data = fetch_balancing('2026-08-28', force=True)
        self.assertIsNone(data['kpi']['imbalance_volume_mwh'])
        self.assertEqual(data['sources']['A86']['state'], 'partial')
        self.assertEqual(data['series']['Net imbalance volume'], [])

    def test_public_api_does_not_expose_force_parameter_or_cache_clear_ui(self):
        self.assertNotIn('force', inspect.signature(api_borders).parameters)
        self.assertNotIn('force', inspect.signature(api_outages).parameters)
        html = Path('app/templates/index.html').read_text(encoding='utf-8')
        self.assertNotIn('force=true', html)
        self.assertNotIn('/api/cache/clear', html)
        self.assertIn('12.3.E', html)
        self.assertNotIn('A83 · Net activation', html)


if __name__ == '__main__':
    unittest.main()
