# app/business_logic.py
import re, time, random, asyncio
from typing import Dict, List, Any, Optional, Tuple

# Import the centralized settings module that provides get_menu()
from app import settings as settings_mod

# HELPER FUNCTIONS:

VALID_ORDER_TYPES = {
    "pickup": "pickup",
    "pick up": "pickup",
    "pick-up": "pickup",
    "p": "pickup",
    "delivery": "delivery",
    "d": "delivery",
}

# Keep limits as before
MAX_PIZZAS = 5
MAX_ORDERS_PER_PHONE = 5  # Maximum active pizzas total per phone number

# -----------------------------------------------------------------------------
# Per-call state (unchanged)
# -----------------------------------------------------------------------------
_legacy_lock = asyncio.Lock()
_legacy_CART: List[dict] = []
_legacy_ORDERS: Dict[str, dict] = {}
_legacy_PENDING_ORDERS: Dict[str, dict] = {}

_call_locks: Dict[str, asyncio.Lock] = {}
_CALL_CARTS: Dict[str, List[dict]] = {}
_CALL_ORDERS: Dict[str, Dict[str, dict]] = {}
_CALL_PENDING_ORDERS: Dict[str, Dict[str, dict]] = {}

def _get_effective_menu() -> Dict[str, Any]:
    """
    Always read the current normalized menu from app.settings.get_menu().
    Returns a dict with canonical keys: flavors, toppings, addons, sizes, prices (prices optional).
    """
    try:
        m = settings_mod.get_menu()
        if not isinstance(m, dict):
            return {}
        return m
    except Exception:
        return {}

def _normalize(s: str | None) -> str:
    return (s or "").strip().lower()

def _ensure_list(x):
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [str(i) for i in x if i is not None]
    return [str(x)]

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

# Aliases example (keep them lower-cased for matching)
ADDON_ALIASES = {
    "garlic bread": {"garlic bread", "garlicbread"},
}
TOPPING_ALIASES = {
    "paneer": {"paneer"},
    "onion": {"onion"},
    "capsicum": {"capsicum", "caps"},
    "mushrooms": {"mushrooms", "mushroom"},
    "sweet corn": {"sweet corn", "corn"},
}

def _match_with_aliases(value_norm: str, canonical_list: list[str], aliases: dict[str, set[str]]):
    """
    Return the canonical name from canonical_list that matches value_norm (case-insensitive),
    or None if no match. Uses aliases to expand matches.

    canonical_list is expected to be a list of display strings (e.g. ["Margherita", "Pepperoni"])
    """
    if not value_norm:
        return None

    value_norm = value_norm.strip().lower()

    # Build normalized -> canonical map for canonical_list
    canonical_map = {}
    for c in canonical_list:
        if c is None:
            continue
        canonical_map[str(c).strip().lower()] = c  # normalized -> original (display form)

    # 1) exact normalized match against canonical list
    if value_norm in canonical_map:
        return canonical_map[value_norm]

    # 2) aliases matching
    for canonical, alias_set in aliases.items():
        canonical_norm = canonical.strip().lower()
        if value_norm == canonical_norm:
            return canonical_map.get(canonical_norm, canonical)
        for a in alias_set:
            if value_norm == a.strip().lower() or value_norm in a.strip().lower() or a.strip().lower() in value_norm:
                return canonical_map.get(canonical_norm, canonical)

    # 3) fuzzy match against canonical_list items (substring)
    for c_norm, c_orig in canonical_map.items():
        if value_norm in c_norm or c_norm in value_norm:
            return c_orig

    return None

def menu_summary():
    """
    Return the current menu summary using the live menu from settings.
    Keeps the original response shape so callers don't need to change.
    """
    m = _get_effective_menu() or {}
    return {
        "summary": m.get("summary", "We offer a selection of pizzas."),
        "flavors": m.get("flavors", []),
        "toppings": m.get("toppings", []),
        "addons": m.get("addons", []),
        "sizes": m.get("sizes", []),
        "prices": m.get("prices", {}),
    }

# -----------------------------------------------------------------------------
# Cart ops (pizza aware)
# -----------------------------------------------------------------------------

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
    Add a pizza item to the cart.

    Parameters:
      - item: pizza flavor / item name (required)
      - toppings: list of topping names (optional)
      - customer_name: name of the customer (optional)
      - address: delivery address (optional)
      - size: Small|Medium|Large or menu-specific size (optional)
      - quantity: number of identical pizzas to add (optional, default 1)
      - call_sid: optional call/session id (keyword-only)
    """
    # safe fallback for maximum pizzas per order (use existing constant if present)
    MAX_PIZZAS_LOCAL = globals().get("MAX_PIZZAS", MAX_PIZZAS)

    if not item:
        return {"ok": False, "error": "No item specified."}

    lock, CART, _, _ = _get_store(call_sid)
    async with lock:
        if len(CART) + (quantity or 1) > MAX_PIZZAS_LOCAL:
            return {"ok": False, "error": f"Max {MAX_PIZZAS_LOCAL} pizzas per order."}

        # get live menu
        menu = _get_effective_menu() or {}

        # normalize incoming item and find canonical flavor using matcher
        normalized_item = _normalize(item)
        canonical_flavor = _match_with_aliases(normalized_item, menu.get("flavors", []), {})
        if not canonical_flavor:
            return {"ok": False, "error": f"'{item}' is not on the menu."}
        # store canonical flavor (keeps original capitalization from menu)
        canonical_item = canonical_flavor

        # process toppings
        tops_in = [_normalize(t) for t in _ensure_list(toppings)]
        tops_out = []
        for t in tops_in:
            if not t:
                continue
            m = _match_with_aliases(t, menu.get("toppings", []), TOPPING_ALIASES)
            if not m:
                return {"ok": False, "error": f"Topping '{t}' not available."}
            tops_out.append(m)

        # process addons if present in arguments (compat)
        adds_out = []
        # leave addons processing for modify_cart_item if needed

        # default size: prefer first menu size if available
        default_size = None
        sizes_list = menu.get("sizes") or []
        if sizes_list:
            # pick first element as a reasonable default
            default_size = sizes_list[0]

        # build item object and append to cart (respect quantity by appending multiple entries)
        for _ in range(quantity or 1):
            item_obj = {
                "item": canonical_item,
                "toppings": tops_out.copy(),
                "size": size or default_size,
                "customer_name": customer_name,
                "address": address,
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

        # use live menu for matching
        menu = _get_effective_menu() or {}

        if flavor:
            f = _normalize(flavor)
            matched = _match_with_aliases(f, menu.get("flavors", []), {})
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

        if quantity:
            # naive: don't expand or collapse cart; just attach quantity field
            item["quantity"] = quantity

        return {"ok": True, "item": item, "cart_count": len(CART)}

async def set_size_quantity(index: int | None = None, size: str | None = None, quantity: int | None = None, *, call_sid: str | None = None):
    lock, CART, _, _ = _get_store(call_sid)
    async with lock:
        if not CART:
            return {"ok": False, "error": "Cart is empty."}
        i = index if index is not None else len(CART) - 1
        if not (0 <= i < len(CART)):
            return {"ok": False, "error": "Index out of range."}
        if size: CART[i]["size"] = size
        if quantity: CART[i]["quantity"] = quantity
        return {"ok": True, "item": CART[i]}

async def get_cart(call_sid: str | None = None):
    lock, CART, _, _ = _get_store(call_sid)
    async with lock:
        return {"ok": True, "items": CART.copy(), "count": len(CART)}

# --- Phone / orders ---
PHONE_RE = re.compile(r'\+?\d[\d\-\s()]{9,}\d')
US_E164 = re.compile(r'^\+1\d{10}$')

_PHONE_E164_GENERIC = re.compile(r'^\+\d{7,15}$')  # generic E.164-ish: +<7..15 digits>

def normalize_phone(p: str | None) -> str | None:

    # Normalize a phone string to E.164-style (leading '+', digits only).
    # Accepts:
    #   - '+918777684725' -> '+918777684725'
    #   - '918777684725'  -> '+918777684725'
    #   - '9877684725'    -> '+9877684725'   (will be treated as numeric with no country prefix)
    # Returns None for clearly invalid values.

    if not p:
        return None

    # strip whitespace and common separators
    p = p.strip()
    digits = re.sub(r'\D', '', p)

    # If original had a leading '+', prefer to return +digits (validate length)
    if p.startswith('+'):
        candidate = '+' + digits
        if _PHONE_E164_GENERIC.fullmatch(candidate):
            return candidate
        return None

    # If no leading '+', but digits length looks like an international/E.164 number (7-15 digits),
    # return '+' + digits. This allows '918777684725' -> '+918777684725'.
    if 7 <= len(digits) <= 15:
        return '+' + digits

    # otherwise invalid
    return None

def random_order_no() -> str:
    n = random.randint(0, 9999)
    return f"{n:04d}"
# -------------------------------------------------------------------------
# Checkout / finalize flow (unchanged logic, only minor adjustments)
# -------------------------------------------------------------------------
async def checkout_order(phone: str | None = None, address: str | None = None,
                         order_type: str | None = None, *, call_sid: str | None = None):
    # First: if order_type was provided, save it without holding the per-call lock
    ORDER_TYPE_VALUE = None
    if order_type is not None:
        ORDER_TYPE_VALUE = await save_order_type(call_sid=call_sid, order_type=order_type)

    lock, CART, _, PENDING_ORDERS = _get_store(call_sid)
    async with lock:
        if not CART:
            return {"ok": False, "error": "Cart is empty."}

        phone_norm = normalize_phone(phone) if phone else None

        # normalize address early so it's defined and safe to reference later
        if address is not None:
            address = address.strip() or None

        if phone_norm:
            from .orders_store import count_active_orders_for_phone
            active_orders = count_active_orders_for_phone(phone_norm)
            current_cart_size = len(CART)
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
        order = {
            "order_number": order_no,
            "items": CART.copy(),
            "phone": phone_norm,
            "status": "received",
            "created_at": int(time.time()),
            "committed": False,
            "address": address,
            "order_type": ORDER_TYPE_VALUE,
        }
        PENDING_ORDERS[order_no] = order

    # finalize outside the lock to reduce lock contention (finalize acquires lock internally)
    await finalize_order(order_no, call_sid=call_sid)
    return {"ok": True, **order}

async def finalize_order(order_number: str, *, call_sid: str | None = None):
    lock, CART, ORDERS, PENDING_ORDERS = _get_store(call_sid)

    # Prepare the order under the lock to keep in-memory state consistent
    add_order_fn = None
    now_iso_fn = None
    async with lock:
        if order_number not in PENDING_ORDERS:
            return {"ok": False, "error": "Pending order not found."}

        order = PENDING_ORDERS.pop(order_number)

        if CART:
            order["items"] = CART.copy()

        order["committed"] = True

        if "created_at" not in order:
            order["created_at"] = int(time.time())

        order.setdefault("saved_at", None)

        if "total" not in order:
            order["total"] = None

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

    # Persist to disk off the event loop if we have the persistence function.
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

# -------------------------------------------------------------------------
# order_status (reads orders.json as before)
# -------------------------------------------------------------------------
import os
import json
async def order_status(phone: str | None = None, order_number: str | None = None, *, call_sid: str | None = None):
    lock, _, _, _ = _get_store(call_sid)
    ORDERS=os.path.join(os.path.dirname(__file__), 'orders.json')
    ORDERS=json.load(open(ORDERS,'r'))
    ORDERS=dict(ORDERS)
    ORDERS = ORDERS.get("orders", [])
    
    async with lock:
        if order_number:
            for order in ORDERS:
                if order.get("order_number") == order_number:
                    return {"found": True, "order_number": order['order_number'], "status": order["status"]}                    
            return None
        if phone:
            for order in ORDERS:
                if order.get("phone") == phone:
                    return {"found": True, "order_number": order['order_number'], "status": order["status"]}                    
            return None
        return {"found": False}

def extract_phone_and_order(text: str | None):
    phone = None
    order = None
    if text:
        m = PHONE_RE.search(text)
        if m:
            phone = normalize_phone(m.group(0))
        m2 = re.search(r'\b(\d{4})\b', text)
        if m2:
            order = m2.group(1)
    return {"phone": phone, "order_number": order}

# near the other per-call stores add:
_CALL_ORDER_TYPES: Dict[str, Dict[str, Any]] = {}
_legacy_ORDER_TYPE: Dict[str, Any] = {}

# Helper to access per-call order_type store (keeps _get_store unchanged)
def _get_order_type_store(call_sid: Optional[str]):
    if not call_sid:
        return _legacy_ORDER_TYPE
    ot = _CALL_ORDER_TYPES.get(call_sid)
    if ot is None:
        ot = _CALL_ORDER_TYPES[call_sid] = {}
    return ot

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
    """
    Return the stored order_type value (e.g. 'pickup'/'delivery') or None.
    Acquires per-call lock for consistent reads.
    """
    lock, _, _, _ = _get_store(call_sid)
    async with lock:
        store = _get_order_type_store(call_sid)
        return store.get("value")










# # old logic for app/business_logic.py (does not include variable omenu from api)
# import re, time, random, asyncio
# from typing import Dict, List, Any, Optional, Tuple

# # HELPER FUNCTIONS:


# VALID_ORDER_TYPES = {
#     "pickup": "pickup",
#     "pick up": "pickup",
#     "pick-up": "pickup",
#     "p": "pickup",
#     "delivery": "delivery",
#     "d": "delivery",
# }

# # --- Menu (pizzas, toppings, sizes, add-ons) ---
# MENU = {
#     "flavors": ["Cheezy 7", "Las Vegas Treat", "Country Side", "La Pinoz Chicken Pizza"],
#     "toppings": ["paneer", "onion", "capsicum", "mushrooms", "sweet corn"],
#     "addons": ["coke", "garlic bread", "choco lava cake"],
#     "sizes": ["Small", "Medium", "Large"],
# }
# MAX_PIZZAS = 5
# MAX_ORDERS_PER_PHONE = 5  # Maximum active pizzas total per phone number

# # -----------------------------------------------------------------------------
# # Per-call state
# # -----------------------------------------------------------------------------
# _legacy_lock = asyncio.Lock()
# _legacy_CART: List[dict] = []
# _legacy_ORDERS: Dict[str, dict] = {}
# _legacy_PENDING_ORDERS: Dict[str, dict] = {}

# _call_locks: Dict[str, asyncio.Lock] = {}
# _CALL_CARTS: Dict[str, List[dict]] = {}
# _CALL_ORDERS: Dict[str, Dict[str, dict]] = {}
# _CALL_PENDING_ORDERS: Dict[str, Dict[str, dict]] = {}

# def _normalize(s: str | None) -> str:
#     return (s or "").strip().lower()

# def _ensure_list(x):
#     if x is None:
#         return []
#     if isinstance(x, (list, tuple)):
#         return [str(i) for i in x if i is not None]
#     return [str(x)]

# def _get_store(call_sid: Optional[str]) -> Tuple[asyncio.Lock, List[dict], Dict[str, dict], Dict[str, dict]]:
#     if not call_sid:
#         return _legacy_lock, _legacy_CART, _legacy_ORDERS, _legacy_PENDING_ORDERS

#     lock = _call_locks.get(call_sid)
#     if not lock:
#         lock = _call_locks[call_sid] = asyncio.Lock()
#     cart = _CALL_CARTS.get(call_sid)
#     if cart is None:
#         cart = _CALL_CARTS[call_sid] = []
#     orders = _CALL_ORDERS.get(call_sid)
#     if orders is None:
#         orders = _CALL_ORDERS[call_sid] = {}
#     pending = _CALL_PENDING_ORDERS.get(call_sid)
#     if pending is None:
#         pending = _CALL_PENDING_ORDERS[call_sid] = {}
#     return lock, cart, orders, pending

# # Aliases example (keep them lower-cased for matching)
# ADDON_ALIASES = {
#     "garlic bread": {"garlic bread", "garlicbread"},
# }
# TOPPING_ALIASES = {
#     "paneer": {"paneer"},
#     "onion": {"onion"},
#     "capsicum": {"capsicum", "caps"},
#     "mushrooms": {"mushrooms", "mushroom"},
#     "sweet corn": {"sweet corn", "corn"},
# }

# def _match_with_aliases(value_norm: str, canonical_list: list[str], aliases: dict[str, set[str]]):
#     """
#     Return the canonical name from canonical_list that matches value_norm (case-insensitive),
#     or None if no match. Uses aliases to expand matches.
#     """
#     if not value_norm:
#         return None

#     value_norm = value_norm.strip().lower()

#     # Build normalized -> canonical map for canonical_list
#     canonical_map = {}
#     for c in canonical_list:
#         canonical_map[c.strip().lower()] = c  # normalized -> original (display form)

#     # 1) exact normalized match against canonical list
#     if value_norm in canonical_map:
#         return canonical_map[value_norm]

#     # 2) aliases matching
#     for canonical, alias_set in aliases.items():
#         canonical_norm = canonical.strip().lower()
#         if value_norm == canonical_norm:
#             return canonical_map.get(canonical_norm, canonical)
#         for a in alias_set:
#             if value_norm == a.strip().lower() or value_norm in a.strip().lower() or a.strip().lower() in value_norm:
#                 return canonical_map.get(canonical_norm, canonical)

#     # 3) fuzzy match against canonical_list items
#     for c_norm, c_orig in canonical_map.items():
#         if value_norm in c_norm or c_norm in value_norm:
#             return c_orig

#     return None

# def menu_summary():
#     return {
#         "summary": (
#             "We offer a selection of pizzas. "
#             "Toppings: paneer, onion, capsicum, mushrooms, sweet corn. "
#             "Add-ons: garlic bread, coke, choco lava cake."
#         ),
#         "flavors": MENU["flavors"],
#         "toppings": MENU["toppings"],
#         "addons": MENU["addons"],
#         "sizes": MENU["sizes"],
#     }

# # -----------------------------------------------------------------------------
# # Cart ops (pizza aware)
# # -----------------------------------------------------------------------------

# async def add_to_cart(
#     item: str,
#     toppings=None,
#     customer_name: Optional[str] = None,
#     address: Optional[str] = None,
#     *,
#     call_sid: Optional[str] = None,
#     size: Optional[str] = None,
#     quantity: Optional[int] = 1,
# ):
#     """
#     Add a pizza item to the cart.

#     Parameters:
#       - item: pizza flavor / item name (required)
#       - toppings: list of topping names (optional)
#       - customer_name: name of the customer (optional)
#       - address: delivery address (optional)
#       - size: Small|Medium|Large (optional)
#       - quantity: number of identical pizzas to add (optional, default 1)
#       - call_sid: optional call/session id (keyword-only)
#     """
#     # safe fallback for maximum pizzas per order (use existing constant if present)
#     MAX_PIZZAS_LOCAL = globals().get("MAX_PIZZAS", MAX_PIZZAS)

#     if not item:
#         return {"ok": False, "error": "No item specified."}

#     lock, CART, _, _ = _get_store(call_sid)
#     async with lock:
#         if len(CART) + (quantity or 1) > MAX_PIZZAS_LOCAL:
#             return {"ok": False, "error": f"Max {MAX_PIZZAS_LOCAL} pizzas per order."}

#         # normalize incoming item and find canonical flavor using matcher
#         normalized_item = _normalize(item)
#         canonical_flavor = _match_with_aliases(normalized_item, MENU.get("flavors", []), {})
#         if not canonical_flavor:
#             return {"ok": False, "error": f"'{item}' is not on the menu."}
#         # store canonical flavor (keeps original capitalization from MENU)
#         canonical_item = canonical_flavor

#         # process toppings
#         tops_in = [_normalize(t) for t in _ensure_list(toppings)]
#         tops_out = []
#         for t in tops_in:
#             if not t:
#                 continue
#             m = _match_with_aliases(t, MENU.get("toppings", []), TOPPING_ALIASES)
#             if not m:
#                 return {"ok": False, "error": f"Topping '{t}' not available."}
#             tops_out.append(m)

#         # process addons if present in arguments (compat)
#         adds_out = []
#         # leave addons processing for modify_cart_item if needed

#         # build item object and append to cart (respect quantity by appending multiple entries)
#         for _ in range(quantity or 1):
#             item_obj = {
#                 "item": canonical_item,
#                 "toppings": tops_out.copy(),
#                 "size": size or MENU["sizes"][1] if MENU.get("sizes") else None,
#                 "customer_name": customer_name,
#                 "address": address,
#             }
#             CART.append(item_obj)

#         return {"ok": True, "cart_count": len(CART), "item": item_obj}

# async def remove_from_cart(index: int, *, call_sid: str | None = None):
#     lock, CART, _, _ = _get_store(call_sid)
#     async with lock:
#         if not (0 <= index < len(CART)):
#             return {"ok": False, "error": "Index out of range.", "cart_count": len(CART)}
#         removed = CART.pop(index)
#         return {"ok": True, "removed": removed, "cart_count": len(CART)}

# async def modify_cart_item(index: int, flavor: str | None = None, toppings=None, size: str | None = None,
#                            quantity: int | None = None, addons=None, *, call_sid: str | None = None):
#     lock, CART, _, _ = _get_store(call_sid)
#     async with lock:
#         if not (0 <= index < len(CART)):
#             return {"ok": False, "error": "Index out of range.", "cart_count": len(CART)}
#         item = CART[index]

#         if flavor:
#             f = _normalize(flavor)
#             matched = _match_with_aliases(f, MENU["flavors"], {})
#             if not matched:
#                 return {"ok": False, "error": f"'{flavor}' is not on the menu."}
#             item["item"] = matched

#         if toppings is not None:
#             tops_in = [_normalize(t) for t in _ensure_list(toppings)]
#             tops_out = []
#             for t in tops_in:
#                 if not t:
#                     continue
#                 m = _match_with_aliases(t, MENU["toppings"], TOPPING_ALIASES)
#                 if not m:
#                     return {"ok": False, "error": f"Topping '{t}' not available."}
#                 tops_out.append(m)
#             item["toppings"] = tops_out

#         if size:
#             item["size"] = size

#         if quantity:
#             # naive: don't expand or collapse cart; just attach quantity field
#             item["quantity"] = quantity

#         return {"ok": True, "item": item, "cart_count": len(CART)}

# async def set_size_quantity(index: int | None = None, size: str | None = None, quantity: int | None = None, *, call_sid: str | None = None):
#     lock, CART, _, _ = _get_store(call_sid)
#     async with lock:
#         if not CART:
#             return {"ok": False, "error": "Cart is empty."}
#         i = index if index is not None else len(CART) - 1
#         if not (0 <= i < len(CART)):
#             return {"ok": False, "error": "Index out of range."}
#         if size: CART[i]["size"] = size
#         if quantity: CART[i]["quantity"] = quantity
#         return {"ok": True, "item": CART[i]}

# async def get_cart(call_sid: str | None = None):
#     lock, CART, _, _ = _get_store(call_sid)
#     async with lock:
#         return {"ok": True, "items": CART.copy(), "count": len(CART)}

# # --- Phone / orders ---
# PHONE_RE = re.compile(r'\+?\d[\d\-\s()]{9,}\d')
# US_E164 = re.compile(r'^\+1\d{10}$')

# _PHONE_E164_GENERIC = re.compile(r'^\+\d{7,15}$')  # generic E.164-ish: +<7..15 digits>

# def normalize_phone(p: str | None) -> str | None:

#     # Normalize a phone string to E.164-style (leading '+', digits only).
#     # Accepts:
#     #   - '+918777684725' -> '+918777684725'
#     #   - '918777684725'  -> '+918777684725'
#     #   - '9877684725'    -> '+9877684725'   (will be treated as numeric with no country prefix)
#     # Returns None for clearly invalid values.

#     if not p:
#         return None

#     # strip whitespace and common separators
#     p = p.strip()
#     digits = re.sub(r'\D', '', p)

#     # If original had a leading '+', prefer to return +digits (validate length)
#     if p.startswith('+'):
#         candidate = '+' + digits
#         if _PHONE_E164_GENERIC.fullmatch(candidate):
#             return candidate
#         return None

#     # If no leading '+', but digits length looks like an international/E.164 number (7-15 digits),
#     # return '+' + digits. This allows '918777684725' -> '+918777684725'.
#     if 7 <= len(digits) <= 15:
#         return '+' + digits

#     # otherwise invalid
#     return None

# def random_order_no() -> str:
#     n = random.randint(0, 9999)
#     return f"{n:04d}"

# # async def checkout_order(phone: str | None = None, *, call_sid: str | None = None):
# #     lock, CART, _, PENDING_ORDERS = _get_store(call_sid)
# #     async with lock:
# #         if not CART:
# #             return {"ok": False, "error": "Cart is empty."}
# #         phone_norm = normalize_phone(phone) if phone else None
# #         if address is not None:
# #             address = address.strip() or None
# #         if phone_norm:
# #             from .orders_store import count_active_orders_for_phone
# #             active_orders = count_active_orders_for_phone(phone_norm)
# #             current_cart_size = len(CART)
# #             total_orders = active_orders + current_cart_size
# #             if total_orders > MAX_ORDERS_PER_PHONE:
# #                 return {
# #                     "ok": False,
# #                     "error": (f"You currently have {active_orders} active order(s). Adding {current_cart_size} more "
# #                               f"would exceed the limit of {MAX_ORDERS_PER_PHONE} active orders per phone number. "
# #                               f"Please wait for your current orders to be ready."),
# #                     "limit_reached": True,
# #                     "active_orders": active_orders,
# #                     "cart_pizzas": current_cart_size,
# #                     "max_allowed": MAX_ORDERS_PER_PHONE
# #                 }

# #         order_no = random_order_no()
# #         order = {
# #             "order_number": order_no,
# #             "items": CART.copy(),
# #             "phone": phone_norm,
# #             "status": "received",
# #             "created_at": int(time.time()),
# #             "committed": False,
# #             "address": address,
# #         }
# #         PENDING_ORDERS[order_no] = order
# #         return {"ok": True, **order}



# # Checkout_order new function with address parameter

# # import time
# # from typing import Optional

# # async def checkout_order(phone: str | None = None, address: str | None = None, *, call_sid: str | None = None):
# #     lock, CART, _, PENDING_ORDERS = _get_store(call_sid)
# #     async with lock:
# #         if not CART:
# #             return {"ok": False, "error": "Cart is empty."}

# #         phone_norm = normalize_phone(phone) if phone else None

# #         # normalize address early so it's defined and safe to reference later
# #         if address is not None:
# #             address = address.strip() or None

# #         if phone_norm:
# #             from .orders_store import count_active_orders_for_phone
# #             active_orders = count_active_orders_for_phone(phone_norm)
# #             current_cart_size = len(CART)
# #             total_orders = active_orders + current_cart_size
# #             if total_orders > MAX_ORDERS_PER_PHONE:
# #                 return {
# #                     "ok": False,
# #                     "error": (f"You currently have {active_orders} active order(s). Adding {current_cart_size} more "
# #                               f"would exceed the limit of {MAX_ORDERS_PER_PHONE} active orders per phone number. "
# #                               f"Please wait for your current orders to be ready."),
# #                     "limit_reached": True,
# #                     "active_orders": active_orders,
# #                     "cart_pizzas": current_cart_size,
# #                     "max_allowed": MAX_ORDERS_PER_PHONE
# #                 }

# #         order_no = random_order_no()
# #         order = {
# #             "order_number": order_no,
# #             "items": CART.copy(),
# #             "phone": phone_norm,
# #             "status": "received",
# #             "created_at": int(time.time()),
# #             "committed": False,
# #             "address": address,
# #         }
# #         PENDING_ORDERS[order_no] = order
# #     await finalize_order(order_no, call_sid=call_sid)  # auto-finalize on checkout
# #     return {"ok": True, **order}


# # 
# # checkout_order new function with order_type parameter
# # 
# import time
# from typing import Optional

# async def checkout_order(phone: str | None = None, address: str | None = None,
#                          order_type: str | None = None, *, call_sid: str | None = None):
#     # First: if order_type was provided, save it **without** holding the per-call lock
#     ORDER_TYPE_VALUE = None
#     if order_type is not None:
#         ORDER_TYPE_VALUE = await save_order_type(call_sid=call_sid, order_type=order_type)

#     # now do normal locked processing for cart/limits and creating pending order
#     lock, CART, _, PENDING_ORDERS = _get_store(call_sid)
#     async with lock:
#         if not CART:
#             return {"ok": False, "error": "Cart is empty."}

#         phone_norm = normalize_phone(phone) if phone else None

#         # normalize address early so it's defined and safe to reference later
#         if address is not None:
#             address = address.strip() or None

#         if phone_norm:
#             from .orders_store import count_active_orders_for_phone
#             active_orders = count_active_orders_for_phone(phone_norm)
#             current_cart_size = len(CART)
#             total_orders = active_orders + current_cart_size
#             if total_orders > MAX_ORDERS_PER_PHONE:
#                 return {
#                     "ok": False,
#                     "error": (f"You currently have {active_orders} active order(s). Adding {current_cart_size} more "
#                               f"would exceed the limit of {MAX_ORDERS_PER_PHONE} active orders per phone number. "
#                               f"Please wait for your current orders to be ready."),
#                     "limit_reached": True,
#                     "active_orders": active_orders,
#                     "cart_pizzas": current_cart_size,
#                     "max_allowed": MAX_ORDERS_PER_PHONE
#                 }

#         order_no = random_order_no()
#         order = {
#             "order_number": order_no,
#             "items": CART.copy(),
#             "phone": phone_norm,
#             "status": "received",
#             "created_at": int(time.time()),
#             "committed": False,
#             "address": address,
#             "order_type": ORDER_TYPE_VALUE,
#         }
#         PENDING_ORDERS[order_no] = order

#     # finalize outside the lock to reduce lock contention (finalize acquires lock internally)
#     await finalize_order(order_no, call_sid=call_sid)
#     return {"ok": True, **order}

# # async def finalize_order(order_number: str, *, call_sid: str | None = None):
# #     lock, CART, ORDERS, PENDING_ORDERS = _get_store(call_sid)
# #     async with lock:
# #         if order_number not in PENDING_ORDERS:
# #             return {"ok": False, "error": "Pending order not found."}
# #         order = PENDING_ORDERS.pop(order_number)
# #         # If items still in CART, prefer those (keeps final snapshot)
# #         if CART:
# #             order["items"] = CART.copy()
# #         order["committed"] = True
# #         # ensure created_at exists
# #         if "created_at" not in order:
# #             order["created_at"] = int(time.time())
# #         # ensure saved_at for DB trace
# #         order.setdefault("saved_at", None)
# #         # optionally compute a simple total if you don't have pricing yet
# #         if "total" not in order:
# #             # crude placeholder: no pricing available yet
# #             order["total"] = None

# #         ORDERS[order_number] = order
# #         CART.clear()

# #         # Persist order to orders.json using orders_store
# #         try:
# #             # import inside function to avoid import cycles
# #             from .orders_store import add_order, now_iso
# #             # append saved_at timestamp
# #             order["saved_at"] = now_iso()
# #             add_order(order)
# #         except Exception as e:
# #             # don't fail the finalize if file write has a transient error
# #             return {"ok": True, **order, "warning": f"Failed to persist order: {e}"}
# #         try:
# #             if call_sid:
# #                 _CALL_ORDER_TYPES.pop(call_sid, None)
# #         except Exception:
# #             pass
# #         return {"ok": True, **order}

# async def finalize_order(order_number: str, *, call_sid: str | None = None):
#     lock, CART, ORDERS, PENDING_ORDERS = _get_store(call_sid)

#     # Prepare the order under the lock to keep in-memory state consistent
#     add_order_fn = None
#     now_iso_fn = None
#     async with lock:
#         if order_number not in PENDING_ORDERS:
#             return {"ok": False, "error": "Pending order not found."}

#         order = PENDING_ORDERS.pop(order_number)

#         # If items still in CART, prefer those (keeps final snapshot)
#         if CART:
#             order["items"] = CART.copy()

#         order["committed"] = True

#         # ensure created_at exists
#         if "created_at" not in order:
#             order["created_at"] = int(time.time())

#         # ensure saved_at for DB trace (will be set below)
#         order.setdefault("saved_at", None)

#         # optionally compute a simple total if you don't have pricing yet
#         if "total" not in order:
#             # crude placeholder: no pricing available yet
#             order["total"] = None

#         # Record in in-memory orders and clear cart under the lock
#         ORDERS[order_number] = order
#         CART.clear()

#         # Try to import the blocking persistence helper while still under the lock.
#         # We only import here to avoid import cycles; the actual write will happen off-thread.
#         try:
#             from .orders_store import add_order, now_iso
#             add_order_fn = add_order
#             now_iso_fn = now_iso
#             # stamp saved_at now (so in-memory state has it)
#             order["saved_at"] = now_iso_fn()
#         except Exception:
#             # If import fails, leave saved_at as-is (None) and we'll return a warning later.
#             add_order_fn = None
#             now_iso_fn = None

#     # At this point the lock is released.

#     # Persist to disk off the event loop if we have the persistence function.
#     if add_order_fn:
#         try:
#             # run blocking file IO in a thread so we don't block the event loop
#             await asyncio.to_thread(add_order_fn, order)
#         except Exception as e:
#             # Persistence failed, but order is still committed in-memory; return success with a warning.
#             # Optionally you could retry or enqueue for later retry.
#             # Also attempt cleanup of per-call order_type store even on failure.
#             try:
#                 if call_sid:
#                     _CALL_ORDER_TYPES.pop(call_sid, None)
#             except Exception:
#                 pass
#             return {"ok": True, **order, "warning": f"Failed to persist order: {e}"}

#     # Cleanup per-call order_type store to avoid memory leak
#     try:
#         if call_sid:
#             _CALL_ORDER_TYPES.pop(call_sid, None)
#     except Exception:
#         pass

#     return {"ok": True, **order}


# async def discard_pending_order(order_number: str, *, call_sid: str | None = None):
#     lock, CART, _, PENDING_ORDERS = _get_store(call_sid)
#     async with lock:
#         if order_number in PENDING_ORDERS:
#             PENDING_ORDERS.pop(order_number)
#             CART.clear()
#             return {"ok": True, "discarded": True}
#         return {"ok": False, "error": "Pending order not found."}


# # 
# # ORIGINAL LOGIC FOR order_status
# # 
# # async def order_status(phone: str | None = None, order_number: str | None = None, *, call_sid: str | None = None):
# #     lock, _, ORDERS, _ = _get_store(call_sid)
# #     async with lock:
# #         if order_number and order_number in ORDERS:
# #             o = ORDERS[order_number]
# #             return {"found": True, "order_number": order_number, "status": o["status"]}
# #         phone_norm = normalize_phone(phone) if phone else None
# #         if phone_norm:
# #             matches = [(k, v) for k, v in ORDERS.items() if v.get("phone") == phone_norm]
# #             if matches:
# #                 k, v = sorted(matches, key=lambda kv: kv[1]["created_at"], reverse=True)[0]
# #                 return {"found": True, "order_number": k, "status": v["status"]}
# #         return {"found": False}


# # 
# # CHANGED LOGICE FOR order_status to get the orders from the orders.json file
# # 
# import os
# import json
# async def order_status(phone: str | None = None, order_number: str | None = None, *, call_sid: str | None = None):
#     # lock, _, ORDERS, _ = _get_store(call_sid)
#     lock, _, _, _ = _get_store(call_sid)
#     ORDERS=os.path.join(os.path.dirname(__file__), 'orders.json')
#     ORDERS=json.load(open(ORDERS,'r'))
#     ORDERS=dict(ORDERS)
#     ORDERS = ORDERS.get("orders", [])
    
#     async with lock:
#         if order_number:
#             for order in ORDERS:
#                 if order.get("order_number") == order_number:
#                     return {"found": True, "order_number": order['order_number'], "status": order["status"]}                    
#             return None
#         # phone_norm = normalize_phone("+91555885548") if phone else None
#         # print(phone_norm)
#         if phone:
#             for order in ORDERS:
#                 if order.get("phone") == phone:
#                     return {"found": True, "order_number": order['order_number'], "status": order["status"]}                    
#             return None
#         return {"found": False}
# def extract_phone_and_order(text: str | None):
#     phone = None
#     order = None
#     if text:
#         m = PHONE_RE.search(text)
#         if m:
#             phone = normalize_phone(m.group(0))
#         m2 = re.search(r'\b(\d{4})\b', text)
#         if m2:
#             order = m2.group(1)
#     return {"phone": phone, "order_number": order}

# # near the other per-call stores add:
# _CALL_ORDER_TYPES: Dict[str, Dict[str, Any]] = {}
# _legacy_ORDER_TYPE: Dict[str, Any] = {}


# # Helper to access per-call order_type store (keeps _get_store unchanged)
# def _get_order_type_store(call_sid: Optional[str]):
#     if not call_sid:
#         return _legacy_ORDER_TYPE
#     ot = _CALL_ORDER_TYPES.get(call_sid)
#     if ot is None:
#         ot = _CALL_ORDER_TYPES[call_sid] = {}
#     return ot


# async def save_order_type(call_sid: str | None = None, order_type: str | None = None):
    
#     if order_type is None:
#         return None

#     # unify normalization to lowercase canonical values
#     ot = str(order_type).strip().lower()
#     normalized = VALID_ORDER_TYPES.get(ot)
#     if normalized is None:
#         # lenient matching
#         if "pick" in ot:
#             normalized = "pickup"
#         elif "deliv" in ot:
#             normalized = "delivery"
#         else:
#             return None

#     # acquire same lock as _get_store to avoid races with cart/finalize
#     lock, _, _, _ = _get_store(call_sid)
#     async with lock:
#         store = _get_order_type_store(call_sid)
#         store["value"] = normalized
#         try:
#             loop = asyncio.get_event_loop()
#             store["saved_at"] = int(loop.time()) if loop.is_running() else int(time.time())
#         except Exception:
#             store["saved_at"] = int(time.time())

#     return store["value"]



# async def get_order_type(call_sid: str | None = None):
#     """
#     Return the stored order_type value (e.g. 'pickup'/'delivery') or None.
#     Acquires per-call lock for consistent reads.
#     """
#     lock, _, _, _ = _get_store(call_sid)
#     async with lock:
#         store = _get_order_type_store(call_sid)
#         return store.get("value")
