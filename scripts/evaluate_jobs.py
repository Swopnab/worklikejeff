"""Reproducible synthetic eligibility/skill evaluation; no AI or private profile."""
import argparse
import copy
import json
import platform
import statistics
import sys
from pathlib import Path
from time import perf_counter
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from jobs.eligibility import EligibilityChecker
from jobs.scoring import JobMatchEngine

def evaluate(iterations=100):
    dataset=json.loads((ROOT/'evaluation/eligibility_cases.json').read_text())
    predictions=[]; timings=[]
    for case in dataset['cases']:
        profile=copy.deepcopy(dataset['profile'])
        if 'education' in case: profile['education']=case['education']
        checker=EligibilityChecker(profile)
        for _ in range(iterations):
            start=perf_counter(); actual=checker.evaluate(case['job']); timings.append((perf_counter()-start)*1000)
        predictions.append({'id':case['id'],'expected':case['expected_status'],'actual':actual.status,'correct':actual.status==case['expected_status']})
    confusion={expected:{actual:0 for actual in ['eligible','ineligible','needs_review']} for expected in ['eligible','ineligible','needs_review']}
    for row in predictions: confusion[row['expected']][row['actual']]+=1
    engine=JobMatchEngine({'skills':{'languages':{'javascript':'verified','python':'verified','c++':'verified'}}},{'projects':[]})
    skills=[('Java',False),('JavaScript',True),('C',False),('C++',True),('Python3',True),('TypeScript',False)]
    skill_results=[{'skill':name,'expected_match':expected,'actual_match':engine._match_skill(name)[0]} for name,expected in skills]
    ordered=sorted(timings)
    return {'dataset':'synthetic regression examples; not hiring/legal/real-world accuracy','python':platform.python_version(),'platform':platform.platform(),'iterations_per_case':iterations,
            'eligibility_cases':len(predictions),'correct':sum(r['correct'] for r in predictions),'confusion_matrix':confusion,
            'false_eligible':sum(r['actual']=='eligible' and r['expected']!='eligible' for r in predictions),
            'false_ineligible':sum(r['actual']=='ineligible' and r['expected']!='ineligible' for r in predictions),
            'latency_ms':{'p50':round(statistics.median(ordered),4),'p95':round(ordered[int(.95*(len(ordered)-1))],4)},
            'predictions':predictions,'skill_cases':skill_results}
if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path); parser.add_argument('--iterations',type=int,default=100)
    args=parser.parse_args()
    if args.iterations<1:parser.error('iterations must be positive')
    result=evaluate(args.iterations); text=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text)
    else:print(text)
    if result['correct']!=result['eligibility_cases'] or any(r['expected_match']!=r['actual_match'] for r in result['skill_cases']):sys.exit(1)
