"""Local JSON API over the finance DB (consumed by the React app)."""

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from finance.api import errors
from finance.api.deps import Workspace, get_workspace
from finance.api.routes import budgets, meta, networth, panorama, review, settings, summary, taxonomy, transactions
from finance.api.security import LOCAL_HOSTS, MutationGuardMiddleware, SecurityHeadersMiddleware
from finance.api.sync_runner import SyncRunner

__all__ = ["Workspace", "create_app", "get_workspace"]


def create_app(workspace_factory: Callable[[], Workspace] | None = None, static_dir: Path | None = None,
               sync_runner: SyncRunner | None = None) -> FastAPI:
    app = FastAPI(title="finance", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sync_runner = sync_runner or SyncRunner()  # one background sync at a time per app
    if workspace_factory is not None:
        app.dependency_overrides[get_workspace] = workspace_factory
    errors.install(app)
    app.add_middleware(MutationGuardMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(LOCAL_HOSTS))
    app.add_middleware(SecurityHeadersMiddleware)  # added last = outermost: headers on every response
    app.include_router(meta.router, prefix="/api/v1")
    app.include_router(summary.router, prefix="/api/v1")
    app.include_router(taxonomy.router, prefix="/api/v1")
    app.include_router(transactions.router, prefix="/api/v1")
    app.include_router(review.router, prefix="/api/v1")
    app.include_router(budgets.router, prefix="/api/v1")
    app.include_router(panorama.router, prefix="/api/v1")
    app.include_router(networth.router, prefix="/api/v1")
    app.include_router(settings.router, prefix="/api/v1")

    if static_dir is not None and static_dir.exists():
        root = static_dir.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return errors.error_response(404)
            candidate = (root / path).resolve()
            if path and candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(root / "index.html")  # SPA fallback
    return app
