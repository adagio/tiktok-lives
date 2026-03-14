from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routers import clips, sessions

app = FastAPI(
    title="Clips Explorer API",
    description="API para explorar clips de TikTok Lives",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    clips.router,
    prefix="/api/v1/clips",
    tags=["clips"],
)

app.include_router(
    sessions.router,
    prefix="/api/v1/sessions",
    tags=["sessions"],
)


@app.get("/", tags=["health"])
async def root():
    return {
        "name": "Clips Explorer API",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["health"])
async def health():
    return {"status": "healthy"}
