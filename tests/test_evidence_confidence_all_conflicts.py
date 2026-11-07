from datetime import datetime
from zoneinfo import ZoneInfo
from foot_web.services.evidence_confidence import score_evidence

def test_nonweighted_dimension_conflict_blocks():
    source={'id':'s1','url':'https://official.example/a','title':'a','published_at':'2026-11-07T08:00:00+08:00','effective_at':'2026-11-07T08:00:00+08:00','group_id':'g1','tier':'L1'}
    dims=[{'id':i,'status':'verified' if i in {1,4,7,9,12,13,15,17,18,19,21} else 'unknown','home':'x','away':'y','impact':'x','source_ids':['s1'] if i in {1,4,7,9,12,13,15,17,18,19,21} else []} for i in range(1,24)]
    dims[10]|={'status':'conflict','source_ids':['s1']}
    e={'sources':[source], 'dimensions':dims, 'assessments':[{'option_id':'o','reasons':['a','b'],'source_ids':['s1']}]}
    result=score_evidence(e,option_id='o',as_of=datetime(2026,11,7,12,tzinfo=ZoneInfo('Asia/Shanghai')))
    assert not result['eligible'] and any('维度11' in x for x in result['reasons'])
