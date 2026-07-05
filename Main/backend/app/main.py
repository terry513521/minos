import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import auto, candidates, health, history, jobs, platform_round, policies, runs, workers
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.services.auto_mode import load_auto_mode_state
from app.services.platform_round import poller as platform_poller
from app.services.seed_results_poller import poller as seed_poller

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    async with SessionLocal() as db:
        await load_auto_mode_state(db)
    await platform_poller.start()
    await seed_poller.start()
    yield
    await seed_poller.stop()
    await platform_poller.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Effortless Control Plane",
        description="Config optimization orchestrator for genomic windows",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix=settings.api_prefix)
    api.include_router(health.router)
    api.include_router(candidates.router)
    api.include_router(runs.router)
    api.include_router(jobs.router)
    api.include_router(workers.router)
    api.include_router(auto.router)
    api.include_router(history.router)
    api.include_router(policies.router)
    api.include_router(platform_round.router)
    app.include_router(api)

    @app.websocket(f"{settings.api_prefix}/ws")
    async def websocket_events(websocket: WebSocket):
        await websocket.accept()
        queue = platform_poller.subscribe()
        try:
            await websocket.send_json(
                {"type": "connected", "service": "effortless", "data": platform_poller.snapshot.to_dict()}
            )
            await websocket.send_json(
                {"type": "platform_round", "data": platform_poller.snapshot.to_dict()}
            )

            async def forward_poller():
                while True:
                    msg = await queue.get()
                    await websocket.send_json(msg)

            async def read_client():
                while True:
                    await websocket.receive_text()

            forward_task = asyncio.create_task(forward_poller())
            read_task = asyncio.create_task(read_client())
            done, pending = await asyncio.wait(
                {forward_task, read_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
        except WebSocketDisconnect:
            pass
        finally:
            platform_poller.unsubscribe(queue)

    if settings.serve_frontend and FRONTEND_DIST.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=FRONTEND_DIST, html=True),
            name="frontend",
        )

    return app


app = create_app()
