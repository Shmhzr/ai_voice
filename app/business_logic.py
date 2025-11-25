# app/business_logic.py
import re
import time
import random
import asyncio
import os
import json
import logging
from typing import Dict, List, Any, Optional, Tuple, Set
from .firebase_client import firebase_client

from app import settings as settings_mod
from .events import publish

logger = logging.getLogger(__name__)

# -------------------------
# Matching helpers
# -------------------------
def _match_with_aliases(value_norm: str, canonical_list: list | dict, aliases: Dict[str, Set[str]]):
    """
    Return canonical display name from canonical_list that best matches value_norm.
    - Accepts canonical_list as list or dict (will extract keys if dict).
    - aliases: mapping canonical_name -> set({alternate spellings})
    Returns exact canonical display name (as present in canonical_list) or None.
    """
    if not value_norm:
        return None

    v = str(value_norm).strip().lower()
    # build canonical_map normalized -> original
    canonical_map: Dict[str, str] = {}
    if isinstance(canonical_list, dict):
        iterable = list(canonical_list.keys())
    else:
        iterable = list(canonical_list or [])

    for c in iterable:
        if c is None:
            continue
        cnorm = str(c).strip().lower()
        canonical_map[cnorm] = c  # keep original display form

    # 1) exact normalized match
    if v in canonical_map:
        return canonical_map[v]

    # 2) aliases match
    try:
        for canonical, alias_set in (aliases or {}).items():
            if canonical is None:
                continue
            canonical_norm = str(canonical).strip().lower()
            # direct canonical match (even if canonical not in canonical_map)
            if v == canonical_norm:
                return canonical_map.get(canonical_norm, canonical)
            for a in (alias_set or set()):
                if not a:
                    continue
                a_norm = str(a).strip().lower()
                if v == a_norm or v in a_norm or a_norm in v:
                    return canonical_map.get(canonical_norm, canonical)
    except Exception:
        # tolerate alias errors: fall through to fuzzy match
        pass

    # 3) fuzzy substring match against canonical list
    for c_norm, c_orig in canonical_map.items():
        if v in c_norm or c_norm in v:
            return c_orig

    return None

# -------------------------
# Config / constants
# -------------------------
VALID_ORDER_TYPES = {
    "pickup": "pickup",
    "pick up": "pickup",
    "pick-up": "pickup",
    "p": "pickup",
    "delivery": "delivery",
    "d": "delivery",
}

# Aliases for toppings/addons (canonical -> set of variants)
ADDON_ALIASES: Dict[str, Set[str]] = {
    "garlic bread": {"garlic bread", "garlicbread", "garlic-bread", "garlic"},
    "coke": {"coke", "cola", "coca cola", "coca-cola"},
    "choco lava cake": {"choco lava", "lava cake", "choco lava cake", "choco-lava"},
}

TOPPING_ALIASES: Dict[str, Set[str]] = {
    "paneer": {"paneer", "panir"},
    "onion": {"onion", "onions"},
    "capsicum": {"capsicum", "caps", "capsicums", "bell pepper", "bell peppers"},
    "mushrooms": {"mushrooms", "mushroom"},
    "sweet corn": {"sweet corn", "corn"},
    "jalapeno": {"jalapeno", "jalapeño", "jalapenos"},
    "tomato": {"tomato", "tomatoes"},
}

MAX_PIZZAS = 5
MAX_ORDERS_PER_PHONE = 5

# -------------------------
# In-memory per-call stores
# -------------------------
_legacy_lock = asyncio.Lock()
_legacy_CART: List[dict] = []
_legacy_ORDERS: Dict[str, dict] = {}
_legacy_PENDING_ORDERS: Dict[str, dict] = {}

_call_locks: Dict[str, asyncio.Lock] = {}
_CALL_CARTS: Dict[str, List[dict]] = {}
_CALL_ORDERS: Dict[str, Dict[str, dict]] = {}
_CALL_PENDING_ORDERS: Dict[str, Dict[str, dict]] = {}
_CALL_ORDER_TYPES: Dict[str, Dict[str, Any]] = {}
_legacy_ORDER_TYPE: Dict[str, Any] = {}

# -------------------------
# Store helpers & normalizers
# -------------------------
def _get_store(call_sid: Optional[str]) -> Tuple[asyncio.Lock, List[dict], Dict[str, dict], Dict[str, dict]]:
    if not call_sid:
        return _legacy_lock, _legacy_CART, _legacy_ORDERS, _legacy_PENDING_ORDERS

    lock = _call_locks.get(call_sid)
    if not lock:
        lock = _call_locks[call_sid] = asyncio.Lock()
    cart = _CALL_CARTS.get(call_sid)
    if cart is None:
        cart = _CALL_CARTS[call_sid] = []
    orders = _CALL_ORDERS.get(call_sid)
    if orders is None:
        orders = _CALL_ORDERS[call_sid] = {}
    pending = _CALL_PENDING_ORDERS.get(call_sid)
    if pending is None:
        pending = _CALL_PENDING_ORDERS[call_sid] = {}
    return lock, cart, orders, pending

def _get_order_type_store(call_sid: Optional[str]):
    if not call_sid:
        return _legacy_ORDER_TYPE
    ot = _CALL_ORDER_TYPES.get(call_sid)
    if ot is None:
        ot = _CALL_ORDER_TYPES[call_sid] = {}
    return ot

def _normalize(s: Optional[str]) -> str:
    return (s or "").strip().lower()

def _ensure_list(x):
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [str(i) for i in x if i is not None]
    return [str(x)]

# -------------------------
# Menu helpers (read-only)
# -------------------------
def _get_effective_menu() -> Dict[str, Any]:
    """Read current menu from settings.get_menu(). Returns canonical dict or empty dict."""
    try:
        m = settings_mod.get_menu()
        if not isinstance(m, dict):
            return {}
        return m
    except Exception as e:
        publish("agent_function_error", {"name": "_get_effective_menu", "error": str(e)})
        return {}

# -------------------------
# Size / price key helpers
# -------------------------
def _size_key_candidates(size: Optional[str]) -> List[str]:
    """
    Produce candidate keys to try in price lookup for a requested size.
    E.g. "Small" -> ["Small","small","SMALL","small","Small","regular","default"]
    Keep order so more likely forms are tried first.
    """
    if not size:
        return ["default", "regular"]
    s = str(size).strip()
    candidates = [s, s.lower(), s.capitalize(), s.title(), s.upper()]
    # common aliases
    if s.lower() in ("small", "medium", "large"):
        candidates += ["regular", "default"]
    else:
        candidates += ["default", "regular"]
    # dedupe preserving order
    seen = set()
    out = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out

# -------------------------
# Price lookups
# -------------------------
def _lookup_price_from_normalized(menu: dict, item_name: str, size: Optional[str]) -> Optional[float]:
    """
    Look up price in menu['prices'] map in a tolerant way:
      - Try normalized (lowercased) item key first
      - Fall back to display-key if present
      - Try a list of size-key candidates
    """
    try:
        if not item_name:
            return None
        prices = (menu.get("prices") or {}) or {}
        norm_name = item_name.strip().lower()

        # prefer normalized key if present
        if norm_name in prices and isinstance(prices[norm_name], dict):
            item_prices = prices[norm_name]
        else:
            # try display keyed entries (exact)
            item_prices = prices.get(item_name) or prices.get(item_name.strip()) or {}
        if not isinstance(item_prices, dict):
            return None

        for sk in _size_key_candidates(size):
            if sk in item_prices and item_prices[sk] is not None:
                try:
                    return float(item_prices[sk])
                except Exception:
                    # continue trying other candidates
                    pass
    except Exception as e:
        publish("agent_function_error", {"name": "_lookup_price_from_normalized", "error": str(e), "item_name": item_name, "size": size})
    return None

def _lookup_price_from_raw_menu(menu_raw: dict, item_name: str, size: Optional[str]) -> Optional[float]:
    """
    Inspect common raw menu shapes (menu->Pizza / Sides lists) and attempt to find a price.
    """
    try:
        if not isinstance(menu_raw, dict):
            return None
        candidate = menu_raw.get("menu") or menu_raw
        sections = []
        if isinstance(candidate, dict):
            sections += [candidate.get(k) for k in ("Pizza", "Pizzas", "pizza", "pizzas")]
            sections += [candidate.get(k) for k in ("Sides", "Drinks", "sides", "drinks")]
        for sec in sections:
            if not isinstance(sec, list):
                continue
            for it in sec:
                if not isinstance(it, dict):
                    continue
                name = (it.get("name") or it.get("title") or "").strip()
                if not name:
                    continue
                if name.strip().lower() != item_name.strip().lower():
                    continue
                # sizes dict
                s = it.get("sizes")
                if isinstance(s, dict):
                    for candidate_size in _size_key_candidates(size):
                        entry = s.get(candidate_size) or s.get(candidate_size.lower()) or s.get(candidate_size.capitalize())
                        if isinstance(entry, dict):
                            p = entry.get("price") or entry.get("cost")
                            if p is not None:
                                try:
                                    return float(p)
                                except Exception:
                                    pass
                        elif isinstance(entry, (int, float)):
                            return float(entry)
                # fallback to top-level 'price'
                p = it.get("price")
                if p is not None:
                    try:
                        return float(p)
                    except Exception:
                        pass
        # not found
    except Exception as e:
        publish("agent_function_error", {"name": "_lookup_price_from_raw_menu", "error": str(e), "item_name": item_name, "size": size})
    return None

# -------------------------
# Per-item pricing helpers
# -------------------------
def _detailed_price_for_cart_item(item_obj: dict, menu: dict) -> Dict[str, Any]:
    """
    Detailed breakdown for a single cart line. Accepts item_obj with 'quantity'.
    Returns monetary amounts rounded to 2 decimals.
    """
    item_name = item_obj.get("item") or item_obj.get("flavor") or ""
    # If menu supplies human sizes (Small/Medium/Large) we expect callers to use that.
    # If stored value is None/invalid, treat as 'Small' (sensible default).
    size = item_obj.get("size") or None
    try:
        qty = int(item_obj.get("quantity") or 1)
    except Exception:
        qty = 1

    unit_price = _lookup_price_from_normalized(menu, item_name, size)
    if unit_price is None:
        unit_price = _lookup_price_from_raw_menu(menu, item_name, size)
    if unit_price is None:
        unit_price = 0.0
    try:
        unit_price = float(unit_price)
    except Exception:
        unit_price = 0.0

    # addons breakdown
    addons_list = []
    addons_total_unit = 0.0
    raw_addons = item_obj.get("addons") or []
    if raw_addons and isinstance(raw_addons, (list, tuple)):
        prices_map = (menu.get("prices") or {}) or {}
        for a in raw_addons:
            a_name = a if isinstance(a, str) else str(a)
            a_unit_price = None
            try:
                anorm = a_name.strip().lower()
                if anorm in prices_map and isinstance(prices_map[anorm], dict):
                    amap = prices_map[anorm]
                    if "default" in amap and amap["default"] is not None:
                        a_unit_price = float(amap["default"])
                    else:
                        for v in amap.values():
                            if v is not None:
                                a_unit_price = float(v)
                                break
                elif a_name in prices_map and isinstance(prices_map[a_name], (int, float)):
                    a_unit_price = float(prices_map[a_name])
            except Exception:
                a_unit_price = None

            if a_unit_price is None:
                a_unit_price = _lookup_price_from_raw_menu(menu, a_name, size="default")

            if a_unit_price is None:
                a_unit_price = 0.0
            try:
                a_unit_price = float(a_unit_price)
            except Exception:
                a_unit_price = 0.0

            addons_list.append({"name": a_name, "unit_price": round(a_unit_price, 2)})
            addons_total_unit += a_unit_price

    unit_total = unit_price + addons_total_unit
    line_total = unit_total * qty

    return {
        "item": item_name,
        "size": size or (menu.get("sizes") or ["Small"])[0],
        "qty": qty,
        "unit_price": round(unit_price, 2),
        "addons": addons_list,
        "unit_total": round(unit_total, 2),
        "line_total": round(line_total, 2),
    }

def calculate_cart_total(cart: List[dict]) -> Dict[str, Any]:
    """
    Compute cart totals. Each line may have 'quantity'.
    Returns {"subtotal": float, "items": [...], "total": float}
    """
    menu = _get_effective_menu() or {}
    items_breakdown = []
    subtotal = 0.0
    for idx, item in enumerate(cart):
        detail = _detailed_price_for_cart_item(item, menu)
        items_breakdown.append({
            "index": idx,
            "item": detail["item"],
            "size": detail["size"],
            "qty": detail["qty"],
            "unit_price": detail["unit_price"],
            "addons": detail["addons"],
            "unit_total": detail["unit_total"],
            "line_total": detail["line_total"],
            "raw_item": item,
        })
        subtotal += float(detail["line_total"])
    subtotal = round(subtotal, 2)
    return {"subtotal": subtotal, "items": items_breakdown, "total": subtotal}

def _price_for_cart_item(item_obj: dict, menu: dict) -> float:
    try:
        detail = _detailed_price_for_cart_item(item_obj, menu)
        return float(detail.get("line_total", 0.0))
    except Exception:
        return 0.0

# -------------------------
# Menu summary
# -------------------------
def menu_summary():
    m = _get_effective_menu() or {}
    return {
        "summary": m.get("summary", "We offer a selection of pizzas."),
        "flavors": m.get("flavors", []),
        "toppings": m.get("toppings", []),
        "addons": m.get("addons", []),
        "sizes": m.get("sizes", []),
        "prices": m.get("prices", {}),
    }

# -------------------------
# Cart ops
# -------------------------
def _cart_total_pizzas(CART: List[dict]) -> int:
    total = 0
    for it in CART:
        try:
            total += int(it.get("quantity") or 1)
        except Exception:
            total += 1
    return total

async def add_to_cart(
    item: str,
    toppings=None,
    customer_name: Optional[str] = None,
    address: Optional[str] = None,
    *,
    call_sid: Optional[str] = None,
    size: Optional[str] = None,
    quantity: Optional[int] = 1,
):
    """
    Add a pizza line to cart. Records a single object with 'quantity'.
    Default size is the first menu size (e.g. 'Small') when available.
    """
    if not item:
        return {"ok": False, "error": "No item specified."}
    try:
        quantity = int(quantity or 1)
    except Exception:
        quantity = 1
    if quantity < 1:
        quantity = 1

    lock, CART, _, _ = _get_store(call_sid)
    async with lock:
        current_total = _cart_total_pizzas(CART)
        if current_total + quantity > globals().get("MAX_PIZZAS", MAX_PIZZAS):
            return {"ok": False, "error": f"Max {globals().get('MAX_PIZZAS', MAX_PIZZAS)} pizzas per order."}

        menu = _get_effective_menu() or {}

        # match flavor / item: prefer menu flavors, else try price keys
        normalized_item = _normalize(item)
        canonical_flavor = _match_with_aliases(normalized_item, menu.get("flavors", []), {})
        if not canonical_flavor:
            # try prices map keys as candidates
            prices_keys = menu.get("prices") or {}
            canonical_flavor = _match_with_aliases(normalized_item, list(prices_keys.keys()), {})
        if not canonical_flavor:
            return {"ok": False, "error": f"'{item}' is not on the menu."}
        canonical_item = canonical_flavor

        # toppings -> validate against menu toppings using TOPPING_ALIASES
        tops_in = [_normalize(t) for t in _ensure_list(toppings)]
        tops_out = []
        for t in tops_in:
            if not t:
                continue
            m = _match_with_aliases(t, menu.get("toppings", []), TOPPING_ALIASES)
            if not m:
                return {"ok": False, "error": f"Topping '{t}' not available."}
            tops_out.append(m)

        # choose default size (prefer menu sizes)
        sizes_list = menu.get("sizes") or []
        default_size = sizes_list[0] if sizes_list else "Small"

        item_obj = {
            "item": canonical_item,
            "toppings": tops_out,
            "size": size or default_size,
            "customer_name": customer_name,
            "address": address,
            "quantity": quantity,
        }
        CART.append(item_obj)
        return {"ok": True, "cart_count": len(CART), "item": item_obj}

async def remove_from_cart(index: int, *, call_sid: str | None = None):
    lock, CART, _, _ = _get_store(call_sid)
    async with lock:
        if not (0 <= index < len(CART)):
            return {"ok": False, "error": "Index out of range.", "cart_count": len(CART)}
        removed = CART.pop(index)
        return {"ok": True, "removed": removed, "cart_count": len(CART)}

async def modify_cart_item(index: int, flavor: str | None = None, toppings=None, size: str | None = None,
                           quantity: int | None = None, addons=None, *, call_sid: str | None = None):
    lock, CART, _, _ = _get_store(call_sid)
    async with lock:
        if not (0 <= index < len(CART)):
            return {"ok": False, "error": "Index out of range.", "cart_count": len(CART)}
        item = CART[index]
        menu = _get_effective_menu() or {}

        if flavor:
            f = _normalize(flavor)
            matched = _match_with_aliases(f, menu.get("flavors", []), {})
            if not matched:
                # also try prices keys
                matched = _match_with_aliases(f, list((menu.get("prices") or {}).keys()), {})
            if not matched:
                return {"ok": False, "error": f"'{flavor}' is not on the menu."}
            item["item"] = matched

        if toppings is not None:
            tops_in = [_normalize(t) for t in _ensure_list(toppings)]
            tops_out = []
            for t in tops_in:
                if not t:
                    continue
                m = _match_with_aliases(t, menu.get("toppings", []), TOPPING_ALIASES)
                if not m:
                    return {"ok": False, "error": f"Topping '{t}' not available."}
                tops_out.append(m)
            item["toppings"] = tops_out

        if size:
            item["size"] = size

        if quantity is not None:
            try:
                item["quantity"] = int(quantity)
            except Exception:
                item["quantity"] = 1

        if addons is not None:
            item["addons"] = _ensure_list(addons)

        return {"ok": True, "item": item, "cart_count": len(CART)}

async def set_size_quantity(index: int | None = None, size: str | None = None, quantity: int | None = None, *, call_sid: str | None = None):
    lock, CART, _, _ = _get_store(call_sid)
    async with lock:
        if not CART:
            return {"ok": False, "error": "Cart is empty."}
        i = index if index is not None else len(CART) - 1
        if not (0 <= i < len(CART)):
            return {"ok": False, "error": "Index out of range."}
        if size:
            CART[i]["size"] = size
        if quantity is not None:
            try:
                CART[i]["quantity"] = int(quantity)
            except Exception:
                CART[i]["quantity"] = 1
        return {"ok": True, "item": CART[i]}

async def get_cart(call_sid: str | None = None):
    lock, CART, _, _ = _get_store(call_sid)
    async with lock:
        return {"ok": True, "items": CART.copy(), "count": len(CART)}

# -------------------------
# Phone / orders utilities
# -------------------------
PHONE_RE = re.compile(r'\+?\d[\d\-\s()]{9,}\d')
_PHONE_E164_GENERIC = re.compile(r'^\+\d{7,15}$')

def normalize_phone(p: str | None) -> Optional[str]:
    if not p:
        return None
    p = p.strip()
    digits = re.sub(r'\D', '', p)
    if p.startswith('+'):
        candidate = '+' + digits
        if _PHONE_E164_GENERIC.fullmatch(candidate):
            return candidate
        return None
    if 7 <= len(digits) <= 15:
        return '+' + digits
    return None

def random_order_no() -> str:
    return f"{random.randint(0, 9999):04d}"

# -------------------------
# Checkout / finalize
# -------------------------
async def checkout_order(phone: str | None = None, address: str | None = None,
                         order_type: str | None = None, *, call_sid: str | None = None):
    ORDER_TYPE_VALUE = None
    if order_type is not None:
        ORDER_TYPE_VALUE = await save_order_type(call_sid=call_sid, order_type=order_type)

    lock, CART, _, PENDING_ORDERS = _get_store(call_sid)
    async with lock:
        if not CART:
            return {"ok": False, "error": "Cart is empty."}

        phone_norm = normalize_phone(phone) if phone else None

        if address is not None:
            address = address.strip() or None

        if phone_norm:
            try:
                from .orders_store import count_active_orders_for_phone
                active_orders = count_active_orders_for_phone(phone_norm)
            except Exception:
                active_orders = 0
            current_cart_size = _cart_total_pizzas(CART)
            total_orders = active_orders + current_cart_size
            if total_orders > MAX_ORDERS_PER_PHONE:
                return {
                    "ok": False,
                    "error": (f"You currently have {active_orders} active order(s). Adding {current_cart_size} more "
                              f"would exceed the limit of {MAX_ORDERS_PER_PHONE} active orders per phone number. "
                              f"Please wait for your current orders to be ready."),
                    "limit_reached": True,
                    "active_orders": active_orders,
                    "cart_pizzas": current_cart_size,
                    "max_allowed": MAX_ORDERS_PER_PHONE
                }

        order_no = random_order_no()
        cart_totals = calculate_cart_total(CART)

        order = {
            "order_number": order_no,
            "items": CART.copy(),
            "phone": phone_norm,
            "status": "received",
            "created_at": int(time.time()),
            "committed": False,
            "address": address,
            "order_type": ORDER_TYPE_VALUE,
            "pricing": {
                "subtotal": cart_totals.get("subtotal", 0.0),
                "items": cart_totals.get("items", []),
                "total": cart_totals.get("total", 0.0),
            },
            "total": cart_totals.get("total", 0.0),
        }
        PENDING_ORDERS[order_no] = order

    await finalize_order(order_no, call_sid=call_sid)
    return {"ok": True, **order}

async def finalize_order(order_number: str, *, call_sid: str | None = None):
    lock, CART, ORDERS, PENDING_ORDERS = _get_store(call_sid)
    await firebase_client.push("orderList", {order_number: PENDING_ORDERS.get(order_number)})
    add_order_fn = None
    now_iso_fn = None
    async with lock:
        if order_number not in PENDING_ORDERS:
            return {"ok": False, "error": "Pending order not found."}
        order = PENDING_ORDERS.pop(order_number)
        if CART:
            order["items"] = CART.copy()
        order["committed"] = True
        order.setdefault("saved_at", None)
        try:
            effective_cart = order.get("items", []) or []
            cart_totals = calculate_cart_total(effective_cart)
            order["pricing"] = {
                "subtotal": cart_totals.get("subtotal", 0.0),
                "items": cart_totals.get("items", []),
                "total": cart_totals.get("total", 0.0),
            }
            order["total"] = cart_totals.get("total", 0.0)
        except Exception:
            order.setdefault("pricing", {"subtotal": 0.0, "items": [], "total": order.get("total", 0.0)})
            order.setdefault("total", order.get("total", 0.0))

        ORDERS[order_number] = order
        CART.clear()
        try:
            from .orders_store import add_order, now_iso
            add_order_fn = add_order
            now_iso_fn = now_iso
            order["saved_at"] = now_iso_fn()
        except Exception:
            add_order_fn = None
            now_iso_fn = None

    if add_order_fn:
        try:
            await asyncio.to_thread(add_order_fn, order)
        except Exception as e:
            try:
                if call_sid:
                    _CALL_ORDER_TYPES.pop(call_sid, None)
            except Exception:
                pass
            return {"ok": True, **order, "warning": f"Failed to persist order: {e}"}

    try:
        if call_sid:
            _CALL_ORDER_TYPES.pop(call_sid, None)
    except Exception:
        pass

    return {"ok": True, **order}

async def discard_pending_order(order_number: str, *, call_sid: str | None = None):
    lock, CART, _, PENDING_ORDERS = _get_store(call_sid)
    async with lock:
        if order_number in PENDING_ORDERS:
            PENDING_ORDERS.pop(order_number)
            CART.clear()
            return {"ok": True, "discarded": True}
        return {"ok": False, "error": "Pending order not found."}

# -------------------------
# Order status & parsing helpers
# -------------------------
async def order_status(phone: str | None = None, order_number: str | None = None, *, call_sid: str | None = None):
    lock, _, _, _ = _get_store(call_sid)
    orders_path = os.path.join(os.path.dirname(__file__), "orders.json")
    try:
        with open(orders_path, "r") as fh:
            payload = json.load(fh)
            orders_list = payload.get("orders", []) if isinstance(payload, dict) else (payload or [])
    except Exception as e:
        publish("agent_function_error", {"name": "order_status", "error": str(e)})
        return {"ok": False, "error": f"Failed to read orders: {e}"}

    async with lock:
        if order_number:
            for order in orders_list:
                if order.get("order_number") == order_number:
                    return {"ok": True, "found": True, "order_number": order["order_number"], "status": order.get("status")}
            return {"ok": True, "found": False}
        if phone:
            normalized_phone = normalize_phone(phone)
            for order in orders_list:
                if order.get("phone") and normalize_phone(order.get("phone")) == normalized_phone:
                    return {"ok": True, "found": True, "order_number": order["order_number"], "status": order.get("status")}
            return {"ok": True, "found": False}
        return {"ok": False, "error": "phone or order_number required"}

def extract_phone_and_order(text: str | None):
    phone = None
    order = None
    if text:
        m = PHONE_RE.search(text)
        if m:
            phone = normalize_phone(m.group(0))
        m2 = re.search(r"\b(\d{4})\b", text)
        if m2:
            order = m2.group(1)
    return {"phone": phone, "order_number": order}

# -------------------------
# Order type persistence
# -------------------------
async def save_order_type(call_sid: str | None = None, order_type: str | None = None):
    if order_type is None:
        return None
    ot = str(order_type).strip().lower()
    normalized = VALID_ORDER_TYPES.get(ot)
    if normalized is None:
        if "pick" in ot:
            normalized = "pickup"
        elif "deliv" in ot:
            normalized = "delivery"
        else:
            return None

    lock, _, _, _ = _get_store(call_sid)
    async with lock:
        store = _get_order_type_store(call_sid)
        store["value"] = normalized
        try:
            loop = asyncio.get_event_loop()
            store["saved_at"] = int(loop.time()) if loop.is_running() else int(time.time())
        except Exception:
            store["saved_at"] = int(time.time())
    return store["value"]

async def get_order_type(call_sid: str | None = None):
    lock, _, _, _ = _get_store(call_sid)
    async with lock:
        store = _get_order_type_store(call_sid)
        return store.get("value")
