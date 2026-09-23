from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import router
from app.core.config import get_settings

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Baza se menja isključivo preko Alembic migracija.
    yield


settings = get_settings()
app = FastAPI(
    title="eFakture i eOtpremnice",
    version="0.3.0",
    docs_url="/api/docs" if settings.env != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Organization-Id"],
    )
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(router)


@app.get("/health/live")
async def live():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")
