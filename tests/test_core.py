import io
import unittest
import zipfile
from datetime import timedelta
from unittest.mock import patch

from app.main import (
    CACHE,
    add_series_complete,
    change_windows,
    fetch_balancing,
    fetch_renewables,
    parse_iso_duration,
    parse_timeseries,
)

XML = b'''<?xml version="1.0"?><GL_MarketDocument xmlns="urn:test"><TimeSeries><MktPSRType><psrType>B16</psrType></MktPSRType><Period><timeInterval><start>2026-08-28T00:00Z</start><end>2026-08-28T01:00Z</end></timeInterval><resolution>PT15M</resolution><Point><position>1</position><quantity>100</quantity></Point><Point><position>2</position><quantity>120</quantity></Point></Period></TimeSeries></GL_MarketDocument>'''


def generation_xml(solar: float, offshore: float, onshore: float) -> bytes:
    series = []
    for psr, value in (("B16", solar), ("B18", offshore), ("B19", onshore)):
        series.append(f'''<TimeSeries><MktPSRType><psrType>{psr}</psrType></MktPSRType><Period><timeInterval><start>2026-08-27T22:00Z</start><end>2026-08-27T22:15Z</end></timeInterval><resolution>PT15M</resolution><Point><position>1</position><quantity>{value}</quantity></Point></Period></TimeSeries>''')
    return ('<?xml version="1.0"?><GL_MarketDocument xmlns="urn:test">' + ''.join(series) + '</GL_MarketDocument>').encode()


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

    def test_renewables_keeps_current_intraday_and_day_ahead_separate(self):
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
        self.assertIn('RES Forecast Revision', data['series'])
        self.assertIn('changes', data['kpi'])
        self.assertIn('actual_through', data['freshness'])

    def test_system_stress_prefers_a86_volume(self):
        # Minimal synthetic rows returned at the control-area helper layer.
        trows = parse_timeseries(XML)
        t0 = trows[0]['ts']

        def fake_query(doc, area, start, end, extra=None):
            if doc == 'A83':
                business = (extra or {}).get('businessType')
                return ([{'ts': t0, 'value': 50.0, 'business': business, 'direction': 'A01', 'category': None}], 'ok')
            if doc == 'A86' and area == '50HERTZ':
                return ([{'ts': t0, 'value': 120.0, 'business': None, 'direction': 'A01', 'category': None}], 'ok')
            if doc == 'A85' and area == '50HERTZ':
                return ([{'ts': t0, 'value': 88.0, 'business': None, 'direction': None, 'category': None}], 'ok')
            return ([], 'no_data')

        with patch('app.main._query_control_area_document', side_effect=fake_query):
            data = fetch_balancing('2026-08-28', force=True)

        self.assertEqual(data['kpi']['basis'], 'A86 total imbalance volume')
        self.assertEqual(data['kpi']['system_stress_value'], 120.0)
        self.assertEqual(data['kpi']['system_stress_unit'], 'MWh')
        self.assertEqual(data['kpi']['imbalance_volume_mwh'], 120.0)
        self.assertEqual(data['kpi']['imbalance_price_eur_mwh'], 88.0)
        self.assertEqual(data['sources']['A86']['state'], 'ok')
        self.assertEqual(data['sources']['A85']['state'], 'ok')


if __name__ == '__main__':
    unittest.main()
