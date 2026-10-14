# WorkLikeADog

A local job search companion: discover opportunities, compare them with verified experience, prepare tailored résumés, and organize applications for human review.

**[Website](https://swopnab.github.io/worklikejeff/) · [Interactive demo](https://swopnab.github.io/worklikejeff/demo.html) · [Architecture](docs/ARCHITECTURE.md)**

The public demo uses fictional jobs and browser storage. The full Python application runs on your computer and stores your profile, application records, and documents locally. It never auto-submits applications.

## Quick start

Requires **Python 3.11+**. Run these commands from the repository root:

```sh
git clone https://github.com/Swopnab/worklikejeff.git
cd worklikejeff
python3 setup.py
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

On Windows, use `.venv\Scripts\python.exe` in place of `.venv/bin/python`. Open **http://127.0.0.1:8000**, go to **Candidate Profile**, and save your information. Only enter skills you can substantiate. Your private profile is created locally and ignored by Git.

1. Review `profile/project_registry.json`. It contains the repository owner's verified projects; replace it with your own evidence if using this for another candidate.
2. Save your profile, education, links, and verified skills in the dashboard. Additional profile fields can be edited in the ignored `profile/master_profile.json` using the example schema.
3. Open **Résumé**, create a master source from your profile, and review it. An existing master source is never overwritten by that action.
4. Paste a job description into **Job Queue** to analyze it. Review eligibility, fit, and missing skills before preparing an application.
5. Install a local TeX compiler to produce PDFs. A document is ready only after it compiles and passes one-page, text, and section checks.
6. Review all artifacts and answers. Sign-in, MFA, CAPTCHA, legal answers, and final submission require your intervention.

For an environment without browser preparation, use `python3 setup.py --skip-browser`. Chromium can be added later with `.venv/bin/python -m playwright install chromium`.

## What's implemented

- Responsive dashboard with application history, filters, details, activity logs, analytics, and a persistent local profile/settings editor.
- Integrated Personal Job Tracker: application editing, list/board views, all 11 stages, follow-ups, search/sorting, bulk actions, compatible JSON backups, and versioned local database saves.
- Manual URL/description import; GitHub feeds and Greenhouse/Lever board discovery. Some sources depend on third-party access and may return no results.
- Local Ollama job parsing and résumé planning, with deterministic fallback when the model is unavailable.
- Eligibility review, deterministic match scoring, fingerprint deduplication, verified project selection, and a permanent project blacklist.
- LaTeX résumé generation, ATS source checks, PDF compilation, one-page reduction, and selectable-text validation.
- Application artifact storage, state transitions, pause/stop/handoff controls, daily limits, checkpoints, and crash recovery.
- Playwright form preparation with Greenhouse, Lever, Ashby, Workday, and generic adapters. Test fixtures cover mock forms; real employer flows are variable and require manual supervision.
- Optional configured webhooks; disabled by default.
- A public project website and interactive browser demo with search, list/board views, notes, keyword matching, and JSON/CSV exports.

## Optional local tools

**Ollama:** install from [Ollama](https://ollama.com/), start it, and pull the model named in `.env` (default `llama3.2`). The dashboard shows availability. The fallback can prepare structured results without Ollama, but is less capable at understanding job descriptions.

**PDF compiler:** install a TeX distribution containing `pdflatex` or `xelatex`. On macOS, [BasicTeX](https://www.tug.org/mactex/morepackages.html) is one option. `latexmk` is supported when its underlying TeX engine is available. The app searches PATH and common TeX locations. Without a compiler it offers LaTeX source and reports the PDF as unverified; it does not invent a page count or attach an unrelated PDF.

**Browser:** the bootstrap installs Playwright Chromium. Login and CAPTCHA are manual, and real ATS sites can change or block automation. Do not run the agent unattended against real employers.

## Configuration and privacy

`setup.py` copies `.env.example` without replacing an existing `.env`. The dashboard saves the model name, score threshold, and daily limit in ignored `data/runtime_settings.json`. Other options live in `.env`.

Safety flags are enforced in code: `DRY_RUN=true`, `AUTO_SUBMIT=false`, `FINAL_SUBMISSION_ALLOWED=false`, and `REAL_APPLICATIONS_ENABLED=false`. Environment settings cannot enable automatic submission. Citizenship, sponsorship, work authorization, and other sensitive answers are always handed to the user.

Bind the server to `127.0.0.1`. It is a personal local tool without multi-user authentication; do not expose its API to the public internet. Profile files, `.env`, cookies, databases, résumés, and generated application artifacts are ignored by Git. Ollama uses the configured endpoint; URL import, employer browser navigation, and enabled webhooks make the corresponding network requests. Third-party job content is untrusted data.

The public website deploys **only `site/`**, so it contains no Python API, personal profile, database, or generated documents. Its demo data stays in that browser unless the visitor exports it. Fonts may load from Google Fonts, with system fallbacks.

## Development and verification

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium --only-shell
.venv/bin/python -m pytest -q
node --check frontend/js/app.js
node --check site/demo.js
```

Tests use a fictional candidate, temporary databases/artifacts, and mock employer forms. They do not need the owner's private profile or a running Ollama model. Compiler-dependent tests distinguish unavailable compilation from successful validation. CI installs TeX to exercise the compiled path as well.

Preview the public website:

```sh
python3 -m http.server 4174 --bind 127.0.0.1 --directory site
```

Open `http://127.0.0.1:4174`. GitHub Actions publishes `site/` to GitHub Pages on changes to the site or its deployment workflow. The test workflow checks the backend and JavaScript on pushes and pull requests.

## Limits and review requirements

This is an application preparation toolkit, not a guarantee of eligibility, interviews, or employer compatibility. Match scores are heuristics. Immigration/legal questions need personal review. A generated résumé must be checked against your real experience; editing the project registry can change its claims. The browser demo provides keyword overlap only, without AI, eligibility checks, PDF generation, or employer interactions.

See [Agent Safety](docs/AGENT_SAFETY.md), [Résumé Rules](docs/RESUME_RULES.md), and [Application State Machine](docs/APPLICATION_STATE_MACHINE.md) for the enforced workflow.

## Reproducible evaluation

```sh
.venv/bin/python scripts/evaluate_jobs.py --output evaluation/results.json
.venv/bin/python scripts/benchmark_dedupe.py --output evaluation/dedupe-benchmark.json
```

The labeled fixture uses fictional postings and candidate profiles. Its confusion matrix checks eligible/ineligible/review decisions, graduation ranges, and skill-name boundaries; it is a regression set, not an estimate of accuracy on real jobs. Matching never treats JavaScript as verified Java or C++ as verified C. Graduation checks use the candidate's education instead of a fixed year.

The duplicate benchmark creates isolated 1,000- and 10,000-record SQLite databases and reports p50/p95 timings for URL hits, normalized identity hits, and misses. Indexed normalized identity avoids scanning every in-progress application. Legacy rows are backfilled on startup, preserving their IDs; new ORM writes keep the identity current. Bulk SQL writers must provide normalized identity fields explicitly.

Recovery regression tests simulate persisted mid-flight work and consecutive restarts. Interrupted applications remain visible for review, completed applications remain completed, and repeated recovery does not duplicate recovery logs or retry submission.

Before reporting real-world quality, label a separate sample of actual postings without tuning on it. Record false accepts/rejects, ambiguous cases, and missing skills. Ask a few consenting students to try preparation with fictional or their own data, record setup failures and time spent reviewing, and fix the observed issues. No user counts or real-job accuracy claims are inferred from these fixtures.

## Personal Job Tracker

Open **Job Tracker** in the local dashboard. This integrates the redesigned [Personal-Job-Tracker-app](https://github.com/Swopnab/Personal-Job-Tracker-app) UI without adding a runtime dependency. Tracker entries live in a new `tracker_workspace` SQLite table created on startup; existing application records remain intact. The tracker is a personal local workspace with the same localhost/privacy boundary as the rest of the app.

Use **From application history** to copy existing records once. Submitted records start as Applied; other preparation records start as Interested. Repeating the copy preserves your edited tracker stages and notes. Changing a tracker stage never marks an agent application submitted, advances its state machine, or contacts an employer. History copying is a snapshot, not continuous synchronization.

Export JSON from the standalone tracker and import it here to transfer existing entries. Import replaces the tracker list after validating the entire backup and asking for confirmation; it never replaces the agent's application history. Limits are 10 MB and 10,000 entries, with unique IDs, known stages, bounded strings, real dates, and HTTP/HTTPS job links. Two simultaneous database saves cannot silently replace one another: a stale revision returns a conflict, preserving the open form for review. Export a backup before a destructive import or deletion.

The public website's demo links to `site/tracker/`. That version uses browser storage only and makes no Python API calls. It does not expose the local database, profile or documents. Browser data on the same origin uses the existing `jobTrackerApplications` key; exports bridge browser and local database modes.

`frontend/tracker/` and `site/tracker/` share the same scripts/styles; the local HTML explicitly opts into `/api/tracker/`. Tests check matching assets, actual SQLite imports/conflicts/history boundaries, and a live browser → API → database → reload workflow with fictional data. The browser suite also checks failed saves, stale tabs, public demo isolation and 390px/768px/1440px viewports.
