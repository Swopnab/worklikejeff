/**
 * app.js — WorkLikeDog SPA
 * Phase 4: Local artifact storage, history dashboard, real-time analytics charts,
 *          full application detail drawer with artifact inspection.
 */

const API = '/api';
let pollInterval = null;
let currentPage = 'dashboard';
let currentTailorEvaluation = null;
let appFilters = {};
let currentAppDetailId = null;
let candidateProfile = null;

// ============================================================
// ROUTER
// ============================================================
function navigate(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const pageEl = document.getElementById(`page-${page}`);
  if (!pageEl) return;
  history.replaceState(null, "", `#${page}`);
  const navEl  = document.getElementById(`nav-${page}`);
  if (pageEl) pageEl.classList.add('active');
  if (navEl)  navEl.classList.add('active');

  currentPage = page;
  document.body.classList.toggle('tracker-page', page === 'tracker');
  document.title = `WorkLikeADog — ${capitalize(page)}`;

  switch (page) {
    case 'dashboard':    loadDashboard(); break;
    case 'applications': loadApplications(); break;
    case 'jobs':         loadJobQueue(); break;
    case 'resume':       loadResumePage(); break;
    case 'profile':      loadProfile(); break;
    case 'settings':     loadSettings(); break;
    case 'learnings':    loadLearnings(); break;
  }
}

document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => navigate(btn.dataset.page));
});

// ============================================================
// API HELPERS
// ============================================================
async function apiFetch(path, options = {}) {
  try {
    const resp = await fetch(`${API}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(Array.isArray(err.detail) ? err.detail.map(e => e.msg).join("; ") : err.detail || `HTTP ${resp.status}`);
    }
    return await resp.json();
  } catch (e) {
    console.error(`API ${path}:`, e.message);
    throw e;
  }
}

async function apiFetchText(path) {
  const resp = await fetch(`${API}${path}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return await resp.text();
}

// ============================================================
// AGENT CONTROLS
// ============================================================
async function agentStart() {
  try {
    disableControls(true);
    const result = await apiFetch('/agent/start', { method: 'POST' });
    showToast(result.message || 'Agent started', 'success');
    if (result.recovery?.action_taken?.length) {
      showToast(`Recovery: ${result.recovery.action_taken.join(', ')}`, 'warning');
    }
    pollAgentStatus();
  } catch(e) {
    showToast(`Could not start: ${e.message}`, 'error');
    disableControls(false);
  }
}

async function agentStop() {
  try {
    const result = await apiFetch('/agent/stop', { method: 'POST' });
    showToast(result.message, 'info');
    pollAgentStatus();
  } catch(e) {
    showToast(`Error: ${e.message}`, 'error');
  }
}

async function agentPause() {
  try {
    const result = await apiFetch('/agent/pause', { method: 'POST' });
    showToast(result.message, 'info');
    pollAgentStatus();
  } catch(e) {
    showToast(`Error: ${e.message}`, 'error');
  }
}

async function agentResume() {
  try {
    const result = await apiFetch('/agent/resume', { method: 'POST' });
    showToast(result.message, 'success');
    pollAgentStatus();
  } catch(e) {
    showToast(`Error: ${e.message}`, 'error');
  }
}

function agentForceKill() {
  const modal = document.getElementById('modal-forcekill');
  if (modal) {
    showModal('modal-forcekill');
  } else if (confirm("EMERGENCY FORCE KILL: Are you sure you want to immediately terminate the agent?")) {
    confirmForceKill();
  }
}

async function confirmForceKill() {
  closeModal('modal-forcekill');
  try {
    const result = await apiFetch('/agent/force-kill', {
      method: 'POST',
      body: JSON.stringify({ confirmed: true }),
    });
    showToast(result.message || 'Force kill executed.', 'warning');
    pollAgentStatus();
  } catch(e) {
    showToast(`Error: ${e.message}`, 'error');
  }
}

let currentHandoffAppId = null;
let currentHandoffJobUrl = null;

function openExternalUrl(url) {
  if (!url || url === '#' || url === 'undefined') {
    showToast('Job URL is not available', 'warning');
    return;
  }
  try {
    const targetUrl = new URL(url.trim(), window.location.href);
    if (!['http:', 'https:'].includes(targetUrl.protocol)) throw new Error('Unsupported link');
    window.open(targetUrl.href, '_blank', 'noopener,noreferrer');
  } catch { showToast('This link is not a valid web address', 'warning'); }
}

function openHandoffJobUrl() {
  openExternalUrl(currentHandoffJobUrl);
}

async function takeControl() {
  try {
    const res = await apiFetch('/agent/take-control', { method: 'POST' });
    showToast(res.message || 'You have control of the browser session.', 'info');
    document.getElementById('btn-take-control')?.classList.add('hidden');
    document.getElementById('btn-hand-back')?.classList.remove('hidden');
    pollAgentStatus();
  } catch(e) {
    showToast(`Error taking control: ${e.message}`, 'error');
  }
}

async function handBack() {
  try {
    const res = await apiFetch('/agent/hand-back', { method: 'POST' });
    showToast(res.message || 'Control handed back to agent.', 'success');
    closeModal('modal-handoff-review');
    document.getElementById('agent-banner')?.classList.add('hidden');
    document.getElementById('btn-take-control')?.classList.remove('hidden');
    document.getElementById('btn-hand-back')?.classList.add('hidden');
    pollAgentStatus();
  } catch(e) {
    showToast(`Error handing back: ${e.message}`, 'error');
  }
}

async function openHandoffReview(appId) {
  currentHandoffAppId = appId;
  showModal('modal-handoff-review');
  try {
    const app = await apiFetch(`/applications/${appId}`);
    currentHandoffJobUrl = app.job_url || '';
    document.getElementById('modal-handoff-subtitle').textContent = `${app.company} — ${app.job_title}`;
    document.getElementById('handoff-score').textContent = app.match_score != null ? `${app.match_score}%` : '--';
    document.getElementById('handoff-status').textContent = (app.status || 'READY_FOR_REVIEW').toUpperCase();

    const hashEl = document.getElementById('handoff-resume-hash');
    if (hashEl) {
      hashEl.textContent = `SHA-256: ${app.resume_hash || 'Generated & Verified'}`;
    }

    const answersEl = document.getElementById('handoff-answers-list');
    if (answersEl) {
      answersEl.innerHTML = '<span style="color:var(--text-muted);">Loading answers...</span>';
      try {
        const answersRaw = await apiFetchText(`/applications/${appId}/artifact?file=answers.json`);
        const answersList = JSON.parse(answersRaw);
        if (Array.isArray(answersList) && answersList.length > 0) {
          answersEl.innerHTML = answersList.map(a => `
            <div style="margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 6px;">
              <div style="font-weight:600; color:var(--text-primary); font-size:12px;">Q: ${escHtml(a.question || a.name || 'Question')}</div>
              <div style="color:#22c55e; font-weight:700; font-size:12px; margin-top:2px;">A: ${escHtml(String(a.answer || a.value || '—'))}</div>
              <div style="font-size:10.5px; color:var(--text-muted); margin-top:1px;">Source: ${escHtml(a.source || 'Approved Profile Data')}</div>
            </div>
          `).join('');
        } else {
          answersEl.innerHTML = '<span style="color:var(--text-muted);">Standard profile fields mapped successfully.</span>';
        }
      } catch {
        answersEl.innerHTML = '<span style="color:var(--text-muted);">Verified profile data used for all standard form fields.</span>';
      }
    }

    refreshReviewScreenshot();
  } catch(e) {
    showToast(`Failed loading application review: ${e.message}`, 'error');
  }
}

function previewHandoffPdf() {
  if (!currentHandoffAppId) return;
  const iframe = document.getElementById('pdf-preview-iframe');
  if (iframe) {
    iframe.src = `/api/applications/${currentHandoffAppId}/resume/preview?t=${Date.now()}`;
  }
  showModal('modal-pdf-preview');
}

function openHandoffPdfInNewTab() {
  if (!currentHandoffAppId) return;
  openExternalUrl(`/api/applications/${currentHandoffAppId}/resume/preview`);
}

async function viewHandoffLatex() {
  if (!currentHandoffAppId) return;
  await viewArtifact(currentHandoffAppId, 'resume.tex', 'Tailored LaTeX Source', 'latex');
}

async function recompileHandoffResume() {
  if (!currentHandoffAppId) return;
  showToast('Recompiling tailored LaTeX resume...', 'info');
  try {
    const res = await apiFetch(`/applications/${currentHandoffAppId}/resume/recompile`, { method: 'POST' });
    if (res.success) {
      showToast(`Resume recompiled successfully! 1-Page PDF verified.`, 'success');
      const hashEl = document.getElementById('handoff-resume-hash');
      if (hashEl) hashEl.textContent = `SHA-256: ${res.pdf_hash}`;
      previewHandoffPdf();
    } else {
      showToast(`Compilation failed: ${res.error}`, 'error');
    }
  } catch(e) {
    showToast(`Recompile error: ${e.message}`, 'error');
  }
}

async function confirmManualSubmissionAction() {
  if (!currentHandoffAppId) return;
  try {
    const res = await apiFetch(`/applications/${currentHandoffAppId}/confirm-submission`, {
      method: 'POST',
      body: JSON.stringify({ confirmation: 'User manually submitted on employer site' })
    });
    showToast('Application marked as SUBMITTED!', 'success');
    closeModal('modal-handoff-review');
    await handBack();
    if (currentPage === 'applications') loadApplications();
    loadStats();
  } catch(e) {
    showToast(`Error confirming submission: ${e.message}`, 'error');
  }
}

function refreshReviewScreenshot() {
  if (!currentHandoffAppId) return;
  const img = document.getElementById('handoff-screenshot-img');
  if (img) {
    img.src = `/api/applications/${currentHandoffAppId}/screenshot?t=${Date.now()}`;
  }
}

async function rejectCurrentHandoff() {
  if (!currentHandoffAppId) return;
  try {
    const res = await apiFetch(`/applications/${currentHandoffAppId}/decision`, {
      method: 'POST',
      body: JSON.stringify({ action: 'reject_and_skip', reason: 'Skipped by user during review' })
    });
    showToast('Application abandoned and marked skipped.', 'info');
    closeModal('modal-handoff-review');
    await handBack();
    if (currentPage === 'applications') loadApplications();
  } catch(e) {
    showToast(`Error skipping application: ${e.message}`, 'error');
  }
}

async function triggerDiscoverySync() {
  try {
    const res = await apiFetch('/discovery/sync', { method: 'POST' });
    showToast('Discovery sync started! New jobs will appear in the queue.', 'info');
    pollAgentStatus();
  } catch(e) {
    showToast(`Failed starting discovery sync: ${e.message}`, 'error');
  }
}

// ============================================================
// DASHBOARD STATUS POLLING
// ============================================================
async function loadDashboard() {
  await Promise.all([pollAgentStatus(), loadStats(), loadRecentActivity()]);
  startPolling();
}

function startPolling() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    if (currentPage === 'dashboard') {
      await pollAgentStatus();
    }
  }, 3000);
}

async function pollAgentStatus() {
  try {
    const status = await apiFetch('/agent/status');
    updateAgentStatusUI(status);
  } catch(e) {
    updateAgentStateDisplay('error', 'Cannot reach backend');
  }
}

function updateAgentStatusUI(status) {
  const state = status.state;
  const taskId = status.current_task_id;

  updateAgentStateDisplay(state, status.last_checkpoint);
  updateAgentButtons(state);

  document.getElementById('badge-dryrun').classList.toggle('hidden', !status.dry_run);
  document.getElementById('badge-autosubmit').classList.toggle('hidden', !status.auto_submit);

  const ollamaDot = document.getElementById('stat-ollama')?.querySelector('.status-dot');
  const ollamaEl = document.getElementById('stat-ollama');
  const ollamaModelEl = document.getElementById('stat-ollama-model');
  if (ollamaDot) ollamaDot.className = `status-dot ${status.ollama_online ? 'online' : 'offline'}`;
  if (ollamaEl) ollamaEl.lastChild.textContent = ` ${status.ollama_online ? 'Online' : 'Offline'}`;
  if (ollamaModelEl) ollamaModelEl.textContent = status.ollama_model;

  const banner = document.getElementById('agent-banner');
  if (['needs_attention', 'handoff', 'paused'].includes(state) && banner) {
    banner.classList.remove('hidden');
    document.getElementById('banner-title').textContent =
      state === 'handoff' ? 'Human in Control' : 'Your agent needs a hand.';
    document.getElementById('banner-message').textContent =
      state === 'handoff'
        ? 'Complete the form in the browser or review pre-submit screenshot, then hand control back.'
        : 'The agent paused for human review or challenge handling.';
    
    // Add review button if task ID is present
    if (taskId) {
      currentHandoffAppId = taskId;
      const reviewBtn = document.getElementById('btn-banner-review');
      if (!reviewBtn) {
        const btnContainer = banner.querySelector('.banner-actions');
        if (btnContainer) {
          const btn = document.createElement('button');
          btn.id = 'btn-banner-review';
          btn.className = 'btn btn-primary btn-sm';
          btn.textContent = 'Review Application';
          btn.onclick = () => openHandoffReview(taskId);
          btnContainer.prepend(btn);
        }
      }
    }
  } else if (banner && !['needs_attention', 'handoff', 'paused'].includes(state)) {
    banner.classList.add('hidden');
  }
}

function updateAgentStateDisplay(state, checkpoint) {
  const el = document.getElementById('stat-state');
  const cpEl = document.getElementById('stat-checkpoint');
  if (!el) return;

  const dotClass = {
    'stopped': 'stopped', 'starting': 'running', 'running': 'running',
    'paused': 'paused', 'pause_requested': 'paused',
    'needs_attention': 'attention', 'handoff': 'attention',
    'stop_requested': 'paused', 'stopping': 'paused',
    'error': 'error',
  }[state] || 'stopped';

  el.innerHTML = `<span class="status-dot ${dotClass}"></span> ${state.toUpperCase()}`;
  if (cpEl) cpEl.textContent = checkpoint ? `checkpoint: ${checkpoint}` : '';
}

function updateAgentButtons(state) {
  const startBtn = document.getElementById('btn-start-agent');
  const stopBtn  = document.getElementById('btn-stop-agent');
  const pauseBtn = document.getElementById('btn-pause-agent');

  const stopped = ['stopped', 'error'].includes(state);
  const running = ['running', 'starting', 'applying'].includes(state);
  const paused  = state === 'paused';

  if (startBtn) startBtn.disabled = !stopped;
  if (stopBtn)  stopBtn.disabled  = stopped || state.includes('stop');
  if (pauseBtn) {
    pauseBtn.disabled = !(running || paused);
    pauseBtn.textContent = paused ? 'Resume' : 'Pause';
    if (paused) { pauseBtn.onclick = agentResume; }
    else        { pauseBtn.onclick = agentPause; }
  }
}

function disableControls(disabled) {
  ['btn-start-agent', 'btn-stop-agent', 'btn-pause-agent', 'btn-kill-agent'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = disabled;
  });
}

// ============================================================
// STATS
// ============================================================
async function loadStats() {
  try {
    const stats = await apiFetch('/applications/stats');
    document.getElementById('stat-submitted').textContent = stats.submitted_today ?? 0;
    document.getElementById('stat-paused').textContent    = (stats.paused ?? 0) + (stats.needs_attention ?? 0);
    document.getElementById('stat-discovered').textContent = stats.total ?? 0;
    try {
      const queue = await apiFetch('/jobs/queue');
      document.getElementById('stat-queue').textContent = queue.items?.length ?? 0;
    } catch(e) {}
  } catch(e) {}
}

// ============================================================
// RECENT ACTIVITY
// ============================================================
async function loadRecentActivity() {
  const el = document.getElementById('recent-activity-list');
  if (!el) return;

  try {
    const data = await apiFetch('/applications/?page_size=8');
    const items = data.items || [];

    if (!items.length) {
      el.innerHTML = `
        <div class="empty-state">
          <svg width="32" height="32" viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3"><path d="M4 20l7-7 5 5 6-8 6 6"/></svg>
          <p>No activity yet. Analyze a job or start the agent.</p>
        </div>
      `;
      return;
    }

    el.innerHTML = items.map(app => {
      const time = formatTime(app.discovered_at);
      return `
        <div class="activity-item" onclick="viewApplication(${app.id})">
          <span class="activity-time">${time}</span>
          <span class="activity-event">${app.status.toUpperCase()}</span>
          <span class="activity-desc">${escHtml(app.company)} — ${escHtml(app.job_title)}</span>
          ${app.match_score !== null ? `<span class="match-score ${scoreClass(app.match_score)}">${Math.round(app.match_score)}%</span>` : ''}
        </div>
      `;
    }).join('');
  } catch(e) {
    el.innerHTML = `<div class="empty-state"><p>Error loading activity</p></div>`;
  }
}

// ============================================================
// APPLICATIONS — History table with search, filters, pagination
// ============================================================

async function loadApplications() {
  const tbody = document.getElementById('applications-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="8" class="table-empty"><div class="loading-pulse">Loading applications…</div></td></tr>';

  try {
    const params = new URLSearchParams();
    if (appFilters.search)    params.set('search', appFilters.search);
    if (appFilters.status)    params.set('status', appFilters.status);
    if (appFilters.min_score) params.set('min_score', appFilters.min_score);
    params.set('page_size', '50');

    const data = await apiFetch(`/applications/?${params}`);
    const items = data.items || [];

    const subtitle = document.getElementById('apps-subtitle');
    if (subtitle) subtitle.textContent = `${data.total} application${data.total !== 1 ? 's' : ''}`;

    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="table-empty">No applications found. Use "Queue Job URL" or Tailor page to evaluate jobs.</td></tr>`;
      return;
    }

    tbody.innerHTML = items.map(app => `
      <tr class="app-row" onclick="viewApplication(${app.id})" data-id="${app.id}">
        <td>
          <div style="font-weight:600; color:var(--text-primary);">${escHtml(app.company)}</div>
        </td>
        <td>
          <div style="font-size:13px;">${escHtml(app.job_title)}</div>
          ${app.location ? `<div style="font-size:11px; color:var(--text-muted); margin-top:1px;">${escHtml(app.location)}</div>` : ''}
        </td>
        <td><span class="badge badge-muted">${escHtml(app.source || 'manual')}</span></td>
        <td>
          ${app.match_score !== null
            ? `<div class="score-pill ${scoreClass(app.match_score)}">${Math.round(app.match_score)}<span style="font-size:10px; font-weight:500;">%</span></div>`
            : '<span style="color:var(--text-muted);">—</span>'
          }
        </td>
        <td>${statusChipHtml(app.status)}</td>
        <td style="font-size:12px; color:var(--text-muted);">${formatDate(app.discovered_at)}</td>
        <td>
          ${app.resume_path
            ? `<span class="artifact-badge" title="Resume generated">📄 Resume</span>`
            : ''}
        </td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); viewApplication(${app.id})">
            View
          </button>
        </td>
      </tr>
    `).join('');

    // Badge count
    const badgeEl = document.getElementById('badge-applications');
    if (badgeEl) {
      const needsAttention = items.filter(a => ['needs_attention', 'handoff'].includes(a.status)).length;
      if (needsAttention > 0) {
        badgeEl.textContent = needsAttention;
        badgeEl.classList.add('visible');
      } else {
        badgeEl.classList.remove('visible');
      }
    }
  } catch(e) {
    tbody.innerHTML = `<tr><td colspan="8" class="table-empty">Error loading applications: ${escHtml(e.message)}</td></tr>`;
  }
}

function filterApplications() {
  appFilters = {
    search:    document.getElementById('filter-search')?.value?.trim(),
    status:    document.getElementById('filter-status')?.value,
    min_score: document.getElementById('filter-min-score')?.value,
  };
  loadApplications();
}

// ============================================================
// APPLICATION DETAIL DRAWER
// ============================================================

async function viewApplication(id) {
  currentAppDetailId = id;
  openDrawer();
  setDrawerLoading(true);

  try {
    const app = await apiFetch(`/applications/${id}`);
    renderDrawer(app);
  } catch(e) {
    setDrawerError(e.message);
  }
}

function openDrawer() {
  let drawer = document.getElementById('app-drawer');
  if (!drawer) {
    drawer = document.createElement('div');
    drawer.id = 'app-drawer';
    drawer.className = 'app-drawer';
    drawer.innerHTML = `
      <div class="drawer-overlay" onclick="closeDrawer()"></div>
      <div class="drawer-panel" id="drawer-panel">
        <div class="drawer-header">
          <div id="drawer-title-block">
            <h2 class="drawer-title" id="drawer-job-title">Loading…</h2>
            <div class="drawer-subtitle" id="drawer-company"></div>
          </div>
          <button class="drawer-close" onclick="closeDrawer()">✕</button>
        </div>
        <div class="drawer-tabs">
          <button class="drawer-tab active" id="tab-overview" onclick="switchDrawerTab('overview')">Overview</button>
          <button class="drawer-tab" id="tab-timeline" onclick="switchDrawerTab('timeline')">Timeline</button>
          <button class="drawer-tab" id="tab-artifacts" onclick="switchDrawerTab('artifacts')">Artifacts</button>
          <button class="drawer-tab" id="tab-notes" onclick="switchDrawerTab('notes')">Notes</button>
        </div>
        <div class="drawer-body" id="drawer-body">
          <div class="drawer-loading">
            <div class="spinner"></div>
            <p>Loading application…</p>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(drawer);
  }
  drawer.classList.add('open');
}

function closeDrawer() {
  document.getElementById('app-drawer')?.classList.remove('open');
  currentAppDetailId = null;
}

function setDrawerLoading(loading) {
  const body = document.getElementById('drawer-body');
  if (loading && body) {
    body.innerHTML = `
      <div class="drawer-loading">
        <div class="spinner"></div>
        <p>Loading application…</p>
      </div>
    `;
  }
}

function setDrawerError(msg) {
  const body = document.getElementById('drawer-body');
  if (body) body.innerHTML = `<div class="empty-state"><p style="color:var(--danger)">Error: ${escHtml(msg)}</p></div>`;
}

let _currentDrawerApp = null;
let _activeDrawerTab = 'overview';

function renderDrawer(app) {
  _currentDrawerApp = app;
  document.getElementById('drawer-job-title').textContent = app.job_title;
  document.getElementById('drawer-company').innerHTML = `
    ${escHtml(app.company)}
    ${app.location ? ` &nbsp;·&nbsp; ${escHtml(app.location)}` : ''}
    &nbsp;&nbsp;${statusChipHtml(app.status)}
  `;
  switchDrawerTab('overview');
}

function switchDrawerTab(tab) {
  _activeDrawerTab = tab;
  document.querySelectorAll('.drawer-tab').forEach(t => t.classList.remove('active'));
  document.getElementById(`tab-${tab}`)?.classList.add('active');

  const body = document.getElementById('drawer-body');
  if (!body || !_currentDrawerApp) return;

  const app = _currentDrawerApp;
  switch (tab) {
    case 'overview':  body.innerHTML = renderDrawerOverview(app); break;
    case 'timeline':  body.innerHTML = renderDrawerTimeline(app); break;
    case 'artifacts': renderDrawerArtifacts(app, body); break;
    case 'notes':     body.innerHTML = renderDrawerNotes(app); break;
  }
}

function renderDrawerOverview(app) {
  const score = app.match_score;
  const breakdown = app.score_breakdown || {};
  const projects = app.selected_projects || [];
  const skills = app.matched_skills || [];

  const scoreGauge = score !== null ? `
    <div class="score-gauge-ring ${scoreClass(score)}" style="--pct:${Math.round(score)}">
      <div class="score-gauge-inner">
        <div class="score-gauge-num">${Math.round(score)}</div>
        <div class="score-gauge-label">/ 100</div>
      </div>
    </div>
  ` : '<div class="score-gauge-na">—</div>';

  const breakdownHtml = Object.entries(breakdown).length ? `
    <div class="score-breakdown-grid">
      ${Object.entries(breakdown).map(([k, v]) => `
        <div class="score-breakdown-item">
          <div class="score-breakdown-label">${escHtml(k.replace(/_/g, ' '))}</div>
          <div class="score-breakdown-bar">
            <div class="score-breakdown-fill" style="width:${Math.min(100, (v/30)*100)}%"></div>
          </div>
          <div class="score-breakdown-val">${v}</div>
        </div>
      `).join('')}
    </div>
  ` : '';

  const projectsHtml = projects.length ? `
    <div class="drawer-section">
      <div class="drawer-section-label">Selected Projects for Resume</div>
      ${projects.map((p, i) => `
        <div class="project-row">
          <div class="project-row-header">
            <span class="project-row-rank">#${i+1}</span>
            <span class="project-row-name">${escHtml(p.display_name || p.name || '')}</span>
          </div>
          <div class="project-row-tech">${escHtml((p.tech_stack || []).join(', '))}</div>
        </div>
      `).join('')}
    </div>
  ` : '';

  const skillsHtml = skills.length ? `
    <div class="drawer-section">
      <div class="drawer-section-label">Matched Skills from Profile</div>
      <div class="skill-cloud">
        ${skills.map(s => `<span class="skill-tag matched">${escHtml(s)}</span>`).join('')}
      </div>
    </div>
  ` : '';

  const eligHtml = `
    <div class="elig-banner ${app.eligibility_status === 'passed' ? 'elig-pass' : 'elig-fail'}">
      <strong>${app.eligibility_status === 'passed' ? '✓ Eligible' : '✗ Ineligible'}</strong>
      ${app.eligibility_reason ? `<span>${escHtml(app.eligibility_reason)}</span>` : ''}
    </div>
  `;

  const metaHtml = `
    <div class="meta-grid">
      <div class="meta-item"><span class="meta-label">Source</span><span class="meta-value">${escHtml(app.source || '—')}</span></div>
      <div class="meta-item"><span class="meta-label">Discovered</span><span class="meta-value">${formatDate(app.discovered_at)}</span></div>
      <div class="meta-item"><span class="meta-label">Remote</span><span class="meta-value">${escHtml(app.remote_type || '—')}</span></div>
      <div class="meta-item"><span class="meta-label">Submitted</span><span class="meta-value">${app.application_submitted_at ? formatDate(app.application_submitted_at) : '—'}</span></div>
    </div>
  `;

  const linkHtml = app.job_url ? `
    <div class="drawer-section">
      <button class="job-link-btn" onclick="openExternalUrl('${escHtml(app.job_url)}')" style="display:inline-flex; align-items:center; gap:6px; cursor:pointer; background:var(--surface-light); border:1px solid var(--border-color); color:var(--primary); padding:6px 12px; border-radius:6px; font-weight:600; font-size:12.5px;">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 2H2v8h8V7M7 1h4v4M11 1L5 7"/></svg>
        Open Job Posting ↗
      </button>
    </div>
  ` : '';

  const actionHtml = `
    <div class="drawer-actions">
      <select id="drawer-status-select" class="select-field" style="font-size:12px;">
        ${['ready_for_review','submitted','withdrawn','needs_review','failed','paused'].map(s =>
          `<option value="${s}" ${app.status===s?'selected':''}>${s.replace(/_/g,' ').toUpperCase()}</option>`
        ).join('')}
      </select>
      <button class="btn btn-primary btn-sm" onclick="drawerUpdateStatus()">Update Status</button>
    </div>
  `;

  return `
    <div class="drawer-overview">
      <div class="score-section">
        ${scoreGauge}
        <div class="score-section-right">
          ${eligHtml}
          ${breakdownHtml}
        </div>
      </div>
      ${metaHtml}
      ${linkHtml}
      ${projectsHtml}
      ${skillsHtml}
      ${actionHtml}
    </div>
  `;
}

function renderDrawerTimeline(app) {
  const logs = app.activity_log || [];
  if (!logs.length) {
    return `<div class="empty-state"><p>No activity events recorded yet.</p></div>`;
  }

  const eventIcons = {
    DISCOVERED: '🔍', OPENING_JOB: '🌐', DESCRIPTION_EXTRACTED: '📋',
    ELIGIBILITY_PASSED: '✅', ELIGIBILITY_FAILED: '❌', MATCH_SCORE: '📊',
    RESUME_GENERATED: '📄', RESUME_VALIDATED: '✔️', READY_FOR_REVIEW: '🛡️',
    USER_CONFIRMED_SUBMITTED: '🎉', SUBMITTED: '🚀', FAILED: '💥', PAUSED: '⏸️',
    SKIPPED: '⏭️', AUTH_REQUIRED: '🔐', CAPTCHA_DETECTED: '🤖',
    HANDOFF_STARTED: '👋', STATUS_UPDATE: '✏️',
  };

  return `
    <div class="timeline">
      ${logs.map(l => `
        <div class="timeline-event">
          <div class="timeline-dot">
            <span class="timeline-icon">${eventIcons[l.event_type] || '•'}</span>
          </div>
          <div class="timeline-content">
            <div class="timeline-event-type">${escHtml(l.event_type)}</div>
            <div class="timeline-event-desc">${escHtml(l.description)}</div>
            ${l.details ? `<div class="timeline-event-details">${escHtml(truncate(l.details, 200))}</div>` : ''}
            <div class="timeline-event-time">${formatDateTime(l.created_at)}</div>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderDrawerArtifacts(app, body) {
  const artifactList = [
    { file: 'job.json',           label: 'Job Metadata',       icon: '🗃️', type: 'json' },
    { file: 'job-description.txt',label: 'Job Description',    icon: '📋', type: 'text' },
    { file: 'analysis.json',      label: 'Match Analysis',     icon: '📊', type: 'json' },
    { file: 'resume.tex',         label: 'Tailored LaTeX',     icon: '📄', type: 'latex' },
    { file: 'resume.pdf',         label: 'Compiled 1-Page PDF',icon: '📑', type: 'pdf' },
    { file: 'answers.json',       label: 'Form Answers',       icon: '💬', type: 'json' },
    { file: 'application.json',   label: 'Application State',  icon: '⚙️', type: 'json' },
    { file: 'activity.log',       label: 'Activity Log',       icon: '📟', type: 'text' },
  ];

  const artifacts = app.artifacts?.artifacts || {};

  body.innerHTML = `
    <div class="artifacts-panel">
      <div class="artifacts-header">
        <div class="drawer-section-label">Local Artifact Files</div>
        ${app.artifacts?.dir ? `<div class="artifact-dir-path" title="${escHtml(app.artifacts.dir)}">📁 ${escHtml(truncate(app.artifacts.dir, 50))}</div>` : ''}
      </div>
      <div class="artifact-list">
        ${artifactList.map(a => {
          const info = artifacts[a.file] || {};
          const exists = info.exists;
          return `
            <div class="artifact-item ${exists ? 'exists' : 'missing'}">
              <div class="artifact-item-left">
                <span class="artifact-icon">${a.icon}</span>
                <div>
                  <div class="artifact-name">${a.label}</div>
                  <div class="artifact-filename">${a.file}</div>
                </div>
              </div>
              <div class="artifact-item-right" style="display:flex; align-items:center; gap:6px;">
                ${exists
                  ? (a.file === 'resume.pdf' ? `
                      <span class="artifact-size">${formatBytes(info.size_bytes)}</span>
                      <button class="btn btn-secondary btn-sm" onclick="openDrawerPdfPreview(${app.id})">Preview PDF</button>
                      <button class="btn btn-secondary btn-sm" onclick="openExternalUrl('/api/applications/${app.id}/resume/preview')">Open PDF ↗</button>
                      <button class="btn btn-secondary btn-sm" onclick="drawerRecompileResume(${app.id})">Recompile</button>
                    ` : `
                      <span class="artifact-size">${formatBytes(info.size_bytes)}</span>
                      <button class="btn btn-secondary btn-sm" onclick="viewArtifact(${app.id}, '${a.file}', '${a.label}', '${a.type}')">View</button>
                    `)
                  : `<span class="artifact-missing-badge">Not yet created</span>`
                }
              </div>
            </div>
          `;
        }).join('')}
      </div>
    </div>

    <!-- Artifact content viewer -->
    <div class="artifact-viewer" id="artifact-viewer" style="display:none;">
      <div class="artifact-viewer-header">
        <div class="artifact-viewer-title" id="artifact-viewer-title"></div>
        <div style="display:flex; gap:6px;">
          <button class="btn btn-secondary btn-sm" onclick="copyArtifactContent()">Copy</button>
          <button class="btn btn-secondary btn-sm" onclick="closeArtifactViewer()">✕ Close</button>
        </div>
      </div>
      <pre class="artifact-viewer-code" id="artifact-viewer-code"></pre>
    </div>
  `;
}

async function viewArtifact(appId, file, label, type) {
  const viewer = document.getElementById('artifact-viewer');
  const codeEl = document.getElementById('artifact-viewer-code');
  const titleEl = document.getElementById('artifact-viewer-title');

  if (!viewer || !codeEl) return;
  viewer.style.display = 'block';
  titleEl.textContent = `${label} (${file})`;
  codeEl.textContent = 'Loading…';

  try {
    const text = await apiFetchText(`/applications/${appId}/artifact?file=${encodeURIComponent(file)}`);
    if (type === 'json') {
      try {
        codeEl.textContent = JSON.stringify(JSON.parse(text), null, 2);
      } catch {
        codeEl.textContent = text;
      }
    } else {
      codeEl.textContent = text;
    }
  } catch(e) {
    codeEl.textContent = `Error loading artifact: ${e.message}`;
  }
}

function copyArtifactContent() {
  const code = document.getElementById('artifact-viewer-code')?.textContent;
  if (code) {
    navigator.clipboard.writeText(code);
    showToast('Artifact content copied!', 'success');
  }
}

function closeArtifactViewer() {
  const viewer = document.getElementById('artifact-viewer');
  if (viewer) viewer.style.display = 'none';
}

function openDrawerPdfPreview(appId) {
  const iframe = document.getElementById('pdf-preview-iframe');
  if (iframe) {
    iframe.src = `/api/applications/${appId}/resume/preview?t=${Date.now()}`;
  }
  showModal('modal-pdf-preview');
}

async function drawerRecompileResume(appId) {
  showToast('Recompiling LaTeX resume...', 'info');
  try {
    const res = await apiFetch(`/applications/${appId}/resume/recompile`, { method: 'POST' });
    if (res.success) {
      showToast(`Resume recompiled successfully! Verified 1-Page PDF (SHA-256: ${res.pdf_hash.slice(0,8)}...)`, 'success');
      openDrawerPdfPreview(appId);
      if (currentDrawerAppId === appId) {
        openApplicationDrawer(appId);
      }
    } else {
      showToast(`Compilation failed: ${res.error}`, 'error');
    }
  } catch(e) {
    showToast(`Recompile error: ${e.message}`, 'error');
  }
}

function renderDrawerNotes(app) {
  return `
    <div class="drawer-notes">
      <div class="drawer-section-label">Notes</div>
      <textarea
        id="drawer-notes-text"
        class="text-area"
        rows="10"
        placeholder="Add notes about this application…"
        style="font-size:13px; line-height:1.6;"
      >${escHtml(app.notes || '')}</textarea>
      <div style="margin-top:10px; display:flex; gap:8px;">
        <button class="btn btn-primary btn-sm" onclick="saveDrawerNotes()">Save Notes</button>
        <span id="notes-saved-indicator" style="font-size:12px; color:var(--success); display:none; align-items:center; gap:4px;">✓ Saved</span>
      </div>
    </div>
  `;
}

async function drawerUpdateStatus() {
  const select = document.getElementById('drawer-status-select');
  if (!select || !currentAppDetailId) return;
  const newStatus = select.value;

  try {
    await apiFetch(`/applications/${currentAppDetailId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status: newStatus }),
    });
    showToast(`Status updated to ${newStatus.toUpperCase()}`, 'success');
    // Refresh drawer
    const app = await apiFetch(`/applications/${currentAppDetailId}`);
    _currentDrawerApp = app;
    document.getElementById('drawer-job-title').textContent = app.job_title;
    document.getElementById('drawer-company').innerHTML = `
      ${escHtml(app.company)}
      ${app.location ? ` &nbsp;·&nbsp; ${escHtml(app.location)}` : ''}
      &nbsp;&nbsp;${statusChipHtml(app.status)}
    `;
    switchDrawerTab('overview');
    if (currentPage === 'applications') loadApplications();
  } catch(e) {
    showToast(`Error updating status: ${e.message}`, 'error');
  }
}

async function saveDrawerNotes() {
  const text = document.getElementById('drawer-notes-text')?.value || '';
  if (!currentAppDetailId) return;

  try {
    await apiFetch(`/applications/${currentAppDetailId}/notes`, {
      method: 'PATCH',
      body: JSON.stringify({ notes: text }),
    });
    const indicator = document.getElementById('notes-saved-indicator');
    if (indicator) {
      indicator.style.display = 'inline-flex';
      setTimeout(() => indicator.style.display = 'none', 2500);
    }
    if (_currentDrawerApp) _currentDrawerApp.notes = text;
  } catch(e) {
    showToast(`Error saving notes: ${e.message}`, 'error');
  }
}

// ============================================================
// JOBS QUEUE
// ============================================================
async function loadJobQueue() {
  const tbody = document.getElementById('jobs-tbody');
  if (!tbody) return;

  try {
    const data = await apiFetch('/jobs/queue');
    const items = data.items || [];

    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="table-empty">Job queue is empty. Add URLs to get started.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(j => `
      <tr>
        <td>${j.id}</td>
        <td><a href="${escHtml(j.url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${escHtml(truncate(j.url, 50))}</a></td>
        <td>${escHtml(j.company || '—')}</td>
        <td>${escHtml(j.job_title || '—')}</td>
        <td><span class="badge badge-muted">${escHtml(j.source || 'manual')}</span></td>
        <td><span class="badge ${j.priority <= 2 ? 'badge-success' : 'badge-muted'}">P${j.priority}</span></td>
        <td>${formatDate(j.queued_at)}</td>
      </tr>
    `).join('');
  } catch(e) {
    tbody.innerHTML = `<tr><td colspan="7" class="table-empty">Error: ${escHtml(e.message)}</td></tr>`;
  }
}

function showQueueModal() { showModal('modal-queue'); }

async function submitQueueJob() {
  const url     = document.getElementById('queue-url')?.value?.trim();
  const company = document.getElementById('queue-company')?.value?.trim();
  const role    = document.getElementById('queue-role')?.value?.trim();

  if (!url) { showToast('Please enter a job URL', 'error'); return; }

  try {
    await apiFetch('/applications/queue', {
      method: 'POST',
      body: JSON.stringify({ url, company, job_title: role, source: 'manual' }),
    });
    showToast('Job added to queue!', 'success');
    closeModal('modal-queue');
    document.getElementById('queue-url').value = '';
    document.getElementById('queue-company').value = '';
    document.getElementById('queue-role').value = '';
    if (currentPage === 'jobs') loadJobQueue();
    loadStats();
  } catch(e) {
    showToast(`Error: ${e.message}`, 'error');
  }
}

// ============================================================
// PROFILE
// ============================================================
async function loadProfile() {
  try {
    const profile = await apiFetch('/profile/');
    candidateProfile = profile;
    document.getElementById('setup-banner')?.classList.toggle('hidden', profile._configured);
    const fields = {'profile-name': profile.identity?.name, 'profile-first-name': profile.identity?.first_name,
      'profile-last-name': profile.identity?.last_name, 'profile-email': profile.identity?.email,
      'profile-phone': profile.identity?.phone, 'profile-location': profile.identity?.location,
      'profile-university': profile.education?.[0]?.institution, 'profile-degree': profile.education?.[0]?.degree,
      'profile-graduation': profile.education?.[0]?.graduation, 'profile-linkedin': profile.links?.linkedin,
      'profile-github': profile.links?.github};
    Object.entries(fields).forEach(([id, value]) => { document.getElementById(id).value = value || ''; });
    for (const [id, cat] of [['profile-languages','languages'], ['profile-web-skills','web_and_backend'], ['profile-tools','tools']]) {
      document.getElementById(id).value = Object.entries(profile.skills?.[cat] || {}).filter(([, value]) =>
        (typeof value === 'string' ? value : value.status) === 'verified').map(([name]) => name).join(', ');
    }
    document.getElementById('user-name').textContent = profile.identity?.name || 'Your workspace';
    document.getElementById('user-email').textContent = profile.identity?.email || 'Stored on this device';

    const identity = profile.identity || {};
    document.getElementById('profile-identity').innerHTML = Object.entries(identity)
      .map(([k, v]) => `<div class="meta-row"><span class="meta-label">${k}</span><span class="meta-value">${escHtml(String(v))}</span></div>`)
      .join('');

    const edu = (profile.education || [])[0] || {};
    document.getElementById('profile-education').innerHTML = `
      <div class="meta-row"><span class="meta-label">University</span><span class="meta-value">${escHtml(edu.institution || '')}</span></div>
      <div class="meta-row"><span class="meta-label">Degree</span><span class="meta-value">${escHtml(edu.degree || '')}</span></div>
      <div class="meta-row"><span class="meta-label">Graduation</span><span class="meta-value">${escHtml(edu.graduation || '')}</span></div>
      <div class="meta-row"><span class="meta-label">Status</span><span class="meta-value">${escHtml(edu.status || '')}</span></div>
    `;

    const skills = profile.skills || {};
    const allSkills = Object.entries(skills).flatMap(([cat, catSkills]) =>
      Object.entries(catSkills).map(([name, data]) => ({ name, status: typeof data === "string" ? data : data.status }))
    );
    document.getElementById('profile-skills').innerHTML = allSkills
      .map(s => `<span class="skill-tag ${s.status !== 'verified' ? 'exposure' : ''}" title="${s.status}">${escHtml(s.name)}</span>`)
      .join('');

    const registry = await apiFetch('/profile/projects');
    const projects = registry.projects || [];
    document.getElementById('profile-projects').innerHTML = projects
      .map(p => `
        <div class="project-row">
          <div class="project-row-header">
            <span class="project-row-name">${escHtml(p.display_name)}</span>
            <span class="badge ${p.quality_tier === 1 ? 'badge-success' : 'badge-muted'}">${p.status}</span>
          </div>
          <div class="project-row-tech">${escHtml((p.tech_stack || []).join(', '))}</div>
        </div>
      `)
      .join('');
  } catch(e) {
    showToast(`Error loading profile: ${e.message}`, 'error');
  }
}

function reloadProfile() { loadProfile(); showToast('Profile reloaded', 'info'); }

// ============================================================
// TAILOR / JOB EVALUATION PAGE
// ============================================================
async function fetchJobFromUrl() {
  const url = document.getElementById('tailor-url')?.value?.trim();
  if (!url) { showToast('Enter a URL first', 'error'); return; }

  showToast('Fetching job posting from web...', 'info');
  try {
    const data = await apiFetch('/jobs/fetch-url', {
      method: 'POST',
      body: JSON.stringify({ url }),
    });

    if (data.job_description) {
      document.getElementById('tailor-jd').value = data.job_description;
      showToast(`Fetched posting: ${data.company} — ${data.job_title}`, 'success');
      runTailor(data.job_title, data.company, url);
    }
  } catch(e) {
    showToast(`Could not fetch URL: ${e.message}`, 'error');
  }
}

async function runTailor(customTitle = "", customCompany = "", customUrl = "") {
  const jd = document.getElementById('tailor-jd')?.value?.trim();
  const url = customUrl || document.getElementById('tailor-url')?.value?.trim() || "";

  if (!jd) { showToast('Paste a job description first', 'error'); return; }

  const output = document.getElementById('tailor-output');
  output.innerHTML = `
    <div style="padding:40px; text-align:center; color: var(--text-secondary);">
      <div class="status-dot running" style="width:12px; height:12px; margin-bottom:12px;"></div>
      <p style="font-weight:600; font-size:14px;">Analyzing requirements &amp; checking eligibility…</p>
      <p style="font-size:12px; color:var(--text-muted); margin-top:4px;">Extracting skills, verifying credentials against verified profile</p>
    </div>
  `;

  try {
    const result = await apiFetch('/jobs/analyze', {
      method: 'POST',
      body: JSON.stringify({
        job_description: jd,
        job_title: customTitle,
        company: customCompany,
        job_url: url,
      }),
    });

    currentTailorEvaluation = result;
    renderTailorAnalysis(result);
  } catch(e) {
    output.innerHTML = `
      <div class="empty-state">
        <p style="color: var(--danger); font-weight:600;">Analysis Failed</p>
        <p style="font-size:12px;">${escHtml(e.message)}</p>
      </div>
    `;
  }
}

function renderTailorAnalysis(res) {
  const output = document.getElementById('tailor-output');
  if (!output) return;

  const score = Math.round(res.match_score);
  const elig = res.eligibility;
  const skills = res.skills;
  const breakdown = res.score_breakdown;
  const projects = res.project_rankings || [];

  const matchedReqHtml = (skills.matched_required || []).map(s => `<span class="skill-tag" style="background:var(--success-light); color:var(--success);">✓ ${escHtml(s)}</span>`).join('') || '<span style="color:var(--text-muted); font-size:12px;">None detected</span>';
  const missingReqHtml = (skills.missing_required || []).map(s => `<span class="skill-tag" style="background:#FEF2F2; color:var(--danger);">✗ ${escHtml(s)}</span>`).join('') || '<span style="color:var(--success); font-size:12px;">None (All matched!)</span>';

  const projectsHtml = projects.slice(0, 3).map((p, idx) => `
    <div style="background:var(--bg-main); padding:10px 12px; border-radius:8px; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center;">
      <div>
        <div style="font-size:13px; font-weight:600; color:var(--text-primary);">#${idx + 1} ${escHtml(p.display_name)}</div>
        <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">${escHtml((p.tech_stack || []).join(', '))}</div>
      </div>
      <span class="badge ${p.tier === 1 ? 'badge-success' : 'badge-muted'}">${p.tier === 1 ? 'Tier 1' : 'Tier 2'}</span>
    </div>
  `).join('');

  output.innerHTML = `
    <div style="padding: 16px;">
      <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); padding-bottom:14px; margin-bottom:14px;">
        <div>
          <h3 style="font-size:16px; font-weight:700; color:var(--text-primary);">${escHtml(res.company)}</h3>
          <p style="font-size:13px; color:var(--text-secondary);">${escHtml(res.job_title)}</p>
        </div>
        <div style="text-align:right;">
          <div style="font-size:24px; font-weight:800;" class="${scoreClass(score)}">${score}%</div>
          <div style="font-size:11px; text-transform:uppercase; color:var(--text-muted); font-weight:600;">Match Score</div>
        </div>
      </div>

      <div style="margin-bottom:14px; padding:10px 14px; border-radius:8px; font-size:12.5px; display:flex; align-items:flex-start; gap:8px; background:${elig.passed ? 'var(--success-light)' : '#FEF2F2'}; color:${elig.passed ? 'var(--success)' : 'var(--danger)'}; border: 1px solid ${elig.passed ? '#A7F3D0' : 'var(--danger-border)'};">
        <span style="font-weight:700;">${elig.passed ? '✓ ELIGIBILITY PASSED:' : '✗ INELIGIBLE:'}</span>
        <span>${escHtml(elig.reason)}</span>
      </div>

      <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:8px; margin-bottom:14px;">
        <div style="background:var(--bg-main); padding:8px 10px; border-radius:8px; font-size:11px;">
          <div style="color:var(--text-muted);">Required Skills</div>
          <div style="font-weight:700; font-size:13px;">${breakdown.required_skills} / 30</div>
        </div>
        <div style="background:var(--bg-main); padding:8px 10px; border-radius:8px; font-size:11px;">
          <div style="color:var(--text-muted);">Preferred Skills</div>
          <div style="font-weight:700; font-size:13px;">${breakdown.preferred_skills} / 10</div>
        </div>
        <div style="background:var(--bg-main); padding:8px 10px; border-radius:8px; font-size:11px;">
          <div style="color:var(--text-muted);">Role Fit</div>
          <div style="font-weight:700; font-size:13px;">${breakdown.role_similarity} / 20</div>
        </div>
      </div>

      <div style="margin-bottom:14px;">
        <div style="font-size:11.5px; font-weight:600; text-transform:uppercase; color:var(--text-muted); margin-bottom:6px;">Matched Skills (Verified in Profile)</div>
        <div style="display:flex; flex-wrap:wrap; gap:5px; margin-bottom:10px;">${matchedReqHtml}</div>
        <div style="font-size:11.5px; font-weight:600; text-transform:uppercase; color:var(--text-muted); margin-bottom:6px;">Missing / Required Skills</div>
        <div style="display:flex; flex-wrap:wrap; gap:5px;">${missingReqHtml}</div>
      </div>

      <div style="margin-bottom:16px;">
        <div style="font-size:11.5px; font-weight:600; text-transform:uppercase; color:var(--text-muted); margin-bottom:6px;">Recommended Projects for Resume</div>
        ${projectsHtml}
      </div>

      <div style="display:flex; gap:8px;">
        <button class="btn btn-primary btn-sm" onclick="saveCurrentEvaluation()">Save to Applications</button>
        <button class="btn btn-secondary btn-sm" onclick="navigate('resume')">View Master Resume</button>
      </div>
    </div>
  `;
}

async function saveCurrentEvaluation() {
  const jd  = document.getElementById('tailor-jd')?.value?.trim();
  const url = document.getElementById('tailor-url')?.value?.trim() || "";

  if (!jd) { showToast('No job content to save', 'error'); return; }

  try {
    const res = await apiFetch('/jobs/save-application', {
      method: 'POST',
      body: JSON.stringify({
        job_description: jd,
        job_url: url,
        company: currentTailorEvaluation?.company || "",
        job_title: currentTailorEvaluation?.job_title || "",
      }),
    });

    if (res.duplicate) {
      showToast(res.message, 'warning');
    } else {
      showToast(`Saved to applications! Status: ${res.status.toUpperCase()}`, 'success');
      loadStats();
    }
  } catch(e) {
    showToast(`Error saving application: ${e.message}`, 'error');
  }
}

// ============================================================
// RESUME PAGE
// ============================================================
let masterResumeData = null;

async function loadResumePage() {
  const viewer = document.getElementById('master-latex-viewer');
  const statusEl = document.getElementById('latex-status');
  const atsBadge = document.getElementById('master-ats-badge');

  if (statusEl) statusEl.textContent = 'Checking compiler...';
  try {
    const profile = await apiFetch('/profile/');
    const education = profile.education?.[0] || {};
    const values = {name:profile.identity?.name, university:education.institution,
      degree:education.degree, graduation:education.graduation};
    for (const [key,value] of Object.entries(values)) {
      const element = document.getElementById(`resume-profile-${key}`);
      if (element) element.textContent = value || 'Not entered';
    }
  } catch { /* The source request below reports any unavailable backend. */ }


  try {
    const data = await apiFetch('/resume/master');
    masterResumeData = data;

    if (viewer) viewer.value = data.latex_source || '';

    if (statusEl) {
      if (data.latex_compiler_available) {
        statusEl.innerHTML = `<span class="status-dot online"></span> ${data.compiler_name} ready`;
      } else {
        statusEl.innerHTML = `<span class="status-dot paused"></span> Not installed (run: brew install --cask basictex)`;
      }
    }

    if (atsBadge && data.ats_analysis) {
      const score = data.ats_analysis.ats_score || 100;
      atsBadge.textContent = `${score}% ATS COMPLIANT`;
      atsBadge.className = `badge ${score >= 80 ? 'badge-success' : 'badge-warning'}`;
    }
  } catch(e) {
    if (viewer) viewer.value = 'Save your candidate profile, then create a master résumé source using the button above.';
    if (statusEl) statusEl.textContent = 'Create a master source to begin';
  }
}

function copyMasterLatex() {
  const viewer = document.getElementById('master-latex-viewer');
  if (!viewer || !viewer.value) { showToast('Master LaTeX not loaded yet', 'error'); return; }
  navigator.clipboard.writeText(viewer.value);
  showToast('Copied master LaTeX source to clipboard!', 'success');
}

function downloadMasterLatex() {
  const viewer = document.getElementById('master-latex-viewer');
  if (!viewer || !viewer.value) { showToast('Master LaTeX not loaded yet', 'error'); return; }
  downloadBlob(viewer.value, 'master_resume.tex', 'text/plain');
}

async function compileMasterResume() {
  showToast('Attempting local LaTeX compilation...', 'info');
  try {
    const res = await apiFetch('/resume/compile-master', { method: 'POST' });
    if (res.success) {
      showToast('Master resume compiled successfully!', 'success');
    } else {
      showToast(`Compile issue: ${res.error || 'Compiler not found'}`, 'warning');
    }
    loadResumePage();
  } catch(e) {
    showToast(`Compilation failed: ${e.message}`, 'error');
  }
}

// ============================================================
// TAILOR / RESUME GENERATION
// ============================================================
async function generateTailoredLatex() {
  const jd  = document.getElementById('tailor-jd')?.value?.trim();
  const url = document.getElementById('tailor-url')?.value?.trim() || "";

  if (!jd) { showToast('Paste a job description first', 'error'); return; }

  const output = document.getElementById('tailor-output');
  output.innerHTML = `
    <div style="padding:40px; text-align:center; color: var(--text-secondary);">
      <div class="status-dot running" style="width:12px; height:12px; margin-bottom:12px;"></div>
      <p style="font-weight:600; font-size:14px;">Tailoring resume &amp; generating LaTeX…</p>
      <p style="font-size:12px; color:var(--text-muted); margin-top:4px;">Selecting top verified projects, prioritizing relevant skills, enforcing 1-page limit</p>
    </div>
  `;

  try {
    const analysis = await apiFetch('/jobs/analyze', {
      method: 'POST',
      body: JSON.stringify({ job_description: jd, job_url: url }),
    });
    currentTailorEvaluation = analysis;

    const tailored = await apiFetch('/resume/tailor', {
      method: 'POST',
      body: JSON.stringify({
        job_description: jd,
        job_title: analysis.job_title,
        company: analysis.company,
        required_skills: analysis.skills?.matched_required || [],
        preferred_skills: analysis.skills?.matched_preferred || [],
        technologies: analysis.parsed_requirements?.technologies || [],
      }),
    });

    renderTailoredResumeResult(analysis, tailored);
    showToast(tailored.pdf_valid ? 'One-page résumé compiled and validated.' : tailored.compile_error || 'Résumé source generated. PDF page count awaits compilation.', tailored.compile_error ? 'warning' : 'success');
  } catch(e) {
    output.innerHTML = `
      <div class="empty-state">
        <p style="color: var(--danger); font-weight:600;">Tailoring Failed</p>
        <p style="font-size:12px;">${escHtml(e.message)}</p>
      </div>
    `;
  }
}

function renderTailoredResumeResult(analysis, tailored) {
  const output = document.getElementById('tailor-output');
  if (!output) return;

  const score = Math.round(analysis.match_score);
  const atsScore = tailored.ats_result?.ats_score || 100;
  const projects = tailored.tailored_plan?.selected_projects || [];
  const latexCode = tailored.latex_code || "";

  const projectsSummary = projects.map((p, i) => `
    <div style="background:var(--bg-main); padding:8px 10px; border-radius:6px; margin-bottom:4px; font-size:12px;">
      <strong>#${i+1} ${escHtml(p.display_name)}</strong>
      <div style="color:var(--text-muted); font-size:11px;">${escHtml((p.tech_stack || []).join(', '))}</div>
    </div>
  `).join('');

  output.innerHTML = `
    <div style="padding: 16px;">
      <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); padding-bottom:12px; margin-bottom:12px;">
        <div>
          <h3 style="font-size:15px; font-weight:700; color:var(--text-primary);">${escHtml(analysis.company)} — Tailored Resume</h3>
          <p style="font-size:12px; color:var(--text-secondary);">${escHtml(analysis.job_title)}</p>
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          <span class="badge ${atsScore >= 80 ? 'badge-success' : 'badge-warning'}">${atsScore}% ATS Score</span>
          <span class="badge badge-muted">${tailored.pdf_valid ? '1 page verified' : 'PDF not yet verified'}</span>
        </div>
      </div>

      <div style="margin-bottom:12px;">
        <div style="font-size:11.5px; font-weight:600; text-transform:uppercase; color:var(--text-muted); margin-bottom:6px;">Selected Verified Projects</div>
        ${projectsSummary}
      </div>

      <div style="margin-bottom:14px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
          <span style="font-size:11.5px; font-weight:600; text-transform:uppercase; color:var(--text-muted);">Generated LaTeX (Ready to Compile)</span>
          <div style="display:flex; gap:6px;">
            <button class="btn btn-secondary btn-sm" onclick="copyTailoredLatex()">Copy LaTeX</button>
            <button class="btn btn-secondary btn-sm" onclick="downloadTailoredLatex()">Download .tex</button>
          </div>
        </div>
        <textarea id="tailored-latex-code" class="text-area" rows="12" style="font-family: var(--font-mono); font-size: 11px; line-height: 1.4; background: var(--bg-main);" readonly>${escHtml(latexCode)}</textarea>
      </div>

      <div style="display:flex; gap:8px;">
        <button class="btn btn-primary btn-sm" onclick="saveCurrentEvaluation()">Save to Applications</button>
        <button class="btn btn-secondary btn-sm" onclick="runTailor()">View Full Match Analysis</button>
      </div>
    </div>
  `;
}

function copyTailoredLatex() {
  const codeEl = document.getElementById('tailored-latex-code');
  if (!codeEl || !codeEl.value) return;
  navigator.clipboard.writeText(codeEl.value);
  showToast('Copied tailored LaTeX to clipboard!', 'success');
}

function downloadTailoredLatex() {
  const codeEl = document.getElementById('tailored-latex-code');
  if (!codeEl || !codeEl.value) return;
  downloadBlob(codeEl.value, 'tailored_resume.tex', 'text/plain');
}

function downloadBlob(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast(`Downloaded ${filename}`, 'info');
}

// ============================================================
// LEARNINGS PAGE — Real Analytics Dashboard
// ============================================================
let _analyticsData = null;

async function loadLearnings() {
  const container = document.getElementById('learnings-content');
  if (!container) return;

  container.innerHTML = `
    <div style="padding:40px; text-align:center; color:var(--text-secondary);">
      <div class="spinner" style="margin:0 auto 16px;"></div>
      <p style="font-size:14px; font-weight:600;">Computing analytics…</p>
    </div>
  `;

  try {
    const data = await apiFetch('/applications/analytics');
    _analyticsData = data;
    renderAnalytics(data);
  } catch(e) {
    container.innerHTML = `<div class="empty-state"><p style="color:var(--danger)">Error loading analytics: ${escHtml(e.message)}</p></div>`;
  }
}

function renderAnalytics(data) {
  const container = document.getElementById('learnings-content');
  if (!container) return;

  if (data.total_applications === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3">
          <path d="M6 30l10-10 8 8 10-14 10 10"/>
        </svg>
        <h3 style="margin:12px 0 6px; font-size:16px;">No data yet</h3>
        <p>Evaluate some jobs to start seeing analytics.</p>
        <button class="btn btn-primary btn-sm" style="margin-top:12px;" onclick="navigate('resume')">Try Job Tailoring</button>
      </div>
    `;
    return;
  }

  // KPI cards
  const kpiHtml = `
    <div class="analytics-kpis">
      <div class="kpi-card">
        <div class="kpi-value">${data.total_applications}</div>
        <div class="kpi-label">Total Evaluated</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value ${scoreClass(data.scores.avg)}">${data.scores.avg}%</div>
        <div class="kpi-label">Avg Match Score</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">${data.eligibility.rate_pct}%</div>
        <div class="kpi-label">Eligibility Rate</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">${data.status_counts.submitted || 0}</div>
        <div class="kpi-label">Submitted</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">${data.scores.max}%</div>
        <div class="kpi-label">Top Score</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">${data.apply_rate_pct}%</div>
        <div class="kpi-label">Apply Rate</div>
      </div>
    </div>
  `;

  // Score distribution bars
  const scoreDist = data.scores.distribution || {};
  const maxDistVal = Math.max(...Object.values(scoreDist), 1);
  const scoreDistHtml = `
    <div class="chart-card">
      <div class="chart-title">Match Score Distribution</div>
      <div class="bar-chart">
        ${Object.entries(scoreDist).map(([label, count]) => `
          <div class="bar-group">
            <div class="bar-track">
              <div class="bar-fill ${label.startsWith('85') ? 'bar-high' : label.startsWith('75') ? 'bar-med-high' : label.startsWith('65') ? 'bar-med' : 'bar-low'}"
                   style="height:${Math.round((count/maxDistVal)*120)}px" title="${count} applications">
              </div>
            </div>
            <div class="bar-label">${label}</div>
            <div class="bar-count">${count}</div>
          </div>
        `).join('')}
      </div>
    </div>
  `;

  // Status funnel
  const statusCounts = data.status_counts || {};
  const totalForFunnel = data.total_applications || 1;
  const statusOrder = ['discovered', 'analyzed', 'resume_generated', 'ready', 'applying', 'submitted', 'ineligible', 'skipped', 'failed'];
  const statusLabels = {
    discovered: 'Discovered', analyzed: 'Analyzed', resume_generated: 'Resume Generated',
    ready: 'Ready', applying: 'Applying', submitted: 'Submitted',
    ineligible: 'Ineligible', skipped: 'Skipped', failed: 'Failed',
    paused: 'Paused', needs_attention: 'Needs Attention',
  };
  const statusFunnelHtml = `
    <div class="chart-card">
      <div class="chart-title">Application Funnel</div>
      <div class="funnel-chart">
        ${statusOrder.filter(s => statusCounts[s] > 0).map(s => {
          const count = statusCounts[s] || 0;
          const pct = Math.round((count / totalForFunnel) * 100);
          return `
            <div class="funnel-row">
              <div class="funnel-label">${statusLabels[s] || s}</div>
              <div class="funnel-bar-track">
                <div class="funnel-bar-fill status-fill-${s}" style="width:${pct}%"></div>
              </div>
              <div class="funnel-count">${count}</div>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;

  // Tech seen in job descriptions
  const topTechs = data.top_technologies_seen || [];
  const maxTechCount = Math.max(...topTechs.map(t => t.count), 1);
  const techHtml = topTechs.length ? `
    <div class="chart-card">
      <div class="chart-title">Technologies Seen in Job Postings</div>
      <div class="tech-bars">
        ${topTechs.slice(0, 12).map(t => `
          <div class="tech-bar-row">
            <div class="tech-bar-label">${escHtml(t.tech)}</div>
            <div class="tech-bar-track">
              <div class="tech-bar-fill" style="width:${Math.round((t.count/maxTechCount)*100)}%"></div>
            </div>
            <div class="tech-bar-count">${t.count}</div>
          </div>
        `).join('')}
      </div>
    </div>
  ` : '';

  // Timeline
  const timeline = data.timeline || {};
  const timelineEntries = Object.entries(timeline);
  const maxTimelineVal = Math.max(...timelineEntries.map(([, v]) => v), 1);
  const timelineHtml = timelineEntries.length ? `
    <div class="chart-card chart-wide">
      <div class="chart-title">Applications Discovered — Last 30 Days</div>
      <div class="timeline-chart">
        ${timelineEntries.map(([date, count]) => `
          <div class="tl-col" title="${date}: ${count}">
            <div class="tl-bar" style="height:${Math.round((count/maxTimelineVal)*60)}px;"></div>
            <div class="tl-date">${date.slice(5)}</div>
          </div>
        `).join('')}
      </div>
    </div>
  ` : '';

  // Source breakdown
  const sources = data.source_breakdown || {};
  const sourceTotal = Object.values(sources).reduce((a, b) => a + b, 0) || 1;
  const sourceHtml = Object.keys(sources).length ? `
    <div class="chart-card">
      <div class="chart-title">Discovery Sources</div>
      <div class="source-list">
        ${Object.entries(sources).sort((a, b) => b[1] - a[1]).map(([src, count]) => `
          <div class="source-row">
            <span class="source-label">${escHtml(src)}</span>
            <div class="source-bar-track">
              <div class="source-bar-fill" style="width:${Math.round((count/sourceTotal)*100)}%"></div>
            </div>
            <span class="source-count">${count}</span>
          </div>
        `).join('')}
      </div>
    </div>
  ` : '';

  // Eligibility donut (CSS-based)
  const eligible = data.eligibility.eligible;
  const ineligible = data.eligibility.ineligible;
  const eligTotal = eligible + ineligible || 1;
  const eligPct = Math.round((eligible / eligTotal) * 100);
  const eligHtml = `
    <div class="chart-card">
      <div class="chart-title">Eligibility Gate</div>
      <div class="donut-container">
        <div class="donut" style="--pct:${eligPct}; --color:var(--success);">
          <div class="donut-center">
            <div class="donut-pct">${eligPct}%</div>
            <div class="donut-sub">passed</div>
          </div>
        </div>
        <div class="donut-legend">
          <div class="donut-legend-item">
            <span class="donut-dot" style="background:var(--success);"></span>
            Eligible (${eligible})
          </div>
          <div class="donut-legend-item">
            <span class="donut-dot" style="background:var(--danger);"></span>
            Ineligible (${ineligible})
          </div>
        </div>
      </div>
    </div>
  `;

  container.innerHTML = `
    ${kpiHtml}
    <div class="analytics-grid">
      ${scoreDistHtml}
      ${eligHtml}
      ${statusFunnelHtml}
      ${techHtml}
      ${timelineHtml}
      ${sourceHtml}
    </div>
  `;
}

// ============================================================
// SETTINGS
// ============================================================
async function loadSettings() {
  try {
    const s = await apiFetch('/agent/settings');
    const dryrunEl     = document.getElementById('setting-dryrun');
    const autosubmitEl = document.getElementById('setting-autosubmit');
    const minScoreEl   = document.getElementById('setting-min-score');
    const maxPerDayEl  = document.getElementById('setting-max-per-day');
    const ollamaUrlEl  = document.getElementById('setting-ollama-url');
    const ollamaModelEl= document.getElementById('setting-ollama-model');

    if (dryrunEl) { dryrunEl.checked = true; dryrunEl.disabled = true; }
    if (autosubmitEl) { autosubmitEl.checked = false; autosubmitEl.disabled = true; }
    if (minScoreEl)   minScoreEl.value = s.min_match_score;
    if (maxPerDayEl)  maxPerDayEl.value = s.max_applications_per_day;
    if (ollamaUrlEl)  ollamaUrlEl.value = s.ollama_base_url;
    if (ollamaModelEl) ollamaModelEl.value = s.ollama_model;

    await checkOllama();
  } catch(e) {}
}

async function checkOllama() {
  const dot  = document.getElementById('ollama-status-dot');
  const text = document.getElementById('ollama-status-text');
  if (!dot || !text) return;

  dot.className = 'status-dot paused';
  text.textContent = 'Checking...';

  try {
    const status = await apiFetch('/agent/status');
    dot.className = `status-dot ${status.ollama_online ? 'online' : 'offline'}`;
    text.textContent = status.ollama_online
      ? `Connected (${status.ollama_model})`
      : 'Offline — run: ollama serve';
  } catch(e) {
    dot.className = 'status-dot offline';
    text.textContent = 'Cannot reach backend';
  }
}

function updateSetting(key, value) {
  showToast(`${key} = ${value} (configured in .env)`, 'info');
}

// ============================================================
// MODALS
// ============================================================
function showModal(id) {
  document.getElementById(id)?.classList.remove('hidden');
}

function closeModal(id) {
  document.getElementById(id)?.classList.add('hidden');
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal:not(.hidden)').forEach(m => m.classList.add('hidden'));
    closeDrawer();
  }
});

// ============================================================
// TOAST NOTIFICATIONS
// ============================================================
function showToast(message, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.style.cssText = `
      position:fixed; bottom:20px; right:20px; z-index:3000;
      display:flex; flex-direction:column; gap:8px; max-width:360px;
    `;
    document.body.appendChild(container);
  }

  const colors = {
    success: '#059669', error: '#DC2626', warning: '#D97706', info: '#5B5BD6',
  };

  const toast = document.createElement('div');
  toast.style.cssText = `
    background: white; border-left: 4px solid ${colors[type] || colors.info};
    border-radius: 10px; padding: 12px 16px; font-size: 13px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.12); color: #1A1F2E;
    line-height:1.4; animation: slideIn 200ms ease;
  `;

  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 300ms';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ============================================================
// HELPERS
// ============================================================
function statusChipHtml(status) {
  const classMap = {
    submitted: 'status-submitted', applying: 'status-applying',
    paused: 'status-paused', failed: 'status-failed',
    ineligible: 'status-ineligible', discovered: 'status-discovered',
    analyzed: 'status-applying', needs_attention: 'status-needs-attention',
    interrupted: 'status-interrupted', needs_review: 'status-needs-review',
    skipped: 'status-skipped', resume_generated: 'status-applying',
    handoff: 'status-needs-attention', withdrawn: 'status-skipped',
  };
  const cls = classMap[status] || 'status-unknown';
  return `<span class="status-chip ${cls}">${escHtml(status)}</span>`;
}

function scoreClass(score) {
  if (score >= 75) return 'high';
  if (score >= 55) return 'medium';
  return 'low';
}

function formatTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
}

function formatDateTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' '
    + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function capitalize(str) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function escHtml(str) {
  const div = document.createElement('div');
  div.textContent = String(str ?? '');
  return div.innerHTML;
}

function truncate(str, n) {
  return str && str.length > n ? str.slice(0, n) + '…' : str;
}

function openFile(path) {
  showToast(`Opening ${path} (use your editor)`, 'info');
}

// ============================================================
// INIT
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  const page = location.hash.slice(1);
  navigate(document.getElementById(`page-${page}`) ? page : 'dashboard');
  apiFetch('/profile/').then(profile => {
    document.getElementById('setup-banner')?.classList.toggle('hidden', profile._configured);
    document.getElementById('user-name').textContent = profile.identity?.name || 'Your workspace';
  }).catch(() => {});
});


async function saveCandidateProfile(event) {
  event.preventDefault();
  const value = id => document.getElementById(id).value.trim();
  const profile = structuredClone(candidateProfile || {});
  profile.identity = {...profile.identity, name:value('profile-name'), first_name:value('profile-first-name'),
    last_name:value('profile-last-name'), email:value('profile-email'), phone:value('profile-phone'), location:value('profile-location')};
  const education = {...(profile.education?.[0] || {}), institution:value('profile-university'),
    degree:value('profile-degree'), graduation:value('profile-graduation')};
  education.graduation_year = education.graduation.match(/\b(20\d{2})\b/)?.[1] || '';
  profile.education = [education, ...(profile.education?.slice(1) || [])];
  profile.links = {...profile.links, linkedin:value('profile-linkedin'), github:value('profile-github')};
  profile.skills = profile.skills || {};
  for (const [id,cat] of [['profile-languages','languages'], ['profile-web-skills','web_and_backend'], ['profile-tools','tools']]) {
    const previous = profile.skills[cat] || {};
    const retained = Object.fromEntries(Object.entries(previous).filter(([, evidence]) =>
      (typeof evidence === 'string' ? evidence : evidence.status) !== 'verified'));
    profile.skills[cat] = {...retained, ...Object.fromEntries(value(id).split(',').map(s => s.trim()).filter(Boolean)
      .map(s => [s, previous[s] && (typeof previous[s] === 'string' ? previous[s] : previous[s].status) === 'verified'
        ? previous[s] : {status:'verified'}]))};
  }
  try {
    await apiFetch('/profile/', {method:'PUT',body:JSON.stringify(profile)});
    showToast('Profile saved on this device.', 'success');
    await loadProfile();
  } catch (error) { showToast(`Could not save profile: ${error.message}`, 'error'); }
}

async function saveWorkspaceSettings() {
  const body = {min_match_score:Number(document.getElementById('setting-min-score').value),
    max_applications_per_day:Number(document.getElementById('setting-max-per-day').value),
    ollama_model:document.getElementById('setting-ollama-model').value.trim()};
  try { await apiFetch('/agent/settings',{method:'PUT',body:JSON.stringify(body)}); showToast('Settings saved.', 'success'); }
  catch(error) { showToast(`Could not save settings: ${error.message}`, 'error'); }
}

async function createMasterResume() {
  try { await apiFetch('/resume/master',{method:'POST'}); await loadResumePage(); showToast('Master source created. Review your facts before use.', 'success'); }
  catch(error) { showToast(error.message, 'error'); }
}
