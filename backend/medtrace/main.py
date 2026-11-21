"""FastAPI application entry point.

Run (from ./backend):  uvicorn medtrace.main:app --port 8000
If ../frontend/dist exists it is served at / so the app runs on a single origin."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .api import analysis_routes, auth_routes, document_routes, evaluation_routes, patient_routes
from .config import get_settings
from .db import init_db
from .security import CSRF_HEADER, bootstrap_admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("medtrace")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def create_app() -> FastAPI:
    settings = get_settings()
    init_db()
    generated = bootstrap_admin()
    if generated:
        # Printed once to the local console only; never logged to file or stored in plain text.
        print("\n[MedTrace] No MEDTRACE_ADMIN_PASSWORD configured. Generated administrator password for "
              f"'{settings.admin_username}': {generated}\n[MedTrace] Set MEDTRACE_ADMIN_PASSWORD in .env to choose your own.\n")

    app = FastAPI(title="MedTrace API", version="1.0.0",
                  description="Evidence-based, chronological medical record reconstruction. Records organisation only - not clinical advice.")

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-MedTrace-CSRF"])

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method in UNSAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"detail": "Missing CSRF header."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store") if request.url.path.startswith("/api/") else response.headers.get("Cache-Control", "no-cache")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        return response

    for r in (auth_routes.router, patient_routes.router, document_routes.router, analysis_routes.router, evaluation_routes.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    if FRONTEND_DIST.is_dir():
        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            base = FRONTEND_DIST.resolve()
            target = (base / full_path).resolve()
            if full_path and base in target.parents and target.is_file():
                return FileResponse(target)
            return FileResponse(base / "index.html")

    return app


app = create_app()
