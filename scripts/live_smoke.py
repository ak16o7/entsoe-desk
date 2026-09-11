"""Reproducible live audit. Credentials are read locally, never written to output.
Run: python scripts/live_smoke.py --env-file /path/to/.env --day 2026-09-10 --output audit.json
"""
import argparse
import json
import sys
import time
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from app import main as m


def reference_points(body, field='quantity', psr=None, category=None):
    """Independent XML expansion for the published fixed-duration test day."""
    result={}
    for xml in m.xml_documents(body):
        root=ET.fromstring(xml)
        for ts in root.findall('.//{*}TimeSeries'):
            if psr and ts.findtext('.//{*}psrType') != psr:continue
            if psr and ts.find('{*}outBiddingZone_Domain.mRID') is not None:continue
            for period in ts.findall('{*}Period'):
                start=datetime.fromisoformat(period.findtext('{*}timeInterval/{*}start').replace('Z','+00:00'))
                end=datetime.fromisoformat(period.findtext('{*}timeInterval/{*}end').replace('Z','+00:00'))
                res=period.findtext('{*}resolution')
                seconds={'PT15M':900,'PT30M':1800,'PT60M':3600,'PT1H':3600,'PT1M':60}[res]
                points=sorted(period.findall('{*}Point'),key=lambda p:int(p.findtext('{*}position')))
                for i,p in enumerate(points):
                    pos=int(p.findtext('{*}position'));raw=p.findtext('{*}'+field)
                    if raw is None or (category and p.findtext('{*}imbalance_Price.category')!=category):continue
                    begin=start+timedelta(seconds=seconds*(pos-1))
                    stop=begin+timedelta(seconds=seconds)
                    if ts.findtext('{*}curveType')=='A03':
                        stop=start+timedelta(seconds=seconds*(int(points[i+1].findtext('{*}position'))-1)) if i+1<len(points) else end
                    direction=ts.findtext('{*}flowDirection.direction')
                    t=begin
                    while t<min(stop,end):
                        result[(t,direction)]=float(raw);t+=timedelta(seconds=seconds)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--env-file');parser.add_argument('--day',required=True);parser.add_argument('--output',default='live-audit.json')
    args=parser.parse_args()
    if args.env_file:m.API_KEY=dotenv_values(args.env_file).get('ENTSOE_API_KEY','').strip()
    if not m.API_KEY:raise SystemExit('ENTSOE_API_KEY missing')
    captured={};lock=threading.Lock();original=m.entsoe_request
    def request(params,start,end):
        body=original(params,start,end)
        with lock:captured[tuple(sorted(params.items()))]=body
        return body
    m.entsoe_request=request
    jobs={'renewables':lambda:m.fetch_renewables(args.day,True),'load':lambda:m.fetch_load(args.day),
          'borders':lambda:m.fetch_borders(args.day,m.DEFAULT_NEIGHBORS,True),
          'outages':lambda:m.fetch_outages(args.day,True),'balancing':lambda:m.fetch_balancing(args.day,True)}
    def run(item):
        name,fn=item;t=time.monotonic();data=fn();return name,{'seconds':round(time.monotonic()-t,2),'data':data}
    with ThreadPoolExecutor(max_workers=3) as pool:results=dict(pool.map(run,jobs.items()))
    checks=[]
    def raw(doc,**filters):
        return next(b for key,b in captured.items() if dict(key).get('documentType')==doc and all(dict(key).get(k)==v for k,v in filters.items()))
    def flat(body,**kw):return {t:v for (t,d),v in reference_points(body,**kw).items()}
    def compare(label,points,expected):
        got={datetime.fromisoformat(p['t']):p['v'] for p in points}
        assert set(got)==set(expected),(label,'timestamps',len(got),len(expected))
        error=max((abs(got[t]-v) for t,v in expected.items()),default=0)
        assert error<=0.0011,(label,error)
        checks.append({'name':label,'points':len(got),'max_abs_error':round(error,8)})
    ren=results['renewables']['data']['series']
    for psr,name in m.PSR.items():
        compare(name+' Actual',ren[name+' Actual'],flat(raw('A75'),psr=psr))
        for proc,label in [('A01','Day-ahead'),('A18','Current'),('A40','Intraday')]:
            compare(name+' '+label,ren[name+' '+label],flat(raw('A69',processType=proc),psr=psr))
    for proc,label in [('A16','Load Actual'),('A01','Load Forecast')]:
        compare(label,results['load']['data']['series'][label],flat(raw('A65',processType=proc)))
    for neighbor in m.DEFAULT_NEIGHBORS:
        for doc,label in [('A11','physical'),('A09','scheduled')]:
            incoming=flat(raw(doc,in_Domain=m.AREAS['DE_LU'],out_Domain=m.AREAS[neighbor]))
            outgoing=flat(raw(doc,in_Domain=m.AREAS[neighbor],out_Domain=m.AREAS['DE_LU']))
            expected={t:incoming[t]-outgoing[t] for t in incoming.keys()&outgoing.keys()}
            compare(neighbor+' '+label,results['borders']['data']['borders'][neighbor][label],expected)
    for family,codes in [('aFRR',('A67','A68')),('mFRR',('A60','A61'))]:
        for area,data in results['balancing']['data']['activation_areas'][family].items():
            if not data['net']:continue
            refs=[]
            for code in codes:
                try:body=raw('A24',area_Domain=m.AREAS[area],processType=code)
                except StopIteration:continue
                vals=reference_points(body,field='secondaryQuantity')
                if vals:refs.append({t:vals[t,'A01']-vals[t,'A02'] for t,d in vals if (t,'A01') in vals and (t,'A02') in vals})
            if refs:
                common=set.intersection(*(set(v) for v in refs))
                compare(family+' '+area,data['net'],{t:sum(v[t] for v in refs) for t in common})
    volumes=[]
    for area in m.BALANCING_AREAS:
        vals=reference_points(raw('A86',controlArea_Domain=m.AREAS[area]))
        by_time={}
        for (t,d),v in vals.items():by_time[t]=by_time.get(t,0)+( -v if d=='A02' else v)
        volumes.append(by_time)
    common=set.intersection(*(set(v) for v in volumes))
    compare('A86 Germany',results['balancing']['data']['series']['Net imbalance volume'],{t:sum(v[t] for v in volumes) for t in common})
    for category,label in [('A04','Imbalance price long'),('A05','Imbalance price short')]:
        compare('A85 '+category,results['balancing']['data']['series'][label],flat(raw('A85',controlArea_Domain=m.AREAS['DE']),field='imbalance_Price.amount',category=category))
    report={'tested_at':datetime.now(timezone.utc).isoformat(),'delivery_day':args.day,'version':m.app.version,
            'independent_xml_comparisons':checks,'panels':results,'successful_upstream_responses':len(captured)}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'version':m.app.version,'comparisons':len(checks),'points':sum(c['points'] for c in checks),'outages':results['outages']['data']['kpi'],'activation':results['balancing']['data']['sources']['12.3.E']},ensure_ascii=True))

if __name__=='__main__':main()
