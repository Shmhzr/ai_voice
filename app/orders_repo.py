# orders_repo.py
from .firebase_client import db

def save_order(order: dict):
    doc_id = str(order["order_number"])
    db.collection("orders").document(doc_id).set(order)
