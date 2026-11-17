from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, health, ingest
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.middleware import ApiHeadersMiddleware


def create_app() -> FastAPI:
    settings = get_settings()

    # Interactive docs help while learning, but they describe every endpoint to
    # anyone who finds the URL, so they exist only in development.
    docs = not settings.is_production
    app = FastAPI(
        title="Finance API",
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )

    install_error_handlers(app)
    app.add_middleware(ApiHeadersMiddleware)

    # Production needs no CORS at all: the browser only ever talks to the Vercel
    # origin, which proxies /api to this server. CORS exists for local development.
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type"],
        )

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    return app


app = create_app()