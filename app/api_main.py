from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.news import router as news_router

app = FastAPI(title="Daily PE Reporter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(news_router)


@app.get("/")
async def root():
    return {"code": 0, "message": "ok"}