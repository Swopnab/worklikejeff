"""Manual job tracking, isolated from the agent's preparation state machine."""
import json
import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from database.models import Application, TrackerWorkspace

router = APIRouter()
STATUSES = {'Interested', 'Applied', 'Phone Screen', 'Technical Interview', 'Final Round',
            'Offer Received', 'Accepted', 'Rejected', 'No Reply', 'Ghosted', 'Withdrawn'}
MAX_BYTES = 10 * 1024 * 1024


class TrackerItem(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,100}$')
    company: str = Field(default='', max_length=500)
    jobTitle: str = Field(default='', max_length=500)
    salary: str = Field(default='', max_length=500)
    notes: str = Field(default='', max_length=10000)
    status: str
    dateApplied: str = ''
    link: str = Field(default='', max_length=2048)
    createdAt: str = ''
    updatedAt: str = ''

    @field_validator('status')
    @classmethod
    def valid_status(cls, value):
        if value not in STATUSES:
            raise ValueError('Unknown application status')
        return value

    @field_validator('dateApplied')
    @classmethod
    def valid_date(cls, value):
        if not value:
            return ''
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T.*)?', value):
            raise ValueError('Invalid application date')
        day = date.fromisoformat(value[:10]).isoformat()
        if len(value) > 10:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
        return day

    @field_validator('link')
    @classmethod
    def valid_link(cls, value):
        if not value:
            return ''
        parts = urlsplit(value)
        if len(value) > 2048 or parts.scheme not in {'http', 'https'} or not parts.netloc or any(c.isspace() for c in value):
            raise ValueError('Links must use http:// or https://')
        return value

    @field_validator('createdAt', 'updatedAt')
    @classmethod
    def valid_timestamp(cls, value):
        if not value:
            return ''
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Timestamp must include a timezone')
        return parsed.astimezone(timezone.utc).isoformat()


class Snapshot(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    items: list[TrackerItem] = Field(max_length=10000)

    @field_validator('items')
    @classmethod
    def unique_ids(cls, items):
        if len({item.id for item in items}) != len(items):
            raise ValueError('Duplicate application IDs')
        return items


class HistoryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)


async def read_body(request, schema):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, 'Tracker backups are limited to 10 MB')
    try:
        return schema.model_validate(json.loads(data))
    except (ValidationError, ValueError, UnicodeDecodeError):
        raise HTTPException(422, 'Invalid tracker data: check IDs, stages, dates, links and field lengths')


def serialize(workspace):
    return {'revision': workspace.revision if workspace else 0,
            'items': json.loads(workspace.items_json) if workspace else []}


async def write_snapshot(db, revision, items):
    encoded = json.dumps(items, ensure_ascii=False)
    if len(encoded.encode('utf-8')) > MAX_BYTES:
        raise HTTPException(413, 'Tracker backups are limited to 10 MB')
    # Conditional write protects simultaneous tabs and makes replacing a backup atomic.
    if revision == 0:
        result = await db.execute(insert(TrackerWorkspace).values(id=1, revision=1, items_json=encoded).on_conflict_do_nothing(index_elements=['id']))
    else:
        result = await db.execute(update(TrackerWorkspace).where(TrackerWorkspace.id == 1, TrackerWorkspace.revision == revision).values(revision=revision + 1, items_json=encoded))
    if result.rowcount != 1:
        raise HTTPException(409, 'Tracker changed in another tab. Refresh before saving.')
    await db.commit()
    return {'revision': revision + 1, 'items': items}


@router.get('/')
async def get_tracker(db: AsyncSession = Depends(get_db)):
    return serialize(await db.get(TrackerWorkspace, 1))


@router.put('/')
async def replace_tracker(request: Request, db: AsyncSession = Depends(get_db)):
    body = await read_body(request, Snapshot)
    return await write_snapshot(db, body.revision, [item.model_dump() for item in body.items])


@router.post('/from-applications')
async def from_applications(request: Request, db: AsyncSession = Depends(get_db)):
    body = await read_body(request, HistoryRequest)
    current = serialize(await db.get(TrackerWorkspace, 1))
    if current['revision'] != body.revision:
        raise HTTPException(409, 'Tracker changed in another tab. Refresh before saving.')
    items = current['items']
    ids = {row['id'] for row in items}
    records = (await db.execute(select(Application).order_by(Application.id).limit(10001))).scalars().all()
    added = 0
    now = datetime.now(timezone.utc).isoformat()
    for app in records:
        tracker_id = f'worklike-{app.id}'
        if tracker_id in ids:
            continue  # Preserve any manually edited stage, dates and notes.
        if len(items) >= 10000:
            raise HTTPException(422, 'History would exceed the 10,000-application limit; existing tracker was kept')
        # Only a recorded submission is Applied. Preparing/ready never implies submitted.
        status = 'Applied' if app.status.value == 'submitted' else 'Interested'
        try:
            link = TrackerItem.valid_link(app.job_url or '')
        except ValueError:
            link = ''
        row = TrackerItem(id=tracker_id, company=app.company[:500], jobTitle=app.job_title[:500],
                          status=status, dateApplied=app.application_submitted_at.date().isoformat() if app.application_submitted_at else '',
                          link=link, notes=(app.notes or '')[:10000], createdAt=now, updatedAt=now)
        items.append(row.model_dump())
        ids.add(tracker_id)
        added += 1
    result = await write_snapshot(db, body.revision, items)
    return {**result, 'added': added}
