"""Measure actual indexed duplicate queries in an isolated synthetic SQLite DB."""
import argparse
import asyncio
import json
import platform
import statistics
import sys
import tempfile
from pathlib import Path
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from database.models import Base,Application,ApplicationStatus
from jobs.dedupe import check_duplicate,normalize_text

def summarize(samples):
    samples=sorted(samples)
    return {'p50_ms':round(statistics.median(samples),3),'p95_ms':round(samples[int(.95*(len(samples)-1))],3)}
async def benchmark(size,iterations):
    with tempfile.TemporaryDirectory() as folder:
        engine=create_async_engine(f'sqlite+aiosqlite:///{folder}/benchmark.db')
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # Bulk SQL inserts bypass ORM listeners, so provide normalized identity explicitly.
                await conn.execute(insert(Application),[{'company':f'Fictional {i}','job_title':'Software Intern','job_url':f'https://example.test/jobs/{i}',
                    'canonical_job_url':f'https://example.test/jobs/{i}','normalized_company':normalize_text(f'Fictional {i}'),
                    'normalized_job_title':normalize_text('Software Intern'),'status':ApplicationStatus.READY} for i in range(size)])
            sessions=async_sessionmaker(engine,expire_on_commit=False); cases={}
            async with sessions() as session:
                for kind,company,url,expected in [('url-hit','Fictional 0','https://example.test/jobs/0?utm_source=demo',True),
                    ('identity-hit','Fictional 0 Inc.','https://example.test/other',True),('miss','No Matching Company','https://example.test/absent',False)]:
                    samples=[]
                    for _ in range(iterations+1):
                        start=perf_counter(); duplicate,_,_=await check_duplicate(session,company,'Software Intern',url); elapsed=(perf_counter()-start)*1000
                        if duplicate!=expected:raise AssertionError(kind)
                        samples.append(elapsed)
                    cases[kind]=summarize(samples[1:])
            return {'records':size,'iterations_per_query':iterations,'queries':cases}
        finally:await engine.dispose()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--iterations',type=int,default=50)
    args=parser.parse_args()
    if args.iterations<1:parser.error('iterations must be positive')
    result={'fixture':'synthetic local SQLite; no model/browser/network workload','python':platform.python_version(),'platform':platform.platform(),
        'runs':[asyncio.run(benchmark(size,args.iterations)) for size in [1000,10000]]}
    report=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(report)
    else:print(report)
