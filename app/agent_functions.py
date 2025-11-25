# app/agent_functions.py
from typing import Any, Dict, Optional, List, Coroutine
import asyncio
import json
import inspect
import logging

from . import business_logic as bl
from .session import sessions
from .events import publish  # may be sync or async

logger = logging.getLogger(__name__)

# Utility -------------------------------------------------------------------

async def _maybe_await_publish(event: str, payload: Dict[str, Any]) -> None:
    """
    Call publish(event, payload) whether publish is sync or async.
    Swallows exceptions but emits an error publish/log on failure.
    """
    try:
        res = publish(event, payload)
        if asyncio.iscoroutine(res) or isinstance(res, Coroutine):
            await res  # type: ignore
    except Exception as e:
        # log locally and try to notify via publish (best-effort)
        logger.exception("publish(%s) failed: %s", event, e)
        try:
            r = publish("agent_function_error", {"name": "_maybe_await_publish", "error": str(e), "event": event})
            if asyncio.iscoroutine(r) or isinstance(r, Coroutine):
                await r  # type: ignore
        except Exception:
            # give up
            logger.exception("secondary publish failed")

def _coerce_to_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        try:
            return json.loads(obj)
        except Exception:
            return {}
    return {}

def _func_accepts_call_sid(fn) -> bool:
    """
    Return True if fn signature accepts 'call_sid' as parameter (positional, kw or **kwargs).
    """
    try:
        sig = inspect.signature(fn)
        for p in sig.parameters.values():
            if p.kind in (p.VAR_KEYWORD, ) or p.name == "call_sid":
                return True
        return False
    except Exception:
        # be conservative
        return False

async def _safe_call(fn, /, *args, call_sid: Optional[str] = None, **kwargs):
    """
    Call fn with kwargs and optionally pass call_sid only if the function accepts it.
    Returns whatever fn returns (awaits if coroutine).
    """
    # ensure we don't overwrite existing call_sid in kwargs
    kwargs = dict(kwargs)
    if call_sid is not None and _func_accepts_call_sid(fn):
        kwargs["call_sid"] = call_sid

    res = fn(*args, **kwargs)
    if asyncio.iscoroutine(res) or isinstance(res, Coroutine):
        return await res  # type: ignore
    return res

# Tool implementations (per-call) -------------------------------------------

async def _add_to_cart(
    customer_name: Optional[str] = None,
    item: Optional[str] = None,
    flavor: Optional[str] = None,
    toppings: Optional[List[str]] = None,
    size: Optional[str] = None,
    quantity: Optional[int] = None,
    address: Optional[str] = None,
    *,
    call_sid: Optional[str] = None
):
    """
    Wrapper that normalizes aliases and calls business_logic.add_to_cart.
    Returns the underlying result and attaches a cart snapshot if available.
    """
    # alias handling
    if not item and flavor:
        item = flavor

    toppings = toppings or []
    quantity = int(quantity or 1)

    try:
        res = await _safe_call(
            bl.add_to_cart,
            item=item,
            toppings=toppings,
            customer_name=customer_name,
            address=address,
            size=size,
            quantity=quantity,
            call_sid=call_sid,
        )
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_add_to_cart:add_failed", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

    # try to fetch cart snapshot defensively
    cart_snapshot = None
    try:
        cart_snapshot = await _safe_call(bl.get_cart, call_sid=call_sid)
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_add_to_cart:get_cart_failed", "error": str(e), "call_sid": call_sid})

    if isinstance(res, dict):
        res.setdefault("cart_snapshot", cart_snapshot)
    else:
        res = {"ok": True, "result": res, "cart_snapshot": cart_snapshot}

    await _maybe_await_publish("agent_action", {"action": "add_to_cart", "call_sid": call_sid, "item": item, "result_ok": bool(res.get("ok")), "cart_snapshot_exists": bool(cart_snapshot)})
    return res

async def _remove_from_cart(index: int, *, call_sid: Optional[str] = None):
    try:
        return await _safe_call(bl.remove_from_cart, index, call_sid=call_sid)
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_remove_from_cart", "error": str(e), "index": index, "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

async def _modify_cart_item(index: int, flavor: Optional[str] = None, toppings=None,
                            size: Optional[str] = None, quantity: Optional[int] = None, addons=None,
                            *, call_sid: Optional[str] = None):
    # accept 'flavor' as alias for item (business logic expects 'flavor' in signature)
    try:
        return await _safe_call(bl.modify_cart_item, index, flavor, toppings, size, quantity, addons, call_sid=call_sid)
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_modify_cart_item", "error": str(e), "index": index, "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

async def _set_size_quantity(index: Optional[int] = None, size: Optional[str] = None,
                             quantity: Optional[int] = None, *, call_sid: Optional[str] = None):
    try:
        return await _safe_call(bl.set_size_quantity, index=index, size=size, quantity=quantity, call_sid=call_sid)
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_set_size_quantity", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

async def _get_cart(*, call_sid: Optional[str] = None):
    try:
        return await _safe_call(bl.get_cart, call_sid=call_sid)
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_get_cart", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

# Pricing wrappers ----------------------------------------------------------

async def _get_cart_totals_for_call(*, call_sid: Optional[str] = None):
    """
    Get cart snapshot then compute totals via bl.calculate_cart_total (defensive).
    """
    try:
        raw_cart = await _safe_call(bl.get_cart, call_sid=call_sid)
        # Handle different shapes
        if isinstance(raw_cart, str):
            try:
                raw_cart = json.loads(raw_cart)
            except Exception:
                await _maybe_await_publish("agent_function_error", {"name": "get_cart_totals_for_call", "error": "bl.get_cart returned string but json.loads failed", "raw_cart": raw_cart, "call_sid": call_sid})
                raw_cart = []

        cart = []
        if isinstance(raw_cart, list):
            cart = raw_cart
        elif isinstance(raw_cart, dict) and "items" in raw_cart and isinstance(raw_cart["items"], list):
            cart = raw_cart["items"]
        elif raw_cart is None:
            cart = []
        else:
            await _maybe_await_publish("agent_function_debug", {"note": "coercing cart to list", "type": type(raw_cart).__name__, "call_sid": call_sid})
            cart = []

        if hasattr(bl, "calculate_cart_total"):
            totals = bl.calculate_cart_total(cart)
        else:
            # fallback minimal totals
            items = []
            subtotal = 0.0
            for idx, it in enumerate(cart):
                qty = int(it.get("quantity") or it.get("qty") or 1) if isinstance(it, dict) else 1
                items.append({"index": idx, "item": (it.get("item") if isinstance(it, dict) else str(it)), "qty": qty, "unit_price": 0.0, "addons": [], "unit_total": 0.0, "line_total": 0.0, "raw_item": it})
            totals = {"subtotal": round(subtotal, 2), "items": items, "total": round(subtotal, 2)}

        if isinstance(totals, str):
            try:
                totals = json.loads(totals)
            except Exception:
                await _maybe_await_publish("agent_function_error", {"name": "get_cart_totals_for_call", "error": "bl.calculate_cart_total returned string but json.loads failed", "call_sid": call_sid})
                totals = {"subtotal": 0.0, "items": [], "total": 0.0}

        if not isinstance(totals, dict) or "subtotal" not in totals:
            await _maybe_await_publish("agent_function_error", {"name": "get_cart_totals_for_call", "error": "calculate_cart_total returned unexpected shape", "call_sid": call_sid, "totals_type": type(totals).__name__})
            totals = {"subtotal": 0.0, "items": [], "total": 0.0}

        await _maybe_await_publish("pricing", {"type": "cart_totals_requested", "call_sid": call_sid, "subtotal": totals.get("subtotal")})
        return {"ok": True, "pricing": totals}
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "get_cart_totals_for_call", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

async def _calculate_cart_total(cart: List[Dict[str, Any]], *, call_sid: Optional[str] = None):
    try:
        if isinstance(cart, str):
            try:
                cart = json.loads(cart)
            except Exception:
                return {"ok": False, "error": "cart must be a list or JSON-encoded list"}

        if not isinstance(cart, list):
            return {"ok": False, "error": "cart must be a list of items"}

        if hasattr(bl, "calculate_cart_total"):
            totals = bl.calculate_cart_total(cart)
        else:
            items = []
            subtotal = 0.0
            for idx, it in enumerate(cart):
                qty = int(it.get("quantity") or it.get("qty") or 1) if isinstance(it, dict) else 1
                items.append({"index": idx, "item": (it.get("item") if isinstance(it, dict) else str(it)), "qty": qty, "unit_price": 0.0, "addons": [], "unit_total": 0.0, "line_total": 0.0, "raw_item": it})
            totals = {"subtotal": round(subtotal, 2), "items": items, "total": round(subtotal, 2)}

        if isinstance(totals, str):
            try:
                totals = json.loads(totals)
            except Exception:
                await _maybe_await_publish("agent_function_error", {"name": "calculate_cart_total", "error": "returned string but json.loads failed", "call_sid": call_sid})
                totals = {"subtotal": 0.0, "items": [], "total": 0.0}

        if not isinstance(totals, dict):
            totals = {"subtotal": 0.0, "items": [], "total": 0.0}

        await _maybe_await_publish("pricing", {"type": "calculate_cart_total", "call_sid": call_sid, "subtotal": totals.get("subtotal")})
        return {"ok": True, "pricing": totals}
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "calculate_cart_total", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

async def _apply_pricing_adjustments(subtotal: float, order_type: Optional[str] = None, promo_code: Optional[str] = None, *, call_sid: Optional[str] = None):
    try:
        if subtotal is None:
            return {"ok": False, "error": "subtotal required"}

        if hasattr(bl, "apply_pricing_adjustments"):
            adj = bl.apply_pricing_adjustments(subtotal=subtotal, order_type=order_type, promo_code=promo_code)
            if isinstance(adj, str):
                try:
                    adj = json.loads(adj)
                except Exception:
                    adj = {}
            tax = float(adj.get("tax", 0.0)) if isinstance(adj, dict) else 0.0
            delivery_fee = float(adj.get("delivery_fee", 0.0)) if isinstance(adj, dict) else 0.0
            discount = float(adj.get("discount", 0.0)) if isinstance(adj, dict) else 0.0
            total = float(adj.get("total", round(subtotal + tax + delivery_fee - discount, 2)))
            result = {"tax": tax, "delivery_fee": delivery_fee, "discount": discount, "total": round(total, 2)}
        else:
            tax = round(subtotal * 0.05, 2)
            delivery_fee = 0.0 if (order_type and str(order_type).lower() == "pickup") else 40.0
            discount = 0.0
            if promo_code and str(promo_code).upper() == "SAVE10":
                discount = 10.0
            total = round(max(0.0, subtotal + tax + delivery_fee - discount), 2)
            result = {"tax": tax, "delivery_fee": delivery_fee, "discount": discount, "total": total}

        await _maybe_await_publish("pricing", {"type": "apply_pricing_adjustments", "call_sid": call_sid, "computed_total": result["total"]})
        return {"ok": True, **result}
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "apply_pricing_adjustments", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

# Checkout / session helpers -----------------------------------------------

async def _checkout_order(phone: Optional[str] = None, address: Optional[str] = None, order_type: Optional[str] = None, *, call_sid: Optional[str] = None):
    try:
        res = await _safe_call(bl.checkout_order, phone=phone, address=address, order_type=order_type, call_sid=call_sid)
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_checkout_order", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

    if isinstance(res, dict) and res.get("ok"):
        s = await sessions.get_or_create(call_sid or "unknown")
        if res.get("phone"):
            s.phone = res["phone"]
            s.phone_confirmed = False
        addr = res.get("address") if isinstance(res, dict) else None
        if not addr and address:
            addr = address
        if addr:
            s.address = addr
            s.address_confirmed = False
        if res.get("order_number"):
            s.order_number = res["order_number"]
            await _maybe_await_publish("orders", {
                "type": "order_locked",
                "order_number": s.order_number,
                "call_sid": call_sid,
                "address": addr,
            })
    return res

async def _order_status(phone: Optional[str] = None, order_number: Optional[str] = None, *, call_sid: Optional[str] = None):
    try:
        return await _safe_call(bl.order_status, phone=phone, order_number=order_number, call_sid=call_sid)
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_order_status", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

def _menu_summary():
    try:
        return bl.menu_summary()
    except Exception as e:
        # menu_summary is sync in bl; publish error
        try:
            # don't await here to avoid requiring loop - use maybe helper
            coro = _maybe_await_publish("agent_function_error", {"name": "_menu_summary", "error": str(e)})
            if asyncio.iscoroutine(coro):
                # fire-and-forget best-effort
                asyncio.ensure_future(coro)
        except Exception:
            pass
        return {"summary": "Menu unavailable", "flavors": [], "toppings": [], "addons": [], "sizes": [], "prices": {}}

def _extract_phone_and_order(text: str):
    try:
        return bl.extract_phone_and_order(text)
    except Exception as e:
        asyncio.ensure_future(_maybe_await_publish("agent_function_error", {"name": "_extract_phone_and_order", "error": str(e), "text": text}))
        return {"phone": None, "order_number": None}

async def _save_phone_number(phone: str, *, call_sid: Optional[str] = None):
    from .business_logic import normalize_phone
    try:
        s = await sessions.get_or_create(call_sid or "unknown")
        p = normalize_phone(phone)
        s.phone = p
        s.phone_confirmed = False
        return {"ok": bool(p), "phone": p}
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_save_phone_number", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

async def _confirm_phone_number(confirmed: bool, *, call_sid: Optional[str] = None):
    try:
        s = await sessions.get_or_create(call_sid or "unknown")
        s.phone_confirmed = bool(confirmed) and bool(s.phone)
        return {"ok": s.phone_confirmed, "phone": s.phone}
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_confirm_phone_number", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

async def _confirm_pending_to_cart(*, call_sid: Optional[str] = None):
    return {"ok": True, "staged": False}

async def _clear_pending_item(*, call_sid: Optional[str] = None):
    return {"ok": True, "cleared": True}

async def _order_is_placed(*, call_sid: Optional[str] = None):
    s = await sessions.get_or_create(call_sid or "unknown")
    placed = bool(getattr(s, "order_number", None))
    return {"placed": placed, "order_number": getattr(s, "order_number", None)}

async def _save_address(address: str, *, call_sid: Optional[str] = None):
    try:
        s = await sessions.get_or_create(call_sid or "unknown")
        s.address = address
        s.address_confirmed = False
        return {"ok": True, "address": address}
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_save_address", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

async def _save_order_type(order_type: str, *, call_sid: Optional[str] = None):
    try:
        res = await _safe_call(bl.save_order_type, call_sid=call_sid, order_type=order_type)
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_save_order_type", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

    s = await sessions.get_or_create(call_sid or "unknown")
    if res:
        s.order_type = res
        s.order_type_confirmed = True
        return {"ok": True, "order_type": res}
    return {"ok": False, "error": "Invalid order_type, expected pickup or delivery."}

async def _get_order_type(*, call_sid: Optional[str] = None):
    try:
        ot = await _safe_call(bl.get_order_type, call_sid=call_sid)
        if not ot:
            return {"ok": False, "order_type": None, "message": "No order type has been set yet for this order."}
        return {"ok": True, "order_type": ot, "message": f"The order type is {ot}."}
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": "_get_order_type", "error": str(e), "call_sid": call_sid})
        return {"ok": False, "error": str(e)}

# ---------- Tool definitions (Deepgram Agent expects this schema) ----------
FUNCTION_DEFS: List[Dict[str, Any]] = [
    {"name": "menu_summary", "description": "Give a short human-style menu overview (pizzas, toppings, sizes, add-ons).", "parameters": {"type": "object", "properties": {}, "required": []}},

    # Cart ops
    {
        "name": "add_to_cart",
        "description": "Add a pizza to the cart (standard size unless specified).",
        "parameters": {
            "type": "object",
            "properties": {
                "flavor": {"type": "string"},
                "item": {"type": "string"},
                "toppings": {"type": "array", "items": {"type": "string"}},
                "size": {"type": "string"},
                "quantity": {"type": "integer", "minimum": 1},
                "addons": {"type": "array", "items": {"type": "string"}},
                "call_sid": {"type": "string"},
            },
            "required": ["flavor"],
        },
    },
    {"name": "remove_from_cart", "description": "Remove a pizza by index (0-based).", "parameters": {"type": "object", "properties": {"index": {"type": "integer", "minimum": 0}}, "required": ["index"]}},
    {"name": "modify_cart_item", "description": "Modify an existing pizza in the cart by index.", "parameters": {"type": "object", "properties": {"index": {"type": "integer", "minimum": 0}, "flavor": {"type": "string"}, "item": {"type": "string"}, "toppings": {"type": "array", "items": {"type": "string"}}, "size": {"type": "string"}, "quantity": {"type": "integer"}, "addons": {"type": "array", "items": {"type": "string"}}, "call_sid": {"type": "string"}}, "required": ["index"]}},
    {"name": "set_size_quantity", "description": "Update size and/or quantity for last item or by index.", "parameters": {"type": "object", "properties": {"index": {"type": "integer", "minimum": 0}, "size": {"type": "string"}, "quantity": {"type": "integer", "minimum": 1}, "call_sid": {"type": "string"}}, "required": []}},
    {"name": "get_cart", "description": "Get current cart contents to read back to customer.", "parameters": {"type": "object", "properties": {"call_sid": {"type": "string"}}, "required": []}},

    {"name": "get_cart_totals_for_call", "description": "Return detailed pricing for the current session cart.", "parameters": {"type": "object", "properties": {"call_sid": {"type": "string"}}, "required": []}},
        {
        "name": "calculate_cart_total",
        "description": "Calculate detailed pricing for a provided cart payload.",
        "parameters": {
            "type": "object",
            "properties": {
                "cart": {
                    "type": "array",
                    # *** THIS 'items' OBJECT IS REQUIRED BY THE THINK PROVIDER ***
                    "items": {
                        "type": "object",
                        "properties": {
                            "item": {"type": "string"},
                            "flavor": {"type": "string"},
                            "size": {"type": "string"},
                            "quantity": {"type": "integer"},
                            "qty": {"type": "integer"},
                            "addons": {
                                "type": "array",
                                "items": {"type": "string"}
                            }
                        },
                        "required": []
                    },
                    "description": "Array of cart items. Each item may include item/flavor, size, quantity and addons."
                },
                "call_sid": {"type": "string", "description": "Optional Twilio call SID to bind to a session."}
            },
            "required": ["cart"]
        }
    },

    # Session helpers
    {"name": "order_is_placed", "description": "Return whether an order number has been generated in this call session.", "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "save_address", "description": "Save the customer's delivery address (not confirmed).", "parameters": {"type": "object", "properties": {"address": {"type": "string"}, "call_sid": {"type": "string"}}, "required": ["address"]}},

    # Checkout / status
    {"name": "checkout_order", "description": "Generate order number but don't finalize yet.", "parameters": {"type": "object", "properties": {"phone": {"type": "string"}, "address": {"type": "string"}, "order_type": {"type": "string"}, "call_sid": {"type": "string"}}, "required": []}},

    {"name": "apply_pricing_adjustments", "description": "Compute tax/delivery/discounts for a subtotal.", "parameters": {"type": "object", "properties": {"subtotal": {"type": "number"}, "order_type": {"type": "string"}, "promo_code": {"type": "string"}, "call_sid": {"type": "string"}}, "required": ["subtotal"]}},

    {"name": "order_status", "description": "Look up order status by phone or order number.", "parameters": {"type": "object", "properties": {"phone": {"type": "string"}, "order_number": {"type": "string"}, "call_sid": {"type": "string"}}, "required": []}},
    {"name": "save_order_type", "description": "Save the customer's order type (pickup or delivery).", "parameters": {"type": "object", "properties": {"order_type": {"type": "string"}, "call_sid": {"type": "string"}}, "required": ["order_type"]}},
    {"name": "get_order_type", "description": "Get the current session's order type (PICKUP or DELIVERY).", "parameters": {"type": "object", "properties": {"call_sid": {"type": "string"}}, "required": []}},

    {"name": "extract_phone_and_order", "description": "Extract phone and 4-digit order number from free text.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "call_sid": {"type": "string"}}, "required": ["text"]}},

    {"name": "save_phone_number", "description": "Save the customer's phone number for pickup/delivery (not confirmed).", "parameters": {"type": "object", "properties": {"phone": {"type": "string"}, "call_sid": {"type": "string"}}, "required": ["phone"]}},
    {"name": "confirm_phone_number", "description": "Confirm (true) or reject (false) the previously provided phone number.", "parameters": {"type": "object", "properties": {"confirmed": {"type": "boolean"}, "call_sid": {"type": "string"}}, "required": ["confirmed"]}},

    {"name": "confirm_pending_to_cart", "description": "No-op in this build.", "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "clear_pending_item", "description": "No-op in this build.", "parameters": {"type": "object", "properties": {}, "required": []}},
]

# --- Map tool names to functions ---
FUNCTION_MAP: Dict[str, Any] = {
    "menu_summary": _menu_summary,
    "add_to_cart": _add_to_cart,
    "remove_from_cart": _remove_from_cart,
    "modify_cart_item": _modify_cart_item,
    "set_size_quantity": _set_size_quantity,
    "get_cart": _get_cart,
    "order_is_placed": _order_is_placed,
    "checkout_order": _checkout_order,
    "order_status": _order_status,
    "extract_phone_and_order": _extract_phone_and_order,
    "save_phone_number": _save_phone_number,
    "confirm_phone_number": _confirm_phone_number,
    "confirm_pending_to_cart": _confirm_pending_to_cart,
    "clear_pending_item": _clear_pending_item,
    "save_address": _save_address,
    "get_order_type": _get_order_type,
    "save_order_type": _save_order_type,
    "get_cart_totals_for_call": _get_cart_totals_for_call,
    "calculate_cart_total": _calculate_cart_total,
    "apply_pricing_adjustments": _apply_pricing_adjustments,
}

# Dispatcher ----------------------------------------------------------------

async def call_agent_function(
    name: str,
    arguments: Any,
    *,
    connection_id: Optional[str] = None,
):
    """
    Dispatch a function call from the agent/model.

    - arguments may be a dict or a JSON string
    - prefer explicit 'call_sid' in arguments; otherwise try to derive from sessions with connection_id
    - pass call_sid to the target function only if it accepts it
    - publish errors for observability
    """
    func = FUNCTION_MAP.get(name)
    if not func:
        await _maybe_await_publish("agent_function_error", {"name": name, "error": f"Unknown function: {name}"})
        return {"ok": False, "error": f"Unknown function: {name}"}

    # parse arguments
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception as e:
            await _maybe_await_publish("agent_function_error", {"name": name, "error": f"Invalid JSON arguments: {e}", "raw": arguments})
            return {"ok": False, "error": "Invalid JSON arguments."}

    if arguments is None:
        arguments = {}

    if not isinstance(arguments, dict):
        await _maybe_await_publish("agent_function_error", {"name": name, "error": "Arguments must be an object/dict", "args": str(arguments)})
        return {"ok": False, "error": "Arguments must be an object/dict."}

    # pull explicit call_sid if provided
    call_sid = arguments.pop("call_sid", None)

    # fallback: get call_sid from sessions mapping using connection_id
    if not call_sid and connection_id:
        sess = sessions.get(connection_id) or {}
        call_sid = sess.get("call_sid")

    # map common model fields -> bridge
    if "flavor" in arguments and "item" not in arguments:
        arguments["item"] = arguments.pop("flavor")

    # attempt call
    try:
        # call the function; _safe_call will attach call_sid only when supported
        result = await _safe_call(func, **arguments, call_sid=call_sid)
        if not isinstance(result, dict):
            return {"ok": True, "result": result}
        return result
    except TypeError as te:
        await _maybe_await_publish("agent_function_error", {"name": name, "error": f"TypeError: {te}", "args": arguments, "call_sid": call_sid})
        return {"ok": False, "error": f"Function signature mismatch: {te}"}
    except Exception as e:
        await _maybe_await_publish("agent_function_error", {"name": name, "error": str(e), "args": arguments, "call_sid": call_sid})
        return {"ok": False, "error": f"Function {name} raised: {e}"}
