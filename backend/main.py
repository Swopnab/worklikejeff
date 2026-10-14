"""
backend/main.py
FastAPI application entrypoint.
Serves the API and static frontend files.
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config.settings import settings
from database.connection import init_db
from agent.recovery import recover_on_startup
from backend.api import agent, applications, jobs, profile, resume, discovery, webhooks, tracker

# ============================================================
# Logging setup
# ============================================================
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================
# Lifespan — startup / shutdown
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("JobAgent starting up...")
    logger.info("DRY_RUN=%s  AUTO_SUBMIT=%s  OLLAMA_MODEL=%s",
                settings.dry_run, settings.auto_submit, settings.ollama_model)

    # Ensure directories exist
    for directory in [
        settings.applications_dir,
        settings.resume_generated_dir,
        settings.logs_dir,
    ]:
        Path(directory).mkdir(parents=True, exist_ok=True)

    # Initialize database
    await init_db()
    logger.info("Database initialized at %s", settings.database_path)

    # Run crash recovery
    recovery_report = await recover_on_startup()
    if recovery_report["action_taken"]:
        logger.warning("Recovery actions taken: %s", recovery_report["action_taken"])

    yield

    logger.info("JobAgent shutting down.")


# ============================================================
# App
# ============================================================
app = FastAPI(
    title="JobAgent API",
    description="AI-powered job application agent backend",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.is_development else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# API routes
# ============================================================
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
app.include_router(applications.router, prefix="/api/applications", tags=["Applications"])
app.include_router(discovery.router, prefix="/api/discovery", tags=["Discovery"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"])
app.include_router(profile.router, prefix="/api/profile", tags=["Profile"])
app.include_router(resume.router, prefix="/api/resume", tags=["Resume"])
app.include_router(tracker.router, prefix="/api/tracker", tags=["Job Tracker"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])

@app.get("/api/health")
async def health():
    from resume.validator import is_latex_compiler_available
    available, compiler, _ = is_latex_compiler_available()
    return {"status": "ok", "profile_configured": Path(settings.profile_path).exists(),
            "latex_available": available, "compiler": compiler,
            "dry_run": settings.dry_run, "auto_submit": settings.auto_submit}

# ============================================================
# Static frontend
# ============================================================
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_spa(path: str):
        """Serve the SPA for all non-API routes."""
        if path.startswith("api/"):
            raise HTTPException(404, "API endpoint not found")
        file_path = (FRONTEND_DIR / path).resolve()
        if not file_path.is_relative_to(FRONTEND_DIR.resolve()):
            raise HTTPException(404, "File not found")
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIR / "index.html"))
