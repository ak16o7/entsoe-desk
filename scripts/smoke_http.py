"""Read-only HTTP deployment smoke test; no credentials included in reports."""
import argparse,json,urllib.request,urllib.parse
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:8000');p.add_argument('--day',required=True);a=p.parse_args()
for route in ['health','api/renewables','api/load','api/borders','api/outages','api/balancing']:
    url=a.base_url.rstrip('/')+'/'+route+('' if route=='health' else '?'+urllib.parse.urlencode({'day':a.day}))
    with urllib.request.urlopen(url,timeout=180) as response:data=json.load(response)
    if route=='health':assert data['version']=='4.4.1' and data['configured'],data
    else:assert 'series' in data and 'kpi' in data,(route,data)
    print(route,'OK',json.dumps(data.get('sources',{}),ensure_ascii=True))
