"""Real SQLite tracker roundtrips, atomic imports, conflicts and history boundaries."""
import asyncio
from pathlib import Path
import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from backend.main import app
from database.connection import get_db
from database.models import Base, Application, ApplicationStatus


@pytest.fixture
async def tracker_db(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "tracker.db"}')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def override():
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client, sessions
    app.dependency_overrides.pop(get_db)
    await engine.dispose()


def row(**values):
    return dict(id='legacy-1', company='Fictional', jobTitle='Intern', status='Applied', dateApplied='2026-10-01T10:30:00Z', link='https://example.com', **values)


@pytest.mark.asyncio
async def test_roundtrip_legacy_backup_atomic_validation_and_conflict(tracker_db):
    client, _ = tracker_db
    assert (await client.get('/api/tracker/')).json() == {'revision': 0, 'items': []}
    saved = await client.put('/api/tracker/', json={'revision': 0, 'items': [row()]})
    assert saved.status_code == 200
    assert saved.json()['items'][0]['dateApplied'] == '2026-10-01'
    for changes in [{'status':'submitted'}, {'dateApplied':'2026-02-30'}, {'link':'javascript:alert(1)'}, {'id':'bad\'id'}, {'notes':'x'*10001}, {'company':23}]:
        response = await client.put('/api/tracker/', json={'revision':1,'items':[row(), {**row(), 'id':'second', **changes}]})
        assert response.status_code == 422
    assert (await client.put('/api/tracker/',json={'revision':1,'items':[row(),row()]})).status_code == 422
    assert (await client.put('/api/tracker/',json={'revision':0,'items':[]})).status_code == 409
    latest = (await client.get('/api/tracker/')).json()
    assert latest['revision'] == 1 and len(latest['items']) == 1
    assert (await client.put('/api/tracker/', json={'revision':1,'items':[]})).json()['revision'] == 2
    assert (await client.get('/api/tracker/')).json()['items'] == []


@pytest.mark.asyncio
async def test_simultaneous_first_writes_and_updates_have_one_winner(tracker_db):
    client, _ = tracker_db
    for revision in [0, 1]:
        responses = await asyncio.gather(*[client.put('/api/tracker/',json={'revision':revision,'items':[row()]}) for _ in range(2)])
        assert sorted(r.status_code for r in responses) == [200,409]


@pytest.mark.asyncio
async def test_history_copy_is_repeatable_and_does_not_change_agent_states(tracker_db):
    client, sessions = tracker_db
    async with sessions() as db:
        preparing = Application(company='Preparing Co',job_title='Intern',job_url='https://example.com/prepare',status=ApplicationStatus.READY_FOR_REVIEW)
        submitted = Application(company='Submitted Co',job_title='Intern',job_url='javascript:alert(1)',status=ApplicationStatus.SUBMITTED)
        db.add_all([preparing,submitted]);await db.commit()
        ids=[preparing.id, submitted.id]
    first = await client.post('/api/tracker/from-applications',json={'revision':0})
    assert first.status_code == 200
    result=first.json();assert result['added'] == 2
    assert [a['status'] for a in result['items']] == ['Interested','Applied']
    assert result['items'][1]['link'] == ''
    result['items'][0]['notes']='My edited notes';result['items'][0]['status']='Phone Screen'
    assert (await client.put('/api/tracker/',json={'revision':1,'items':result['items']})).status_code == 200
    repeated = (await client.post('/api/tracker/from-applications',json={'revision':2})).json()
    assert repeated['added'] == 0 and repeated['items'][0]['notes'] == 'My edited notes'
    assert repeated['items'][0]['status'] == 'Phone Screen'
    async with sessions() as db:
        assert (await db.get(Application,ids[0])).status == ApplicationStatus.READY_FOR_REVIEW
        assert (await db.get(Application,ids[1])).status == ApplicationStatus.SUBMITTED


@pytest.mark.asyncio
async def test_oversized_import_does_not_mutate_tracker(tracker_db):
    client, _ = tracker_db
    assert (await client.put('/api/tracker/', content=b'x'*(10*1024*1024+1))).status_code == 413
    assert (await client.get('/api/tracker/')).json()['revision'] == 0


def test_demo_and_local_tracker_use_same_logic_and_styles():
    for name in ['app.js','data.js','style.css']:
        assert Path(f'frontend/tracker/{name}').read_bytes() == Path(f'site/tracker/{name}').read_bytes()
    assert 'data-storage="api"' in Path('frontend/tracker/index.html').read_text()
    assert 'data-storage="api"' not in Path('site/tracker/index.html').read_text()
