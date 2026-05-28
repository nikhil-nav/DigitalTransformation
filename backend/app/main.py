from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth import router as auth_router
from app.bcm import router as bcm_router
from app.data_quality.router import router as data_quality_router
from app.db import get_engine, init_db
from app.files import router as files_router
from app.projects import router as projects_router
from app.threads import router as threads_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db(get_engine())
    yield


app = FastAPI(title="Digital Transformation Platform API", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(bcm_router)
app.include_router(files_router)
app.include_router(threads_router)
app.include_router(data_quality_router)

