from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI

from app.api import router
from app.config import settings
from app.logger import get_logger


logger = get_logger("main")


def create_app(
    application_factory: Callable[[], Any] | None = None,
    run_on_startup: bool | None = None,
) -> FastAPI:
    should_run_on_startup = settings.run_on_startup if run_on_startup is None else run_on_startup

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):
        factory = application_factory
        if factory is None:
            from app.bootstrap import Application

            factory = Application

        application = factory()
        fastapi_app.state.application = application

        await application.startup()

        try:
            if should_run_on_startup:
                logger.info("register startup daily analysis task once")
                try:
                    await application.ensure_today_daily_analysis_task_exists()
                except Exception as e:
                    logger.exception("register startup daily analysis task failed, ignore: %s", e)

            yield
        finally:
            await application.shutdown()

    fastapi_app = FastAPI(
        title="daily_pe_reporter",
        version="1.0.0",
        lifespan=lifespan,
    )
    fastapi_app.include_router(router)
    return fastapi_app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8092,
        reload=False,
    )
