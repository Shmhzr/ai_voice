# app/orders_store.py
import os, json, threading
from datetime import datetime
import logging

from .firebase_client import firebase_client
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ORDERS_PATH = os.path.join(BASE_DIR, "orders.json")
_lock = threading.Lock()

def init_store():
    # pass
    """Create a fresh orders.json with empty list every time server starts."""
    with _lock:
        data = {"orders": []}
        _write_unlocked(data)
    return ORDERS_PATH

def clear_store():
    """Wipe all orders (used on graceful shutdown)."""
    with _lock:
        _write_unlocked({"orders": []})
    print("🧹 Cleared orders.json on shutdown")

def _ensure_file_unlocked():
    if not os.path.exists(ORDERS_PATH):
        _write_unlocked({"orders": []})

def _read_unlocked():
    _ensure_file_unlocked()
    with open(ORDERS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_unlocked(data):
    tmp = ORDERS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ORDERS_PATH)

def _read():
    with _lock:
        return _read_unlocked()

def _write(data):
    with _lock:
        _write_unlocked(data)

# def add_order(order: dict):
#     """Append a new order. Must include: order_number, phone, items, total, status, created_at."""
#     with _lock:
#         data = _read_unlocked()
#         data["orders"].append(order)
#         _write_unlocked(data)

async def add_order(order: dict) -> str:
    """
    Append a new order:
      - pushes to Firebase Realtime DB under 'orderList' (returns firebase key)
      - appends to local JSON file (uses thread to avoid blocking)
    Returns the firebase-generated key (string).
    """
    # sanity checks
    if not isinstance(order, dict):
        raise TypeError("order must be a dict")

    # 1) push to firebase (async wrapper)
    try:
        key = await firebase_client.push("orderList", order)
        logger.info("Pushed order to Firebase, key=%s", key)
    except Exception as e:
        logger.exception("Failed to push order to Firebase")
        # optionally re-raise or return a special value depending on your desired behavior
        raise

    # attach the key to local copy so file and db can be correlated
    order_with_key = dict(order)
    order_with_key["_firebase_key"] = key

    # 2) write to local JSON in a separate thread to avoid blocking the event loop
    def _write_local():
        # keep the same existing sync locking logic
        with _lock:
            data = _read_unlocked()           # synchronous
            if "orders" not in data:
                data["orders"] = []
            data["orders"].append(order_with_key)
            _write_unlocked(data)            # synchronous

    try:
        # Python 3.9+; for older versions use loop.run_in_executor(...)
        await asyncio.to_thread(_write_local)
        logger.info("Wrote order to local JSON file (orders).")
    except Exception as e:
        # local write failed — decide whether to rollback Firebase or let it stay and alert
        logger.exception("Failed to write order to local JSON file")
        # Optionally: try to delete the pushed Firebase node to keep consistency:
        try:
            await firebase_client.delete(f"orderList/{key}")
            logger.info("Rolled back firebase push after local write failure (deleted key=%s)", key)
        except Exception:
            logger.exception("Rollback (delete) failed for firebase key=%s", key)
        raise

    return key

def list_recent_orders(limit: int = 50):
    data = _read()
    items = list(reversed(data["orders"]))  # newest first
    return items[:limit]

def list_in_progress_orders(limit: int = 100):
    data = _read()
    items = [o for o in reversed(data["orders"]) if o.get("status") != "ready"]
    return [{"order_number": o["order_number"], "status": o.get("status", "received")} for o in items[:limit]]

def get_order_phone(order_number: str) -> str | None:
    data = _read()
    for o in data["orders"]:
        if o.get("order_number") == order_number:
            return o.get("phone")
    return None

def set_order_status(order_number: str, status: str) -> bool:
    with _lock:
        data = _read_unlocked()
        for o in data["orders"]:
            if o.get("order_number") == order_number:
                o["status"] = status
                _write_unlocked(data)
                return True
        return False

def get_order(order_number: str) -> dict | None:
    """Return full order dict by order_number."""
    data = _read()
    for o in data["orders"]:
        if o.get("order_number") == order_number:
            return o
    return None

def latest_order_for_phone(phone_e164: str) -> dict | None:
    """Return the most recent order for a phone (by created_at)."""
    data = _read()
    matches = [o for o in data["orders"] if o.get("phone") == phone_e164]
    if not matches:
        return None
    return sorted(matches, key=lambda o: o.get("created_at") or 0, reverse=True)[0]

def count_active_orders_for_phone(phone_e164: str) -> int:
    """Count orders for a phone that are NOT ready (active orders only)."""
    if not phone_e164:
        return 0
    data = _read()
    return sum(1 for o in data["orders"] if o.get("phone") == phone_e164 and o.get("status") != "ready")

def count_active_drinks_for_phone(phone_e164: str) -> int:
    """Count total number of drinks across all active orders (status != ready) for a phone."""
    if not phone_e164:
        return 0
    data = _read()
    total_drinks = 0
    for o in data["orders"]:
        if o.get("phone") == phone_e164 and o.get("status") != "ready":
            total_drinks += len(o.get("items", []))
    return total_drinks

def now_iso():
    return datetime.utcnow().isoformat()


# from datetime import datetime
# import threading
# from typing import Any, Dict, List, Optional
# from google.cloud import firestore  # comes with firebase_admin
# from .firebase_client import db
# from app import firebase_client
# _lock = threading.Lock()

# COLLECTION = "orders"


# def init_store():
#     # No-op or one‑time migration if you want.
#     return COLLECTION


# def clear_store():
#     # Dangerous in prod: wipes all orders
#     docs = db.collection(COLLECTION).stream()
#     for d in docs:
#         d.reference.delete()
#     print("🧹 Cleared orders collection on shutdown")


# async def add_order(order: Dict[str, Any]):
#     with _lock:
#         """Append a new order. Must include: order_number, phone, items, total, status, created_at."""
#         order_no = str(order["order_number"])
#         if "created_at" not in order:
#             order["created_at"] = int(datetime.utcnow().timestamp())
#         if "saved_at" not in order:
#             order["saved_at"] = datetime.utcnow().isoformat()
#         key = await firebase_client.push('orderList', order)
#         return key


# def list_recent_orders(limit: int = 50) -> List[Dict[str, Any]]:
#     qs = (
#         db.collection(COLLECTION)
#         .order_by("created_at", direction=firestore.Query.DESCENDING)
#         .limit(limit)
#         .stream()
#     )
#     return [doc.to_dict() for doc in qs]


# def list_in_progress_orders(limit: int = 100) -> List[Dict[str, Any]]:
#     qs = (
#         db.collection(COLLECTION)
#         .where("status", "!=", "ready")  # or .where("status", "in", ["received","preparing"])
#         .order_by("created_at", direction=firestore.Query.DESCENDING)
#         .limit(limit)
#         .stream()
#     )
#     orders = [doc.to_dict() for doc in qs]
#     return [
#         {"order_number": o["order_number"], "status": o.get("status", "received")}
#         for o in orders
#     ]


# def get_order_phone(order_number: str) -> Optional[str]:
#     o = get_order(order_number)
#     if not o:
#         return None
#     return o.get("phone")


# def set_order_status(order_number: str, status: str) -> bool:
#     ref = db.collection(COLLECTION).document(order_number)
#     snap = ref.get()
#     if not snap.exists:
#         return False
#     ref.update({"status": status})
#     return True


# def get_order(order_number: str) -> Optional[Dict[str, Any]]:
#     snap = db.collection(COLLECTION).document(order_number).get()
#     if not snap.exists:
#         return None
#     return snap.to_dict()


# def latest_order_for_phone(phone_e164: str) -> Optional[Dict[str, Any]]:
#     if not phone_e164:
#         return None
#     qs = (
#         db.collection(COLLECTION)
#         .where("phone", "==", phone_e164)
#         .order_by("created_at", direction=firestore.Query.DESCENDING)
#         .limit(1)
#         .stream()
#     )
#     docs = list(qs)
#     if not docs:
#         return None
#     return docs[0].to_dict()


# def count_active_orders_for_phone(phone_e164: str) -> int:
#     if not phone_e164:
#         return 0
#     qs = (
#         db.collection(COLLECTION)
#         .where("phone", "==", phone_e164)
#         .where("status", "!=", "ready")
#         .stream()
#     )
#     return sum(1 for _ in qs)


# def count_active_drinks_for_phone(phone_e164: str) -> int:
#     if not phone_e164:
#         return 0
#     qs = (
#         db.collection(COLLECTION)
#         .where("phone", "==", phone_e164)
#         .where("status", "!=", "ready")
#         .stream()
#     )
#     total_drinks = 0
#     for doc in qs:
#         o = doc.to_dict()
#         total_drinks += len(o.get("items", []))
#     return total_drinks


# def now_iso():
#     return datetime.utcnow().isoformat()
