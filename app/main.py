from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.keitaro import aclose_cached_client
from app.routers.campaigns import router as campaigns_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # startup: nothing to do
    yield
    # shutdown: close cached keitaro client
    await aclose_cached_client()


app = FastAPI(title="Keitaro Wrapper", version="1.0.0", lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for tests; in production - specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(campaigns_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root():
    return FileResponse("app/static/index.html")
