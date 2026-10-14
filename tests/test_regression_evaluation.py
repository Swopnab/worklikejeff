import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from contextlib import asynccontextmanager
from scripts.evaluate_jobs import evaluate
from jobs.dedupe import normalize_text,check_duplicate
from database.models import Base,Application,ApplicationStatus,AgentState,AgentStateEnum,ActivityLog
import agent.recovery as recovery

def test_labeled_eligibility_and_skill_boundaries():
    from jobs.scoring import JobMatchEngine
    assert JobMatchEngine._skills_overlap('java', 'java 17')
    assert JobMatchEngine._skills_overlap('c', 'c programming')
    assert not JobMatchEngine._skills_overlap('c', 'c#')
    report=evaluate(iterations=1)
    assert report['correct']==report['eligibility_cases']
    assert report['false_eligible']==report['false_ineligible']==0
    assert all(r['expected_match']==r['actual_match'] for r in report['skill_cases'])

def test_company_normalization_preserves_words_starting_with_abbreviations():
    assert normalize_text('Coinbase Inc.')=='coinbase'
    assert normalize_text('Computer Corporation')=='computer'
    assert normalize_text('Incredible Labs')=='incredible labs'

@pytest.mark.asyncio
async def test_recovery_survives_restart_without_retry_or_duplicate_log(tmp_path,monkeypatch):
    engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "recovery.db"}')
    try:
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        sessions=async_sessionmaker(engine,expire_on_commit=False)
        @asynccontextmanager
        async def transaction():
            async with sessions() as session:
                yield session
                await session.commit()
        monkeypatch.setattr(recovery,'db_session',transaction)
        async with transaction() as session:
            for status in [ApplicationStatus.APPLYING,ApplicationStatus.PAUSED,ApplicationStatus.NEEDS_REVIEW,ApplicationStatus.SUBMITTED]:
                session.add(Application(company='Fictional',job_title=status.value,job_url=f'https://example.test/{status.value}',status=status))
            session.add(AgentState(id=1,state=AgentStateEnum.RUNNING,stop_requested=True))
        first=await recovery.recover_on_startup()
        assert len(first['interrupted'])==1
        assert any('running' in action for action in first['action_taken'])
        second=await recovery.recover_on_startup()
        assert second['action_taken']==[]
        assert second['interrupted']==first['interrupted']
        async with sessions() as session:
            rows=(await session.execute(select(Application))).scalars().all()
            assert {row.status for row in rows}=={ApplicationStatus.INTERRUPTED,ApplicationStatus.PAUSED,ApplicationStatus.NEEDS_REVIEW,ApplicationStatus.SUBMITTED}
            assert await session.scalar(select(func.count()).select_from(ActivityLog))==1
            state=await session.get(AgentState,1)
            assert state.state==AgentStateEnum.STOPPED and not state.stop_requested
    finally: await engine.dispose()

@pytest.mark.asyncio
async def test_duplicate_lookup_handles_existing_duplicate_records(tmp_path):
    engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "duplicates.db"}')
    try:
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        sessions=async_sessionmaker(engine,expire_on_commit=False)
        async with sessions() as session:
            for _ in range(2):session.add(Application(company='Fictional',job_title='Intern',job_url='https://example.test/job'))
            await session.commit()
            duplicate,existing,reason=await check_duplicate(session,'Fictional','Intern','https://example.test/job')
            assert duplicate and existing.id and 'URL' in reason
    finally:await engine.dispose()

@pytest.mark.asyncio
async def test_legacy_identity_migration_preserves_records_and_runs_twice(tmp_path,monkeypatch):
    from sqlalchemy import text
    import database.connection as database
    engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "legacy.db"}')
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text('DROP INDEX ix_applications_normalized_identity'))
            await conn.execute(text('ALTER TABLE applications DROP COLUMN normalized_company'))
            await conn.execute(text('ALTER TABLE applications DROP COLUMN normalized_job_title'))
            await conn.execute(text("INSERT INTO applications(company,job_title,job_url,status,discovered_at,last_updated_at,review_required,review_completed,submission_confirmed_by_user) VALUES('Computer Inc.','Software Intern','https://example.test/legacy?utm_source=x','READY',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1,0,0)"))
        monkeypatch.setattr(database,'engine',engine)
        await database.init_db(); await database.init_db()
        sessions=async_sessionmaker(engine,expire_on_commit=False)
        async with sessions() as session:
            duplicate,app,_=await check_duplicate(session,'Computer Corporation','Software Intern','https://example.test/another')
            assert duplicate and app.normalized_company=='computer' and app.id==1
            assert app.canonical_job_url=='https://example.test/legacy'
    finally:await engine.dispose()
