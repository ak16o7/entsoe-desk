import unittest
from datetime import timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import main as m
from app.quality import classify_notice,outage_breakdown,panel_quality

T=m.parse_dt('2026-09-10T00:00Z')
def notice(**overrides):
    return dict({'zone':'DE_LU','resource_id':'unit','doc_mrid':'doc','ts_mrid':'1','business':'A53',
                 'start':T,'end':T+timedelta(days=1),'event_start':T,'event_end':T+timedelta(days=1),'unavailable':100},**overrides)

class NoticeSemanticsTests(unittest.TestCase):
    def test_type_and_duration_are_independent(self):
        r=notice(business='A54',event_end=T+timedelta(days=45))
        self.assertEqual(classify_notice(r),{'notice_type':'forced','duration_class':'long_term'})
    def test_long_term_boundary(self):
        self.assertEqual(classify_notice(notice(event_end=T+timedelta(days=30)))['duration_class'],'long_term')
        self.assertEqual(classify_notice(notice(event_end=T+timedelta(days=30,seconds=-1)))['duration_class'],'bounded')
    def test_full_event_not_available_segment_classifies_duration(self):
        r=notice(end=T+timedelta(minutes=15),event_start=T-timedelta(days=90))
        self.assertEqual(classify_notice(r)['duration_class'],'long_term')
    def test_2100_local_marker_and_unknown_type(self):
        r=notice(business='future-code',event_end=m.parse_dt('2099-12-31T23:00Z'))
        self.assertEqual(classify_notice(r),{'notice_type':'unknown','duration_class':'open_ended'})
    def test_bad_interval_is_unknown(self):
        self.assertEqual(classify_notice(notice(event_end=T))['duration_class'],'unknown')
    def test_breakdowns_each_reconcile_to_deduplicated_total(self):
        rows=[notice(),notice(resource_id='b',business='A54',event_end=T+timedelta(days=60),unavailable=200),notice(resource_id='c',event_end=m.parse_dt('2099-12-31T23:00Z'),unavailable=300)]
        b=outage_breakdown(rows,True)
        for axis in ('notice_type','duration_class'):
            self.assertEqual(sum(v['mw'] for v in b[axis].values()),600)
        self.assertEqual(b['notice_type']['forced']['mw'],200)
        self.assertEqual(b['duration_class']['long_term']['mw'],200)
    def test_overlap_different_types_is_mixed_not_double_counted(self):
        b=outage_breakdown([notice(),notice(business='A54',doc_mrid='two',unavailable=50)],True)
        self.assertEqual(b['notice_type']['mixed_unknown']['mw'],100)
        self.assertEqual(b['notice_type']['planned']['mw'],0)
        self.assertEqual(b['resource_count'],1)
    def test_overlap_durations_mixed(self):
        b=outage_breakdown([notice(),notice(event_end=T+timedelta(days=31))],True)
        self.assertEqual(b['duration_class']['mixed_unknown']['mw'],100)
    def test_unknown_capacity_suppresses_every_breakdown_number(self):
        b=outage_breakdown([notice(unavailable=None)],False)
        for axis in ('notice_type','duration_class'):
            self.assertTrue(all(v['mw'] is None for v in b[axis].values()))
        self.assertEqual(b['notice_type']['planned']['resources'],1)
    def test_no_notices_explicit_complete_zero(self):
        self.assertEqual(outage_breakdown([],True)['notice_type']['planned']['mw'],0)

class CoverageTests(unittest.TestCase):
    def test_balancing_partial_despite_http_success(self):
        d={'sources':{'12.3.E':{'state':'partial'},'A85':{'state':'ok'},'A86':{'state':'ok'}},'series':{'Net imbalance volume':[1]}}
        self.assertEqual(panel_quality('balancing',d)['state'],'partial')
    def test_area_curves_without_germany_total_are_partial(self):
        self.assertEqual(panel_quality('balancing',{'activation_areas':{'aFRR':{'50HERTZ':{'net':[1]}}}})['state'],'partial')
    def test_empty_success_is_unavailable(self):
        for panel in ('renewables','load','borders','outages','balancing'):
            self.assertEqual(panel_quality(panel,{'series':{}})['state'],'unavailable')
    def test_complete_zero_outages_are_complete(self):
        self.assertEqual(panel_quality('outages',{'kpi':{'coverage_complete':True,'reportable_events':0}})['state'],'complete')
    def test_borders_missing_schedule_is_partial(self):
        self.assertEqual(panel_quality('borders',{'coverage':{'physical_total_complete':True,'scheduled_total_complete':False},'series':{'Net Physical Import':[1]}})['state'],'partial')
    def test_complete_renewables(self):
        self.assertEqual(panel_quality('renewables',{'series':{'RES Actual':[1],'RES Forecast':[1]}})['state'],'complete')
    def test_http_exposes_quality_and_preserves_payload(self):
        with patch.object(m,'fetch_balancing',return_value={'series':{'Net imbalance volume':[1]},'kpi':{}}):
            r=TestClient(m.app).get('/api/balancing')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['quality']['state'],'partial')
        self.assertEqual(r.json()['series']['Net imbalance volume'],[1])
    def test_full_notice_list_is_not_limited_to_top_twelve(self):
        rows=[dict(notice(resource_id=f'unit{i}',doc_mrid=f'doc{i}'),plant=f'Unit{i}',psr='B05',document_type='A80',revision='1',created=T.isoformat()) for i in range(20)]
        with patch.object(m,'_fetch_outage_pages',side_effect=lambda z,d,*a:(rows,'ok',1) if (z,d)==('DE_LU','A80') else ([], 'no_data',0)):
            d=m.fetch_outages('2026-09-10',True)
        self.assertEqual(len(d['top']),12);self.assertEqual(len(d['notices']),20)
        self.assertEqual(d['breakdown']['notice_type']['planned']['mw'],2000)
        self.assertTrue(all(r['notice_type']=='planned' for r in d['notices']))

if __name__=='__main__':unittest.main()
