# app/agent_functions.py
from typing import Any, Dict, Optional, List
import asyncio
import json
from . import business_logic as bl
from .session import sessions
from .events import publish  # NEW

# ---------- Tool implementations (per-call) ----------
async def _add_to_cart(
    customer_name: Optional[str] = None,
    item: Optional[str] = None,
    flavor: Optional[str] = None,            # accept model's "flavor"
    toppings: Optional[List[str]] = None,
    size: Optional[str] = None,
    quantity: Optional[int] = None,
    address: Optional[str] = None,
    *,
    call_sid: Optional[str] = None
):
    """
    Bridge between the agent/function call and business logic.
    Accepts either `item` or `flavor` (model may send `flavor`).
    Also accepts `size` and `quantity` for pizzas.
    """
    # model sometimes sends `flavor` instead of `item`
    if not item and flavor:
        item = flavor

    if toppings is None:
        toppings = []
    if not quantity:
        quantity = 1

    # forward to business logic; business logic expects single-item additions
    # (if you want quantity semantics aggregated, implement in bl.add_to_cart)
    return await bl.add_to_cart(
        item=item,
        toppings=toppings,
        customer_name=customer_name,
        address=address,
        call_sid=call_sid,
        size=size,
        quantity=quantity,
    )


async def _remove_from_cart(index: int, *, call_sid: str | None = None):
    return await bl.remove_from_cart(index, call_sid=call_sid)


async def _modify_cart_item(index: int, flavor: str | None = None, toppings=None,
                            size: str | None = None, quantity: int | None = None, addons=None,
                            *, call_sid: str | None = None):
    # accept 'flavor' as alias for item
    return await bl.modify_cart_item(index, flavor, toppings, size, quantity, addons, call_sid=call_sid)


async def _set_size_quantity(index: int | None = None, size: str | None = None,
                             quantity: int | None = None, *, call_sid: str | None = None):
    return await bl.set_size_quantity(index, size, quantity, call_sid=call_sid)


async def _get_cart(*, call_sid: str | None = None):
    return await bl.get_cart(call_sid=call_sid)


# async def _checkout_order(phone: str | None = None, *, call_sid: str | None = None):
#     # Generate order number, but do not finalize.
#     res = await bl.checkout_order(phone, call_sid=call_sid)
#     if isinstance(res, dict) and res.get("ok"):
#         s = await sessions.get_or_create(call_sid or "unknown")
#         if res.get("phone"):
#             s.phone = res["phone"]
#         if res.get("address"):
#             s.address = res["address"]
#             # NOTE: do NOT auto-confirm here; explicit confirmation is required.
#         if res.get("order_number"):
#             s.order_number = res["order_number"]
#             # Tell dashboards an order number was assigned (pre-finalize)
#             await publish("orders", {
#                 "type": "order_locked",
#                 "order_number": s.order_number,
#                 "call_sid": call_sid,
#                 "address": s.address,
#             })
#     return res
async def _checkout_order(phone: str | None = None, address: str | None = None, *, call_sid: str | None = None):
    # Generate order number, but do not finalize.
    res = await bl.checkout_order(phone=phone, address=address, call_sid=call_sid)
    if isinstance(res, dict) and res.get("ok"):
        s = await sessions.get_or_create(call_sid or "unknown")
        if res.get("phone"):
            s.phone = res["phone"]
            s.phone_confirmed = False
        # prefer the value returned by bl.checkout_order, but fall back to the passed address if needed
        addr = res.get("address") if isinstance(res, dict) else None
        if not addr and address:
            addr = address
        if addr:
            s.address = addr
            s.address_confirmed = False  # require explicit confirmation later
        if res.get("order_number"):
            s.order_number = res["order_number"]
            # Tell dashboards an order number was assigned (pre-finalize)
            await publish("orders", {
                "type": "order_locked",
                "order_number": s.order_number,
                "call_sid": call_sid,
                "address": getattr(s, "address", None),
            })
    return res



async def _order_status(phone: str | None = None, order_number: str | None = None,
                        *, call_sid: str | None = None):
    return await bl.order_status(phone, order_number, call_sid=call_sid)


def _menu_summary():
    return bl.menu_summary()


def _extract_phone_and_order(text: str):
    return bl.extract_phone_and_order(text)


async def _save_phone_number(phone: str, *, call_sid: str | None = None):
    from .business_logic import normalize_phone
    s = await sessions.get_or_create(call_sid or "unknown")
    p = normalize_phone(phone)
    s.phone = p
    s.phone_confirmed = False  # <-- minimal change: do NOT auto-confirm
    return {"ok": bool(p), "phone": p}


# NEW: explicit confirmation tool (minimal addition)
async def _confirm_phone_number(confirmed: bool, *, call_sid: str | None = None):
    s = await sessions.get_or_create(call_sid or "unknown")
    s.phone_confirmed = bool(confirmed) and bool(s.phone)
    return {"ok": s.phone_confirmed, "phone": s.phone}


# Back-compat no-ops for staged flow (so the prompt doesn’t break)
async def _confirm_pending_to_cart(*, call_sid: str | None = None):
    # Our add_to_cart writes directly. Nothing to confirm.
    return {"ok": True, "staged": False}


async def _clear_pending_item(*, call_sid: str | None = None):
    # No staged item; just a no-op.
    return {"ok": True, "cleared": True}


async def _order_is_placed(*, call_sid: str | None = None):
    s = await sessions.get_or_create(call_sid or "unknown")
    placed = bool(s.order_number)
    return {"placed": placed, "order_number": s.order_number}

async def _save_address(address: str, *, call_sid: str | None = None):
    s = await sessions.get_or_create(call_sid or "unknown")
    # minimal normalization/validation can be added in bl.normalize_address if you have one
    s.address = address
    s.address_confirmed = False
    return {"ok": True, "address": address}


# ---------- Tool definitions (Deepgram Agent expects this schema) ----------
FUNCTION_DEFS: list[Dict[str, Any]] = [
    {
        "name": "menu_summary",
        "description": "Give a short human-style menu overview (pizzas, toppings, sizes, add-ons).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },

    # Cart ops
    {
        "name": "add_to_cart",
        "description": "Add a pizza to the cart (standard size unless specified).",
        "parameters": {
            "type": "object",
            "properties": {
                "flavor": {"type": "string", "description": "Pizza flavor (alias for item)."},
                "item": {"type": "string", "description": "Pizza flavor (alias for flavor)."},
                "toppings": {"type": "array", "items": {"type": "string"}},
                "size": {"type": "string", "description": "Small | Medium | Large"},
                "quantity": {"type": "integer", "minimum": 1},
                "addons": {"type": "array", "items": {"type": "string"}},
                "call_sid": {"type": "string", "description": "Optional Twilio call SID to bind this function call to a specific phone call/session."}
            },
            "required": ["flavor"],
        },
    },
    {
        "name": "remove_from_cart",
        "description": "Remove a pizza by index (0-based).",
        "parameters": {
            "type": "object",
            "properties": {"index": {"type": "integer", "minimum": 0}},
            "required": ["index"],
        },
    },
    {
        "name": "modify_cart_item",
        "description": "Modify an existing pizza in the cart by index.",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "minimum": 0},
                "flavor": {"type": "string"},
                "item": {"type": "string"},
                "toppings": {"type": "array", "items": {"type": "string"}},
                "size": {"type": "string"},
                "quantity": {"type": "integer"},
                "addons": {"type": "array", "items": {"type": "string"}},
                "call_sid": {"type": "string"}
            },
            "required": ["index"],
        },
    },
    {
        "name": "set_size_quantity",
        "description": "Update size and/or quantity for last item or by index.",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "minimum": 0},
                "size": {"type": "string"},
                "quantity": {"type": "integer", "minimum": 1},
                "call_sid": {"type": "string"}
            },
            "required": [],
        },
    },
    {
        "name": "get_cart",
        "description": "Get current cart contents to read back to customer.",
        "parameters": {"type": "object", "properties": {"call_sid": {"type": "string"}}, "required": []},
    },

    # Session helpers (compat)
    {
        "name": "order_is_placed",
        "description": "Return whether an order number has been generated in this call session.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
    "name": "save_address",
    "description": "Save the customer's delivery address (not confirmed).",
    "parameters": {
        "type": "object",
        "properties": {
            "address": {"type": "string"},
            "call_sid": {"type": "string"}
        },
        "required": ["address"]
    },
},


    # Checkout / status
    {
        "name": "checkout_order",
        "description": "Generate order number but don't finalize yet. Can be called once per order flow.",
        "parameters": {
            "type": "object",
            "properties": {"phone": {"type": "string"}, 
                           "call_sid": {"type": "string"},
                            "address": {"type": "string", "description": "Delivery address (optional)."}
                           },
            "required": [],
        },
    },
    {
        "name": "order_status",
        "description": "Look up order status by phone or order number.",
        "parameters": {
            "type": "object",
            "properties": {"phone": {"type": "string"}, "order_number": {"type": "string"}, "call_sid": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "extract_phone_and_order",
        "description": "Extract phone and 4-digit order number from free text.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "call_sid": {"type": "string"}},
            "required": ["text"],
        },
    },

    # Phone capture + confirmation (NEW)
    {
        "name": "save_phone_number",
        "description": "Save the customer's phone number for pickup/delivery (not confirmed).",
        "parameters": {
            "type": "object",
            "properties": {"phone": {"type": "string"}, "call_sid": {"type": "string"}},
            "required": ["phone"],
        },
    },
    {
        "name": "confirm_phone_number",
        "description": "Confirm (true) or reject (false) the previously provided phone number.",
        "parameters": {
            "type": "object",
            "properties": {"confirmed": {"type": "boolean"}, "call_sid": {"type": "string"}},
            "required": ["confirmed"],
        },
    },

    # Back-compat stubs (no staging in this build)
    {"name": "confirm_pending_to_cart", "description": "No-op in this build.", "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "clear_pending_item", "description": "No-op in this build.", "parameters": {"type": "object", "properties": {}, "required": []}},
]

# --- Map tool names to functions ---
FUNCTION_MAP: dict[str, Any] = {
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
    "confirm_phone_number": _confirm_phone_number,  # NEW
    "confirm_pending_to_cart": _confirm_pending_to_cart,
    "clear_pending_item": _clear_pending_item,
    "save_address": _save_address,

}


# ---------------------------
# Robust dispatcher to call functions (ensures call_sid injection)
# ---------------------------

async def call_agent_function(
    name: str,
    arguments: Any,
    *,
    connection_id: Optional[str] = None,
):
    """
    Dispatch a function call from the agent / model.

    Responsibilities:
      - Accept arguments that may be a JSON string or a dict.
      - Prefer explicit 'call_sid' in the arguments if provided.
      - Otherwise look up call_sid from sessions using connection_id.
      - Always pass call_sid as a keyword-only argument to the underlying function.
      - Return structured error dicts on failure and publish debug events.
    """

    func = FUNCTION_MAP.get(name)
    if not func:
        return {"ok": False, "error": f"Unknown function: {name}"}

    # Normalize arguments (they might arrive as JSON string)
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception as e:
            publish("agent_function_error", {"name": name, "error": f"Invalid JSON arguments: {e}", "raw": arguments})
            return {"ok": False, "error": "Invalid JSON arguments."}

    if arguments is None:
        arguments = {}

    if not isinstance(arguments, dict):
        publish("agent_function_error", {"name": name, "error": "Arguments must be an object/dict", "args": arguments})
        return {"ok": False, "error": "Arguments must be an object/dict."}

    # 1) explicit call_sid passed by the model
    call_sid = arguments.pop("call_sid", None)

    # 2) otherwise try to get call_sid from sessions mapping using connection_id
    if not call_sid and connection_id:
        sess = sessions.get(connection_id) or {}
        call_sid = sess.get("call_sid")

    # 2.5) Map common model fields -> our bridge (flavor -> item)
    if "flavor" in arguments and "item" not in arguments:
        arguments["item"] = arguments.pop("flavor")

    # optional: debug publish (uncomment if you want logs)
    # publish("debug", {"fn": name, "connection_id": connection_id, "call_sid_used": call_sid, "args": arguments})

    # Call the target function and ensure call_sid is always passed as kw-only
    try:
        result = await func(**arguments, call_sid=call_sid)
        # normalize result to include ok flag for consistency
        if not isinstance(result, dict):
            return {"ok": True, "result": result}
        return result
    except TypeError as te:
        publish("agent_function_error", {"name": name, "error": f"TypeError: {te}", "args": arguments, "call_sid": call_sid})
        return {"ok": False, "error": f"Function signature mismatch: {te}"}
    except Exception as e:
        publish("agent_function_error", {"name": name, "error": str(e), "args": arguments, "call_sid": call_sid})
        return {"ok": False, "error": f"Function {name} raised: {e}"}
