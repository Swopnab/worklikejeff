"""Complete local UI -> API -> SQLite story with fictional data only."""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import time

import httpx
import pytest
from playwright.async_api import async_playwright
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from database.models import Application, ApplicationStatus


@pytest.mark.asyncio
async def test_tracker_browser_roundtrip_conflicts_and_public_demo(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    db_path=tmp_path/'browser.db'
    env={**os.environ,'DATABASE_PATH':str(db_path),'APPLICATIONS_DIR':str(tmp_path/'applications'),
         'RESUME_GENERATED_DIR':str(tmp_path/'generated'),'LOGS_DIR':str(tmp_path/'logs'),
         'RUNTIME_SETTINGS_PATH':str(tmp_path/'settings.json')}
    log_path=tmp_path/'server.log'
    with log_path.open('w') as logs:
        process=await asyncio.create_subprocess_exec(sys.executable,'-m','uvicorn','backend.main:app','--host','127.0.0.1','--port',str(port),env=env,stdout=logs,stderr=logs)
        base=f'http://127.0.0.1:{port}'
        try:
            async with httpx.AsyncClient() as client:
                deadline=time.monotonic()+20
                while True:
                    try:
                        response=await client.get(base+'/api/health')
                        if response.status_code==200:break
                    except httpx.TransportError:
                        pass
                    if time.monotonic()>deadline:pytest.fail(log_path.read_text())
                    await asyncio.sleep(.1)
            engine=create_async_engine(f'sqlite+aiosqlite:///{db_path}')
            async with async_sessionmaker(engine)() as db:
                db.add(Application(company='Fictional History Co',job_title='Backend Intern',job_url='https://example.com/history',status=ApplicationStatus.READY_FOR_REVIEW))
                await db.commit()
            await engine.dispose()
            async with async_playwright() as pw:
                browser=await pw.chromium.launch()
                try:
                    page=await browser.new_page(viewport={'width':1440,'height':1000})
                    errors=[]
                    page.on('pageerror', lambda err: errors.append(str(err)))
                    page.on('dialog',lambda dialog: asyncio.create_task(dialog.accept()))
                    await page.goto(base+'/#tracker')
                    frame=page.frame_locator('#tracker-frame')
                    await frame.locator('#add-application-btn').click()
                    await frame.locator('#qa-company').fill('Fictional Browser Co')
                    await frame.locator('#qa-jobtitle').fill('Software Engineer Intern')
                    await frame.locator('#qa-status').select_option('Applied')
                    await frame.locator('#save-application').click()
                    await frame.get_by_text('Application added',exact=True).wait_for()
                    async with httpx.AsyncClient() as client:
                        snapshot=(await client.get(base+'/api/tracker/')).json()
                        assert snapshot['items'][0]['company']=='Fictional Browser Co'
                    await page.reload()
                    assert await frame.locator('.company-cell strong').inner_text()=='Fictional Browser Co'
                    await frame.locator('#from-history').click()
                    await frame.get_by_text('Added 1 application(s) from history',exact=True).wait_for()
                    assert await frame.locator('.row-checkbox').count()==2
                    await frame.locator('#from-history').click()
                    await frame.get_by_text('Added 0 application(s) from history',exact=True).wait_for()
                    # An independent tab sees the same database snapshot.
                    second=await browser.new_page()
                    await second.goto(base+'/static/tracker/index.html')
                    assert await second.locator('.row-checkbox').count()==2
                    await second.get_by_role('button',name='Edit Fictional Browser Co application',exact=True).click()
                    await second.locator('#qa-company').fill('Stale tab draft')
                    await frame.get_by_role('button',name='Edit Fictional Browser Co application',exact=True).click()
                    await frame.locator('#qa-notes').fill('First tab saved')
                    await frame.locator('#save-application').click()
                    await frame.locator('#quick-add-modal').wait_for(state='hidden')
                    await second.locator('#save-application').click()
                    await second.get_by_text('This tracker changed in another tab.',exact=False).wait_for()
                    assert await second.locator('#qa-company').input_value()=='Stale tab draft'
                    assert await second.locator('#quick-add-modal').is_visible()
                    await second.close()
                    # Failed writes keep the editor draft and do not pretend to save.
                    await frame.get_by_role('button',name='Edit Fictional Browser Co application',exact=True).click()
                    await frame.locator('#qa-notes').fill('Failed request draft')
                    await page.route('**/api/tracker/',lambda route: route.fulfill(status=503,content_type='application/json',body='{"detail":"Server unavailable"}') if route.request.method=='PUT' else route.continue_())
                    await frame.locator('#save-application').click()
                    await frame.get_by_text('Server unavailable',exact=True).wait_for()
                    assert await frame.locator('#qa-notes').input_value()=='Failed request draft'
                    await page.unroute('**/api/tracker/')
                    await frame.locator('#save-application').click()
                    await frame.locator('#quick-add-modal').wait_for(state='hidden')
                    # Import the standalone backup format, reject malicious links atomically.
                    invalid=[{'id':'unsafe','company':'Example','jobTitle':'Intern','status':'Applied','link':'javascript:alert(1)'}]
                    await frame.locator('#import-file-input').set_input_files({'name':'invalid.json','mimeType':'application/json','buffer':json.dumps(invalid).encode()})
                    await frame.get_by_text('Import rejected:',exact=False).wait_for()
                    assert await frame.locator('.row-checkbox').count()==2
                    await frame.locator('#board-view-btn').click()
                    await frame.locator('[data-stage-id]').first.select_option('Final Round')
                    await frame.get_by_text('Stage updated',exact=True).wait_for()
                    await frame.locator('#table-view-btn').click()
                    for width,height in [(390,844),(768,1024),(1440,1000)]:
                        await page.set_viewport_size({'width':width,'height':height})
                        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                        assert await frame.locator('body').evaluate('(body)=>body.scrollWidth<=innerWidth+1')
                        await frame.locator('#add-application-btn').click()
                        assert await frame.locator('#qa-company').is_visible()
                        await frame.locator('#quick-add-cancel').click()
                        screenshots=os.environ.get('TRACKER_SCREENSHOT_DIR')
                        if screenshots:
                            Path(screenshots).mkdir(parents=True,exist_ok=True)
                            await frame.locator('#toast-container').evaluate('(el)=>el.replaceChildren()')
                            await page.screenshot(path=str(Path(screenshots)/f'integrated-{width}.png'),full_page=True)
                    assert errors==[]
                    # Static public version never calls the Python API.
                    demo=await browser.new_page()
                    requested=[]
                    demo.on('request',lambda req:requested.append(req.url))
                    # Serve site from its own file server to exercise relative asset paths.
                    import functools
                    from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
                    from threading import Thread
                    handler=functools.partial(SimpleHTTPRequestHandler,directory=str(Path('site').resolve()))
                    server=ThreadingHTTPServer(('127.0.0.1',0),handler)
                    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
                    try:
                        await demo.goto(f'http://127.0.0.1:{server.server_port}/demo.html')
                        await demo.get_by_role('link',name='Job Tracker',exact=False).click()
                        await demo.locator('#add-application-btn').click()
                        await demo.locator('#qa-company').fill('Static only')
                        await demo.locator('#qa-jobtitle').fill('Intern')
                        await demo.locator('#save-application').click()
                        await demo.get_by_text('Application added',exact=True).wait_for()
                        await demo.reload()
                        assert await demo.locator('.company-cell strong').inner_text()=='Static only'
                        assert not any('/api/' in url for url in requested)
                    finally:
                        server.shutdown();server.server_close();thread.join()
                finally:
                    await browser.close()
        finally:
            process.terminate()
            await process.wait()
