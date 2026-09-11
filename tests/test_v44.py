import io
import json
import unittest
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import requests
from fastapi.testclient import TestClient
from app import main as m

FIX = Path(__file__).parent / 'fixtures'
T = m.parse_dt('2026-09-10T00:00Z')

def bid(process='A67', value=10, direction='A01', area='50HERTZ', product='A01', t=T, **extra):
    return dict(ts=t, process=process, activated=value, offered=999, source_area=area,
                product=product, direction=direction, mrid='1', revision='1', created='2026-09-11T00:00Z', **extra)

def zipped(*docs):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        for i,b in enumerate(docs):z.writestr(f'{i}.xml',b)
    return buf.getvalue()

class ParserRegressionTests(unittest.TestCase):
    def setUp(self):m.CACHE.clear()

    def test_live_outage_full_r3_fields(self):
        row=m._parse_outage_docs((FIX/'live_A80.xml').read_bytes(),'DE_LU','A80')[0]
        self.assertEqual((row['nominal'],row['available'],row['unavailable']),(717,640,77))
        self.assertEqual(row['plant'],'BERGKAMEN_A')
        self.assertEqual(row['resource_id'],'11WD7BERG1S--A-X')
        self.assertEqual(row['production_id'],'11WD7BERG1S--KWB')
        self.assertEqual(row['psr'],'B05')
        self.assertEqual(row['reason_code'],'A95')
        self.assertEqual(row['location'],'North Rhine-Westphalia')

    def test_live_a77_production_identity(self):
        row=m._parse_outage_docs((FIX/'live_A77.xml').read_bytes(),'DE_LU','A77')[0]
        self.assertEqual((row['nominal'],row['unavailable']),(400,400))
        self.assertEqual(row['resource_id'],'11WD2OGTI000264J')
        self.assertIsNone(row['generation_id'])

    def test_unknown_nominal_counts_event_but_suppresses_zero(self):
        b=(FIX/'live_A80.xml').read_bytes().replace(b'717.0',b'NaN')
        row=m._parse_outage_docs(b,'DE_LU','A80')[0]
        with patch.object(m,'_fetch_outage_pages',side_effect=lambda z,d,*a:([row],'ok',1) if (z,d)==('DE_LU','A80') else ([], 'no_data',0)):
            result=m.fetch_outages('2026-09-10',True)
        self.assertFalse(result['kpi']['coverage_complete'])
        self.assertIsNone(result['kpi']['unavailable_mw'])
        self.assertEqual(result['kpi']['reportable_events'],1)
        self.assertEqual(result['kpi']['unknown_capacity_events'],1)
        self.assertIsNone(result['top'][0]['unavailable_mw'])

    def test_outage_cancel_without_timeseries_removes_previous(self):
        b=(FIX/'live_A80.xml').read_bytes()
        root=m.ET.fromstring(b)
        for n in list(root):
            if m.local_name(n.tag)=='timeseries':root.remove(n)
            if m.local_name(n.tag)=='revisionnumber':n.text='2'
        status=m.ET.SubElement(root,'docStatus');m.ET.SubElement(status,'value').text='A09'
        rows=m._parse_outage_docs(zipped(b,m.ET.tostring(root)),'DE_LU','A80')
        self.assertEqual(m._latest_outage_rows(rows),[])

    def test_outage_a01_does_not_fill_missing_positions(self):
        b=(FIX/'live_A80.xml').read_bytes().replace(b'<curveType>A03',b'<curveType>A01')
        r=m._parse_outage_docs(b,'DE_LU','A80')[0]
        self.assertEqual(r['end']-r['start'],timedelta(minutes=1))

    def test_outage_parser_failure_not_ok_or_no_data(self):
        with patch.object(m,'entsoe_request',return_value=b'<broken>'):
            rows,state,_=m._fetch_outage_pages('DE_LU','A80',T,T+timedelta(days=1))
        self.assertEqual(state,'parse_error')

    def test_outage_pagination_and_truncation(self):
        b=(FIX/'live_A80.xml').read_bytes()
        with patch.object(m,'entsoe_request',side_effect=[zipped(*([b]*200)),b]) as req:
            rows,state,pages=m._fetch_outage_pages('DE_LU','A80',T,T+timedelta(days=1))
        self.assertEqual((len(rows),state,pages),(201,'ok',2))
        self.assertEqual(req.call_args_list[1].args[0]['offset'],200)
        with patch.object(m,'entsoe_request',return_value=zipped(*([b]*200))):
            self.assertEqual(m._fetch_outage_pages('DE_LU','A80',T,T+timedelta(days=1),1)[1],'truncated')

    def test_actual_zero_activation_is_not_missing(self):
        rows=m.parse_aggregated_bids((FIX/'live_A60.xml').read_bytes(),'A60')
        up,down,net=m._activation_series(rows)
        self.assertEqual((len(rows),len(net)),(192,96))
        self.assertTrue(all(v==0 for v in net.values()))
        self.assertIsNone(rows[0]['offered'])

    def test_offered_only_fallback_is_not_activation(self):
        rows=m.parse_aggregated_bids((FIX/'live_A47.xml').read_bytes(),'A47')
        self.assertTrue(any(r['offered'] is not None for r in rows))
        self.assertTrue(all(r['activated'] is None for r in rows))
        self.assertEqual(m._activation_series(rows),({},{},{}))

    def test_live_afrr_quantity_and_product(self):
        rows=m.parse_aggregated_bids((FIX/'live_A67.xml').read_bytes(),'A67')
        self.assertEqual(rows[0]['activated'],6.9265)
        self.assertEqual(rows[0]['offered'],575.009)
        self.assertEqual(rows[0]['unavailable'],0)
        self.assertEqual(rows[0]['product'],'A01')
        self.assertEqual(rows[0]['area_eic'],m.AREAS['50HERTZ'])
        self.assertEqual(len(m._activation_series(rows)[2]),96)

    def test_split_sum_beats_generic_including_zero(self):
        primary=[bid('A60',0),bid('A61',5)]
        rows=m._select_activation_rows(primary,[bid('A47',100)],('A60','A61'))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['activated'],5)
        self.assertEqual(rows[0]['selected_processes'],['A60','A61'])

    def test_generic_fills_only_gap_and_matching_product(self):
        rows=m._select_activation_rows([bid('A67',7)],[bid('A51',100),bid('A51',12,t=T+timedelta(minutes=15)),bid('A51',3,product='A02')],('A67','A68'))
        self.assertEqual(sorted(r['activated'] for r in rows),[3,7,12])

    def test_unspecified_generic_product_does_not_overlap_standard(self):
        rows=m._select_activation_rows([bid('A67',7)],[bid('A51',100,product='unspecified')],('A67','A68'))
        self.assertEqual([r['activated'] for r in rows],[7])

    def test_missing_secondary_quantity_can_use_generic(self):
        rows=m._select_activation_rows([bid('A67',None)],[bid('A51',12)],('A67','A68'))
        self.assertEqual(rows[0]['activated'],12)

    def test_same_mrid_in_four_areas_and_two_products_not_collapsed(self):
        rows=[bid(value=10,area=a,product=p,direction=d) for a in m.BALANCING_AREAS for p in ('A01','A02') for d in ('A01','A02')]
        up,down,net=m._activation_series(rows)
        self.assertEqual((up[T],down[T],net[T]),(80,80,0))

    def test_revisions_do_not_double_count(self):
        old=bid(doc_mrid='document');new={**old,'revision':'2','activated':25}
        rows=m._dedupe_bids([old,new,new])
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['activated'],25)

    def test_cancellation_without_points_supersedes_bid_document(self):
        old=bid(doc_mrid='document');cancel={**old,'revision':'2','cancelled':True,'ts':None}
        self.assertEqual(m._dedupe_bids([old,cancel]),[])

    def test_missing_down_is_not_zero(self):
        self.assertEqual(m._activation_series([bid()])[2],{})

    def test_wrong_area_and_unit_rejected(self):
        b=(FIX/'live_A67.xml').read_bytes()
        with patch.object(m,'entsoe_request',return_value=b):
            self.assertEqual(m._query_aggregated_bids('A67',T,T+timedelta(days=1),'AMPRION')[1],'parse_error')
        with self.assertRaises(ValueError):m.parse_aggregated_bids(b.replace(b'>MAW<',b'>MWH<'),'A67')

    def test_four_area_query_and_partial_coverage(self):
        def request(params,start,end):
            self.assertEqual(params['documentType'],'A24')
            self.assertIn(params['area_Domain'],[m.AREAS[a] for a in m.BALANCING_AREAS])
            if params['area_Domain']==m.AREAS['AMPRION'] or params['processType']!='A67':raise LookupError('No data')
            return (FIX/'live_A67.xml').read_bytes().replace(m.AREAS['50HERTZ'].encode(),params['area_Domain'].encode())
        start,end,_=m.day_bounds('2026-09-10')
        with patch.object(m,'entsoe_request',side_effect=request):data=m._fetch_activation_family('aFRR',start,end)
        self.assertEqual(data['state'],'partial');self.assertEqual(data['net'],{})
        self.assertEqual(len(data['areas']['50HERTZ']['net']),96)
        self.assertEqual(data['areas']['AMPRION']['state'],'no_data')

    def test_dst_23_and_25_hour_days_preserve_unique_mtu(self):
        for date,count in [('2026-03-29',92),('2026-10-25',100)]:
            start,end,_=m.day_bounds(date)
            self.assertEqual((end-start).total_seconds()/900,count)
            xml=f'<d><TimeSeries><curveType>A03</curveType><Period><timeInterval><start>{start.isoformat()}</start><end>{end.isoformat()}</end></timeInterval><resolution>PT15M</resolution><Point><position>1</position><quantity>1</quantity></Point></Period></TimeSeries></d>'.encode()
            series=m.series(m.parse_timeseries(xml))
            self.assertEqual(len(series),count)
            self.assertEqual(len({p['t'] for p in m.as_points(series)}),count)

    def test_duration_strict(self):
        self.assertEqual(m.parse_iso_duration('PT1H30M'),timedelta(minutes=90))
        self.assertEqual(m.parse_iso_duration('P1D'),timedelta(days=1))
        for invalid in ('P1M','PT0M','nonsense',None):
            with self.assertRaises(ValueError):m.parse_iso_duration(invalid)

    def test_network_exception_does_not_leak_token(self):
        with patch.object(m,'API_KEY','secret-test-token'),patch.object(m.SESSION,'get',side_effect=requests.ConnectionError('url?securityToken=secret-test-token')):
            with self.assertRaises(RuntimeError) as e:m.entsoe_request({},T,T+timedelta(minutes=15))
        self.assertNotIn('secret-test-token',str(e.exception))

    def test_request_minutes_and_http400_no_data(self):
        response=requests.Response();response.status_code=400;response._content=b'<Acknowledgement_MarketDocument><Reason><text>No matching data found</text></Reason></Acknowledgement_MarketDocument>'
        with patch.object(m,'API_KEY','test'),patch.object(m.SESSION,'get',return_value=response) as get:
            with self.assertRaises(LookupError):m.entsoe_request({},T+timedelta(minutes=15),T+timedelta(minutes=30))
        self.assertEqual(get.call_args.kwargs['params']['periodStart'],'202609100015')

    def test_residual_load_uses_consistent_day_ahead_baseline(self):
        def request(params,start,end):
            value=100 if params['processType']=='A16' else 90
            return f'<d><TimeSeries><Period><timeInterval><start>2026-09-10T00:00Z</start><end>2026-09-10T00:15Z</end></timeInterval><resolution>PT15M</resolution><Point><position>1</position><quantity>{value}</quantity></Point></Period></TimeSeries></d>'.encode()
        renewables={'series':{'RES Actual':[{'t':T.isoformat(),'v':30}],'RES Day-ahead':[{'t':T.isoformat(),'v':25}]}}
        with patch.object(m,'entsoe_request',side_effect=request),patch.object(m,'fetch_renewables',return_value=renewables):
            d=m.fetch_load('2026-09-10',True)
        self.assertEqual(d['kpi']['residual_load_mw'],70)
        self.assertEqual(d['kpi']['residual_surprise_mw'],5)

    def test_neighbor_duplicates_do_not_double_count(self):
        with patch.object(m,'_one_flow',side_effect=lambda doc,source,dest,*a:({T:100 if dest=='DE_LU' else 25},'ok')):
            result=m.fetch_borders('2026-09-10',['FR','FR'],True)
        self.assertEqual(result['kpi']['net_import_mw'],75)
        self.assertEqual(result['coverage']['expected'],1)

    def test_price_disagreement_not_averaged(self):
        self.assertEqual(m.mean_series([{'ts':T,'value':10},{'ts':T,'value':20}]),{})

    def test_a86_requires_four_areas_at_each_mtu(self):
        rows=[{'ts':t,'value':1,'source_area':area,'direction':'A01'}
              for area in m.BALANCING_AREAS for t in (T,T+timedelta(minutes=15))
              if not (area=='AMPRION' and t==T)]
        empty={'up':{},'down':{},'net':{},'state':'no_data','sources':{},'areas':{}}
        with patch.object(m,'_fetch_activation_family',return_value=empty), patch.object(m,'_query_balancing_doc_with_fallback',return_value=(rows,{a:'ok' for a in m.BALANCING_AREAS},'German control areas')):
            result=m.fetch_balancing('2026-09-10',True)
        self.assertEqual(len(result['series']['Net imbalance volume']),1)
        self.assertEqual(result['series']['Net imbalance volume'][0]['v'],4)

    def test_overlap_notices_for_same_unit_do_not_sum_capacity(self):
        r=m._parse_outage_docs((FIX/'live_A80.xml').read_bytes(),'DE_LU','A80')[0]
        rows=[r,{**r,'doc_mrid':'second-notice','unavailable':100}]
        with patch.object(m,'_fetch_outage_pages',side_effect=lambda z,d,*a:(rows,'ok',1) if (z,d)==('DE_LU','A80') else ([], 'no_data',0)):
            result=m.fetch_outages('2026-09-10',True)
        self.assertEqual(result['kpi']['unavailable_mw'],100)
        self.assertEqual(result['kpi']['reportable_events'],2)

    def test_four_areas_complete_total_no_fallback_double_count(self):
        def query(process,start,end,area):
            return [bid(process,10,area=area),bid(process,2,area=area,direction='A02')], 'ok'
        with patch.object(m,'_query_aggregated_bids',side_effect=query):
            result=m._fetch_activation_family('aFRR',T,T+timedelta(minutes=15))
        self.assertEqual(result['net'][T],64)
        self.assertEqual(result['state'],'ok')

    def test_fallback_missing_split_mtu_replaces_whole_group(self):
        t1=T+timedelta(minutes=15)
        primary=[bid('A60',10),bid('A61',5),bid('A60',7,t=t1)]
        rows=m._select_activation_rows(primary,[bid('A47',20,t=t1)],('A60','A61'))
        self.assertEqual({r['ts']:r['activated'] for r in rows},{T:15,t1:20})


class HttpSmokeTests(unittest.TestCase):
    def setUp(self):m.CACHE.clear();self.client=TestClient(m.app)
    def test_health_html_and_static_assets(self):
        self.assertEqual(self.client.get('/health').json()['version'],'4.4.0')
        self.assertIn('Desk v4.4',self.client.get('/').text)
        for asset in ('style.css','plotly.min.js'):
            self.assertEqual(self.client.get('/static/'+asset).status_code,200)
    def test_all_five_api_routes_serialize(self):
        for route in ('renewables','load','borders','outages','balancing'):
            with patch.object(m,'fetch_'+route,return_value={'series':{},'kpi':{'value':None}}):
                r=self.client.get('/api/'+route+'?day=2026-09-10')
                self.assertEqual(r.status_code,200);self.assertIsNone(r.json()['kpi']['value'])
    def test_invalid_date_and_upstream_error(self):
        self.assertEqual(self.client.get('/api/outages?day=not-a-date').status_code,422)
        with patch.object(m,'fetch_outages',side_effect=RuntimeError('upstream failed')):
            self.assertEqual(self.client.get('/api/outages').status_code,502)
    def test_optional_auth_and_health_bypass(self):
        with patch.object(m,'AUTH_ENABLED',True),patch.object(m,'DASHBOARD_USERNAME','desk'),patch.object(m,'DASHBOARD_PASSWORD','test'):
            self.assertEqual(self.client.get('/').status_code,401)
            self.assertEqual(self.client.get('/health').status_code,200)
            self.assertEqual(self.client.get('/',auth=('desk','test')).status_code,200)

if __name__=='__main__':unittest.main()
