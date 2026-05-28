import logging
from contextlib import asynccontextmanager
from pathlib import Path
from subprocess import check_output

import sentry_sdk
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import settings
from app.database.connection import close_db, init_db
from app.routers import (
    dashboard_router,
    feedback_router,
    internal_router,
    request_router,
)

sentry_sdk.init(
    dsn=settings.sentry_dsn,
    environment=settings.environment,
    release=f"reviewhelper-api@{__version__}",
    server_name=check_output("hostname").decode("utf-8").rstrip(),
    send_default_pii=True,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="Review Helper Backend",
    description="FastAPI backend for Mozilla's Review Helper supporting Phabricator and GitHub",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(request_router)
app.include_router(feedback_router)
app.include_router(internal_router)
app.include_router(dashboard_router)


@app.get("/health")
async def health_check():
    """Health check endpoint for Cloud Run."""
    return {"message": "Service is healthy", "status": "ok"}


# Serve the built dashboard SPA (web/dist) at /dashboard, if present. The build
# is produced by `npm --prefix web run build` and is optional in development.
_DASHBOARD_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if _DASHBOARD_DIST.is_dir():
    app.mount(
        "/dashboard",
        StaticFiles(directory=str(_DASHBOARD_DIST), html=True),
        name="dashboard",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.port)
