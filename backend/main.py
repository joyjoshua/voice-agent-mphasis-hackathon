"""FastAPI entrypoint for Kirana AI (Phase 9)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketDisconnect

from db.database import get_inventory, get_sales_summary, init_db
from logger.csv_logger import init_csv
from voice.pipeline import run_pipeline

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_csv()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


SalesPeriod = Literal["today", "this_week", "this_month"]


@app.get("/api/dashboard")
async def api_dashboard():
    return {
        "sales": get_sales_summary("today"),
        "inventory": get_inventory(),
    }


@app.get("/api/sales")
async def api_sales(period: SalesPeriod = Query("today")):
    return get_sales_summary(period)


@app.get("/api/inventory")
async def api_inventory():
    return get_inventory()


@app.websocket("/ws/voice")
async def ws_voice(websocket: WebSocket):
    await websocket.accept()
    try:
        await run_pipeline(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        pass
