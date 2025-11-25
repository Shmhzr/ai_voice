import json
import logging
from contextlib import asynccontextmanager
import os
from fastapi import FastAPI, Depends
from .http_routes import http_router
from .ws_bridge import router as ws_router
from app.firebase_client import firebase_client


def _setup_logging():
    level = logging.getLevelName((__import__("os").getenv("LOG_LEVEL") or "INFO").upper())
    fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    print("🚀 Server starting")
    try:
        yield
    finally:
        print("🔌 Server shutting down")

def get_db_dep():
    return db

def create_app() -> FastAPI:
    app = FastAPI(title="Twilio ⇄ Deepgram Voice Agent", lifespan=lifespan)
    
    
     # Initialize Firebase once at startup
    current_working_directory = os.getcwd()
    sa_path = current_working_directory+ "/serviceAccountKey.json"
    db_url = os.getenv("FIREBASE_DATABASE_URL")

    if not db_url:
        raise RuntimeError("FIREBASE_DATABASE_URL must be set")

    # initialize firebase client
    firebase_client.init_app(
        service_account_path=sa_path,
        service_account_json=None,
        database_url=db_url
    )   


    
    # Register your routers
    app.include_router(http_router)
    app.include_router(ws_router)

    # POST route to add order to Firestore
    @app.post("/orders")
    async def create_order(order: dict, db=Depends(get_db_dep)):
        doc_id = str(order.get("order_number", "unknown"))
        db.collection("orders").document(doc_id).set(order)
        return {"status": "ok"}

    return app
