# import os
# import logging
# import json
# from typing import Any, Dict, Optional, List
# import requests
# import time
# import asyncio

# logger = logging.getLogger(__name__)

# # --- Menu cache & TTL (single canonical declaration) ---
# _cached_menu: Optional[Dict[str, Any]] = None
# _cached_menu_ts: Optional[int] = None
# _MENU_CACHE_TTL: int = int(os.getenv("MENU_CACHE_TTL_SECONDS", "300"))  # default 5 minutes



# # --- Basic env-configurable values ---
# DG_API_KEY = os.getenv("DG_API_KEY")
# MENU_API_URL = os.getenv("MENU_API_URL")

# # Providers (defaults, can be overridden via env)

# AGENT_LANGUAGE = os.getenv("AGENT_LANGUAGE", "en-US")
# LISTEN_PROVIDER = {"type": "deepgram", "model": os.getenv("AGENT_STT_MODEL", "flux-general-en")}
# THINK_PROVIDER  = {"type": "google",   "model": os.getenv("AGENT_THINK_MODEL", "gemini-2.0-flash")}
# SPEAK_PROVIDER = {
#         "type": "eleven_labs",
#         "model_id": os.getenv("AGENT_TTS_MODEL", "eleven_multilingual_v2"),
#         "voice_id": os.getenv("AGENT_TTS_VOICE", "cgSgspJ2msm6clMCkdW9")
#       }

# def fetch_remote_menu(url: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
#     """
#     Fetch a remote menu JSON. Be resilient to common JSONBin URL shapes and
#     support private JSONBin v3 via JSONBIN_API_KEY env var (sent as X-Master-Key).

#     Tries:
#       - the provided URL
#       - url + '/latest'
#       - url + '/raw'
#       - url + '/raw/latest'
#       - url + '?meta=false'

#     Returns the parsed JSON dict on success, otherwise None.
#     """
#     if not url:
#         return None

#     headers = {"Accept": "application/json"}
#     api_key = os.getenv("JSONBIN_API_KEY") or os.getenv("JSONBIN_MASTER_KEY")
#     if api_key:
#         headers["X-Master-Key"] = api_key

#     # Candidate URLs to try (preserve original, but try common JSONBin variants)
#     base = url.rstrip("/")
#     candidates = [
#         url,
#         f"{base}/latest",
#         f"{base}/raw",
#         f"{base}/raw/latest",
#         f"{base}?meta=false",
#     ]

#     # Deduplicate while preserving order
#     seen = set()
#     tried = []
#     for c in candidates:
#         if c not in seen:
#             seen.add(c)
#             tried.append(c)

#     last_exc = None
#     for u in tried:
#         try:
#             resp = requests.get(u, timeout=timeout, headers=headers)
#         except requests.RequestException as e:
#             logger.warning("Failed to fetch MENU_API_URL %s: %s", u, e)
#             last_exc = e
#             continue

#         if resp.status_code == 200:
#             # Got something — try to parse JSON
#             try:
#                 return resp.json()
#             except ValueError as e:
#                 logger.warning("MENU_API_URL %s returned non-JSON response: %s", u, e)
#                 return None
#         else:
#             logger.debug("MENU_API_URL %s returned status %s", u, resp.status_code)
#             last_exc = RuntimeError(f"status {resp.status_code} for {u}")

#     # Nothing succeeded
#     logger.warning("Failed to fetch MENU_API_URL. Tried URLs: %s. Last error: %s", tried, last_exc)
#     return None

# def _normalize_remote_menu(raw: Any) -> Dict[str, Any]:
#     """
#     Turn the remote menu into a canonical menu dict.
#     Normalize price keys to lowercased stripped strings so lookups are case-insensitive.
#     """
#     if not raw:
#         return {"flavors": [], "toppings": [], "addons": [], "sizes": ["regular"], "prices": {}}

#     # unwrap potential wrappers
#     if isinstance(raw, dict) and "record" in raw and isinstance(raw["record"], dict):
#         raw = raw["record"]

#     if isinstance(raw, dict) and "menu" in raw:
#         raw = raw["menu"]

#     flavors: List[str] = []
#     toppings_set = set()
#     addons: List[str] = []
#     sizes_set = set()
#     prices: Dict[str, Dict[str, Optional[float]]] = {}



#     def _norm_key(k: str) -> str:
#         return str(k).strip().lower()

#     def _process_item(item: dict, treat_as_addon: bool = False):
#         if not isinstance(item, dict):
#             return
#         name = item.get("name") or item.get("title")
#         if not name:
#             return
#         name = str(name).strip()
#         if treat_as_addon:
#             addons.append(name)
#         else:
#             flavors.append(name)

#         # toppings or ingredients
#         t = item.get("toppings") or item.get("ingredients") or []
#         if isinstance(t, list):
#             for top in t:
#                 if top:
#                     toppings_set.add(str(top).strip())
#         elif isinstance(t, str):
#             toppings_set.add(t.strip())

#         # sizes/prices
#         s = item.get("sizes")
#         if isinstance(s, dict):
#             # store canonical (display) name and normalized price-keyed dict
#             prices.setdefault(name, {})
#             for size_key, size_val in s.items():
#                 if size_key is None:
#                     continue
#                 sizes_set.add(str(size_key).strip())
#                 price_val = None
#                 if isinstance(size_val, dict):
#                     price_val = size_val.get("price") or size_val.get("cost")
#                 elif isinstance(size_val, (int, float)):
#                     price_val = size_val
#                 try:
#                     # use normalized price key (lowercase)
#                     prices[name][str(size_key).strip()] = float(price_val) if price_val is not None else None
#                 except Exception:
#                     prices[name][str(size_key).strip()] = None
#         else:
#             price = item.get("price")
#             if price is not None:
#                 sizes_set.add("default")
#                 try:
#                     prices.setdefault(name, {})["default"] = float(price)
#                 except Exception:
#                     prices.setdefault(name, {})["default"] = None

#     # Candidate keys that commonly hold pizza items and addons
#     if isinstance(raw, dict):
#         main_sections = ["Pizza", "Pizzas", "pizza", "pizzas", "flavors", "items", "menu_items"]
#         addon_sections = ["Sides", "Drinks", "addons", "extras", "sides", "drinks"]

#         # First try explicit sections
#         for sec in main_sections:
#             sec_items = raw.get(sec)
#             if isinstance(sec_items, list):
#                 for it in sec_items:
#                     _process_item(it, treat_as_addon=False)

#         for sec in addon_sections:
#             sec_items = raw.get(sec)
#             if isinstance(sec_items, list):
#                 for it in sec_items:
#                     _process_item(it, treat_as_addon=True)

#         # Heuristic scan if no flavors found
#         if not flavors:
#             for k, v in raw.items():
#                 if isinstance(v, list) and v:
#                     sample = v[0]
#                     if isinstance(sample, dict) and ("sizes" in sample or "toppings" in sample or "description" in sample):
#                         for it in v:
#                             _process_item(it, treat_as_addon=False)
#                     else:
#                         for it in v:
#                             _process_item(it, treat_as_addon=True)

#     elif isinstance(raw, list):
#         for it in raw:
#             _process_item(it, treat_as_addon=False)

#     sizes = sorted(sizes_set) if sizes_set else ["regular"]
#     toppings = sorted(toppings_set)

#     # Normalize the prices mapping keys: map lowercased names to their size mappings.
#     normalized_prices: Dict[str, Dict[str, Optional[float]]] = {}
#     for display_name, size_map in prices.items():
#         disp = display_name.strip()
#         normalized_prices[disp] = {}
#         for size_key, price_val in (size_map or {}).items():
#             normalized_prices[disp][str(size_key).strip()] = (float(price_val) if price_val is not None else None)
#         # also expose a lowercased alias for lookup convenience
#         normalized_prices[disp.lower()] = normalized_prices[disp].copy()

#         # Also create a lowercased name alias for robust lookup by callers that use normalized names
#         normalized_key = display_name.strip().lower()
#         if normalized_key not in normalized_prices:
#             # avoid overwriting display-keyed map if collision
#             normalized_prices[normalized_key] = normalized_prices[display_name.strip()].copy()
    


#     return {
#         "flavors": flavors,
#         "toppings": toppings,
#         "addons": addons,
#         "sizes": sizes,
#         "prices": normalized_prices,
#     }

# def _empty_menu() -> Dict[str, Any]:
#     """Canonical empty menu when remote fetch fails (no local fallback)."""
#     return {"flavors": [], "toppings": [], "addons": [], "sizes": [], "prices": {}}


# def get_menu(force_refresh: bool = False) -> Dict[str, Any]:
#     """
#     Synchronous menu fetch using blocking requests.
#     Uses module-level cache with TTL. Only uses remote MENU_API_URL.
#     If the remote fetch fails, returns an empty canonical menu (no local fallback).
#     """
#     global _cached_menu, _cached_menu_ts

#     now = int(time.time())
#     if _cached_menu is not None and not force_refresh and _cached_menu_ts and (now - _cached_menu_ts) < _MENU_CACHE_TTL:
#         return _cached_menu

#     if not MENU_API_URL:
#         logger.error("MENU_API_URL not set; returning empty menu (no local fallback).")
#         _cached_menu = _empty_menu()
#         _cached_menu_ts = now
#         return _cached_menu

#     remote = fetch_remote_menu(MENU_API_URL)
#     if isinstance(remote, dict) and remote:
#         try:
#             _cached_menu = _normalize_remote_menu(remote)
#         except Exception:
#             logger.exception("Failed to normalize remote menu; returning empty menu.")
#             _cached_menu = _empty_menu()
#         _cached_menu_ts = now
#         return _cached_menu

#     # remote fetch failed — log and return empty menu (no fallback)
#     logger.error("Failed to fetch or parse remote menu from %s; returning empty menu.", MENU_API_URL)
#     _cached_menu = _empty_menu()
#     _cached_menu_ts = now
#     return _cached_menu

# import asyncio
# import time


# async def async_fetch_remote_menu(url: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
#     """
#     Run blocking fetch_remote_menu in a thread so async callers don't block the event loop.
#     """
#     loop = asyncio.get_running_loop()
#     return await loop.run_in_executor(None, lambda: fetch_remote_menu(url, timeout=timeout))




# async def async_get_menu(force_refresh: bool = False) -> Dict[str, Any]:
#     """
#     Async version of get_menu(). Mirrors synchronous behavior and cache TTL.
#     """
#     global _cached_menu, _cached_menu_ts

#     now = int(time.time())
#     if _cached_menu is not None and not force_refresh and _cached_menu_ts and (now - _cached_menu_ts) < _MENU_CACHE_TTL:
#         return _cached_menu

#     if not MENU_API_URL:
#         logger.error("MENU_API_URL not set; returning empty menu (no local fallback).")
#         _cached_menu = _empty_menu()
#         _cached_menu_ts = now
#         return _cached_menu

#     remote = await async_fetch_remote_menu(MENU_API_URL)
#     if isinstance(remote, dict) and remote:
#         try:
#             _cached_menu = _normalize_remote_menu(remote)
#         except Exception:
#             logger.exception("Failed to normalize remote menu; returning empty menu.")
#             _cached_menu = _empty_menu()
#         _cached_menu_ts = now
#         return _cached_menu

#     logger.error("Failed to fetch remote menu (async) from %s; returning empty menu.", MENU_API_URL)
#     _cached_menu = _empty_menu()
#     _cached_menu_ts = now
#     return _cached_menu

# # --- Prompt builder that tolerates missing keys ---
# def build_prompt_from_menu(menu: Optional[Dict[str, Any]] = None) -> str:
#     m = menu or get_menu()
#     flavors = m.get("flavors") or m.get("pizzas") or m.get("items") or []
#     toppings = m.get("toppings") or []
#     addons = m.get("addons") or m.get("extras") or []
#     sizes = m.get("sizes") or []

#     def to_list_of_strings(x):
#         if not x:
#             return []
#         if isinstance(x, dict):
#             return list(x.keys())
#         if isinstance(x, list):
#             return [str(i) for i in x]
#         return [str(x)]

#     flavors = to_list_of_strings(flavors)
#     toppings = to_list_of_strings(toppings)
#     addons = to_list_of_strings(addons)
#     sizes = to_list_of_strings(sizes)

#     snippet = {
#         "flavors": flavors,
#         "toppings": toppings,
#         "addons": addons,
#         "sizes": sizes,
#     }
#     try:
#         menu_snippet = json.dumps(snippet, indent=2, ensure_ascii=False)
#     except Exception:
#         menu_snippet = (
#             "Flavors: " + ", ".join(flavors) + ". "
#             "Toppings: " + ", ".join(toppings) + ". "
#             "Add-ons: " + ", ".join(addons) + ". "
#             "Sizes: " + ", ".join(sizes) + "."
#         )

#     prompt = (
#         "You are an AI pizza ordering assistant.\n\n"
#         "Use the following menu when making suggestions and validating user choices:\n"
#         f"{menu_snippet}\n\n"
#         "Ask clarifying questions when necessary (size, quantity, toppings, address). "
#         "Always confirm phone numbers before checkout. Do not finalize orders without explicit confirmation."
#     )
#     return prompt

# # --- Re-introduce build_deepgram_settings so other modules can import it ---
# def build_deepgram_settings(prompt: Optional[str] = None) -> Dict[str, Any]:
#     """
#     Build the Deepgram 'Settings' payload expected by agent_client / agent setup.
#     If prompt is not provided, it will be generated from the current menu.
#     """
#     effective_prompt = prompt or build_prompt_from_menu()
#     return {
#     "type": "Settings",
#     "audio": {
#         "input": {"encoding": "linear16", "sample_rate": 48000},
#         "output": {"encoding": "linear16", "sample_rate": 24000, "container": "none"},
#     },
#     "agent": {
#         "language": AGENT_LANGUAGE,
#         "listen": {"provider": LISTEN_PROVIDER},
#         "think": {
#             "provider": THINK_PROVIDER,
#             "prompt": ("You are an AI-powered Pizza Ordering Assistant for phone-call customers.\n\n"

#                 "High-level: Greet the caller, determine whether they want to place a new order or check an order status, "
#                 "and then guide them step-by-step to complete or check the order. Use the provided tool functions (menu_summary, "
#                 "add_to_cart, modify_cart_item, remove_from_cart, get_cart, save_order_type, save_phone_number, confirm_phone_number, "
#                 "save_address, checkout_order, order_status, extract_phone_and_order, get_cart_totals_for_call, calculate_cart_total, apply_pricing_adjustments) "
#                 "to perform actions — do not invent state or finalize an order without calling the appropriate tools.\n\n"

#                 "Staged ordering flow (follow exactly):\n"
#                 "1) Greeting: Say hello and ask whether they want to place an order or check an existing order. If checking, ask for phone or order number and call order_status.\n"
#                 "2) Menu: If ordering, call menu_summary when helpful and offer menu suggestions (flavors, sizes, toppings, add-ons).\n"
#                 "3) Build cart: Add pizzas using add_to_cart. If the caller wants adjustments, use modify_cart_item or remove_from_cart. Use set_size_quantity or quantity fields where required.\n"
#                 "4) Confirm cart: Call get_cart and read the cart back clearly (flavor, size, toppings, add-ons, quantity). Ask the caller to confirm the cart contents before proceeding.\n"
#                 "5) Pricing check (required before checkout): Always call get_cart_totals_for_call(call_sid=<current session>) to compute the detailed pricing breakdown (unit_price, qty, addons, unit_total, line_total, subtotal). If you need to price an ad-hoc cart payload instead, call calculate_cart_total. If your business needs tax/delivery/discount computations, call apply_pricing_adjustments with the subtotal to compute tax, delivery_fee, discount and final total. Attach the detailed pricing block to the pending order before calling checkout_order.\n"
#                 "6) Order type (required): Ask whether the order is PICKUP or DELIVERY. Call save_order_type to persist the choice. Do not proceed to collect address for PICKUP orders.\n"
#                 "7) Contact details:\n"
#                 "   - For PICKUP: request phone number, call save_phone_number, then call confirm_phone_number to confirm.\n"
#                 "   - For DELIVERY: request phone and full delivery address, call save_phone_number and save_address, and confirm the phone with confirm_phone_number.\n"
#                 "8) Final validation: Before checkout, re-read cart, pricing (subtotal and per-item line totals), order type, phone, and address (if delivery). Ask: 'Is everything correct?' Only proceed when customer explicitly says 'yes' or 'confirm'.\n"
#                 "9) Checkout: Call checkout_order to generate an order number (do not auto-finalize outside this call). Only after checkout_order returns an order number tell the caller the order number and expected next steps. Do NOT claim payment or completion—just give the order number and next steps.\n\n"

#                 "Tool usage rules and behavior:\n"
#                 "- Always use the provided tool that matches the intent (e.g., save_order_type for order type, save_address for delivery address). Use get_cart_totals_for_call to obtain pricing before checkout.\n"
#                 "- If the caller gives free-form text containing numbers, use extract_phone_and_order to parse potential phone or 4-digit order numbers.\n"
#                 "- If a requested flavor, topping, or add-on is not on the menu, politely tell the caller and offer alternatives from menu_summary.\n"
#                 "- Enforce limits: do not add more than the maximum allowed pizzas; inform the caller clearly if limits are reached.\n"
#                 "- When saving phone numbers, normalize but ask the user to confirm the final format before checkout.\n"
#                 "- Never finalize or claim the order is placed unless checkout_order returned an order number and the caller explicitly confirmed.\n\n"

#                 "Tone and responsibilities:\n"
#                 "- Be friendly, calm, and professional. Speak clearly and avoid jargon.\n"
#                 "- Guide the caller step-by-step, ask concise clarifying questions only when needed.\n"
#                 "- Repeat back important details (cart contents, pricing line items, phone, address, order type) and request explicit confirmation.\n"
#                 "- If the caller asks about an existing order, gather phone or order number and use order_status to answer.\n\n"

#                 "Your goal is to ensure the order is accurate, complete, and explicitly confirmed before checkout."
#             ),

#             "functions": [
#                 {
#                     "name": "menu_summary",
#                     "description": "Retrieve the current pizza menu, including available flavors, toppings, add-ons, and sizes.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "category": {
#                                 "type": "string",
#                                 "description": "Optional category to filter menu items (e.g., 'flavors', 'toppings', 'addons', 'sizes').",
#                             }
#                         },
#                         "required": [],
#                     },
#                 },
#                 {
#                     "name": "add_to_cart",
#                     "description": "Place a new pizza order with customer details and order items.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "item": {
#                                 "type": "string",
#                                 "description": "Pizza flavor or item name."
#                             },
#                             "flavor": {
#                                 "type": "string",
#                                 "description": "Pizza flavor (alias for item)."
#                             },
#                             "toppings": {
#                                 "type": "string",
#                                 "description": "Comma-separated list of toppings."
#                             },
#                             "size": 
#                             {
#                                 "type": "string", 
#                                 "description": "Small | Medium | Large"
#                             },
#                             "quantity": 
#                             {
#                                 "type": "integer", 
#                                 "minimum": 1
#                             },
#                             "address": 
#                             {
#                                 "type": "string", 
#                                 "description": "Full delivery address of customer including street, city, state, and zip code."
#                             },
#                             "addons": 
#                             {
#                                 "type": "array", 
#                                 "items": {"type": "string"}
#                             },
#                             "call_sid": 
#                             {
#                                 "type": "string", 
#                                 "description": "Optional Twilio call SID to bind this function call to a specific phone call/session."
#                             }
#                         },
#                         "required": ["flavor","size","quantity","call_sid"],
#                     },
#                 },
                

#                 {
#                     "name":"remove_from_cart",
#                     "description": "Remove a pizza by index (0-based).",
#                     "parameters": 
#                     {
#                         "type": "object",
#                         "properties": {"index": {"type": "integer", "minimum": 0}},
#                         "required": ["index"],
#                     },
#                 },

#                 {
#                     "name": "modify_cart_item",
#                     "description": "Modify an existing pizza in the cart by index.",
#                     "parameters": 
#                     {
#                         "type": "object",
#                         "properties": 
#                         {
#                             "index": {"type": "integer", "minimum": 0},
#                             "flavor": {"type": "string"},
#                             "item": {"type": "string"},
#                             "toppings": {"type": "array", "items": {"type": "string"}},
#                             "size": {"type": "string"},
#                             "quantity": {"type": "integer"},
#                             "addons": {"type": "array", "items": {"type": "string"}},
#                             "call_sid": {"type": "string"}
#                         },
#                         "required": ["index"],
#                     },
#                 },

#                 {
#                     "name": "get_cart",
#                     "description": "Get current cart contents to read back to customer.",
#                     "parameters": {"type": "object", "properties": {"call_sid": {"type": "string"}},
#                     "required": []},
#                 },

#                 {
#                     "name": "order_is_placed",
#                     "description": "Return whether an order number has been generated in this call session.",
#                     "parameters": 
#                     {"type": "object", 
#                      "properties": {}, 
#                      "required": []},
#                 },

#                 {
#                     "name": "get_cart_totals_for_call",
#                     "description": "Return the detailed cart pricing for the current call session. Use this to obtain per-item unit_price, qty, addons, unit_total, line_total, subtotal, and total for the CART associated with call_sid.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "call_sid": {
#                                 "type": "string",
#                                 "description": "Optional Twilio call SID to bind to a specific session."
#                             }
#                         },
#                         "required": []
#                     }
#                 },
#                 {
#                     "name": "calculate_cart_total",
#                     "description": "Calculate detailed pricing for a given cart payload. Returns per-item breakdown (unit_price, qty, addons with unit_price, unit_total, line_total) and subtotal/total. Use this for pricing ad-hoc carts or verifying pricing of a proposed modification.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "cart": {
#                                 "type": "array",
#                                 "items": {
#                                     "type": "object",
#                                     "properties": {
#                                         "item": {"type": "string"},
#                                         "flavor": {"type": "string"},
#                                         "size": {"type": "string"},
#                                         "quantity": {"type": "integer"},
#                                         "addons": {"type": "array", "items": {"type": "string"}}
#                                     }
#                                 }
#                             }
#                         },
#                         "required": ["cart"]
#                     }
#                 },
                
#                 {
#                     "name": "checkout_order",
#                     "description": "Generate an order number (can be called once per order flow). This may be called after order_type, phone, and address have been saved. If some details are missing, the agent should collect them first or call the appropriate save_* functions.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {
#                             "phone": {"type": "string"},
#                             "address": {
#                                 "type": "string",
#                                 "description":"Full delivery address of customer including street, city, state, and zip code."
#                             },
#                             "order_type": {
#                                 "type": "string",
#                                 "description":"Order type: pickup or delivery."
#                             },
#                             "call_sid": {"type": "string"}
#                         },
#                         "required": [], 
#                     },
#                 },

#                 {
#                     "name": "order_status",
#                     "description": "Look up order status by phone or order number.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"phone": {"type": "string"}, "order_number": {"type": "string"}, "call_sid": {"type": "string"}},
#                         "required": [],
#                     },
#                 },
                
#                 {
#                     "name": "extract_phone_and_order",
#                     "description": "Extract phone and 4-digit order number from free text.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"text": {"type": "string"}, "call_sid": {"type": "string"}},
#                         "required": ["text"],
#                     },
#                 },

#                 {
#                     "name": "save_phone_number",
#                     "description": "Save the customer's phone number for pickup/delivery (not confirmed).",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"phone": {"type": "string"}, "call_sid": {"type": "string"}},
#                         "required": ["phone"],
#                     },
#                 },

#                 {
#                     "name": "confirm_phone_number",
#                     "description": "Confirm (true) or reject (false) the previously provided phone number.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"confirmed": {"type": "boolean"}, "call_sid": {"type": "string"}},
#                         "required": ["confirmed"],
#                     },
#                 },

#                 {
#                     "name": "save_address",
#                     "description": "Save the customer's delivery address (not confirmed). Can be empty or omitted for pickup orders.",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"address": {"type": "string"}, "call_sid": {"type": "string"}},
#                         "required": ["address"],
#                     }
#                 },
#                 {
#                     "name": "save_order_type",
#                     "description": "Save the customer's order type (PICKUP or DELIVERY).",
#                     "parameters": {
#                         "type": "object",
#                         "properties": {"order_type": {"type": "string"}, "call_sid": {"type": "string"}},
#                         "required": ["order_type"],
#                     }
#                 },

#             ],
#         },
#         "speak": {"provider": SPEAK_PROVIDER},
#         "greeting": os.getenv("AGENT_GREETING", "Hi! Welcome to Lapinoz-Pizza, i am clara your AI assitant.How can i help you today ? I can check your order status or help you place a new order."),
#     },
# }


# def get_default_prompt(force_refresh: bool = False) -> str:
#     if force_refresh:
#         global _cached_menu
#         _cached_menu = None
#     return build_prompt_from_menu()

# app/settings.py
import os
import logging
import json
from typing import Any, Dict, Optional, List
import requests
import time
import asyncio

logger = logging.getLogger(__name__)

# --- Menu cache & TTL (single canonical declaration) ---
_cached_menu: Optional[Dict[str, Any]] = None
_cached_menu_ts: Optional[int] = None
_MENU_CACHE_TTL: int = int(os.getenv("MENU_CACHE_TTL_SECONDS", "300"))  # default 5 minutes

# --- Basic env-configurable values ---
DG_API_KEY = os.getenv("DG_API_KEY")
MENU_API_URL = os.getenv("MENU_API_URL")

# Providers (defaults, can be overridden via env)
AGENT_LANGUAGE = os.getenv("AGENT_LANGUAGE", "en-US")
LISTEN_PROVIDER = {"type": "deepgram", "model": os.getenv("AGENT_STT_MODEL", "flux-general-en")}
THINK_PROVIDER  = {"type": "google",   "model": os.getenv("AGENT_THINK_MODEL", "gemini-2.0-flash")}
SPEAK_PROVIDER = {
    "type": "eleven_labs",
    "model_id": os.getenv("AGENT_TTS_MODEL", "eleven_multilingual_v2"),
    "voice_id": os.getenv("AGENT_TTS_VOICE", "cgSgspJ2msm6clMCkdW9"),
}

# ------------------------------
# Remote fetch + normalization
# ------------------------------
def fetch_remote_menu(url: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    """
    Fetch a remote menu JSON. Try common JSONBin shapes and allow X-Master-Key.
    Returns parsed JSON on success, otherwise None.
    """
    if not url:
        return None

    headers = {"Accept": "application/json"}
    api_key = os.getenv("JSONBIN_API_KEY") or os.getenv("JSONBIN_MASTER_KEY")
    if api_key:
        headers["X-Master-Key"] = api_key

    base = url.rstrip("/")
    candidates = [
        url,
        f"{base}/latest",
        f"{base}/raw",
        f"{base}/raw/latest",
        f"{base}?meta=false",
    ]

    seen = set()
    tried = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            tried.append(c)

    last_exc = None
    for u in tried:
        try:
            resp = requests.get(u, timeout=timeout, headers=headers)
        except requests.RequestException as e:
            logger.warning("Failed to fetch MENU_API_URL %s: %s", u, e)
            last_exc = e
            continue

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError as e:
                logger.warning("MENU_API_URL %s returned non-JSON response: %s", u, e)
                return None
        else:
            logger.debug("MENU_API_URL %s returned status %s", u, resp.status_code)
            last_exc = RuntimeError(f"status {resp.status_code} for {u}")

    logger.warning("Failed to fetch MENU_API_URL. Tried URLs: %s. Last error: %s", tried, last_exc)
    return None


def _normalize_remote_menu(raw: Any) -> Dict[str, Any]:
    """
    Turn the remote menu into a canonical menu dict:
      - flavors: list[str]
      - toppings: list[str] (unique)
      - addons: list[str]
      - sizes: list[str] (human-friendly)
      - prices: dict(displayName -> {sizeKey -> float|None}) with lowercased aliases
    """
    if not raw:
        return {"flavors": [], "toppings": [], "addons": [], "sizes": [], "prices": {}}

    # unwrap common wrappers
    if isinstance(raw, dict) and "record" in raw and isinstance(raw["record"], dict):
        raw = raw["record"]
    if isinstance(raw, dict) and "menu" in raw:
        raw = raw["menu"]

    flavors: List[str] = []
    toppings_set = set()
    addons: List[str] = []
    sizes_set = set()
    prices: Dict[str, Dict[str, Optional[float]]] = {}

    def _process_item(item: dict, treat_as_addon: bool = False):
        if not isinstance(item, dict):
            return
        name = item.get("name") or item.get("title")
        if not name:
            return
        name = str(name).strip()
        if treat_as_addon:
            addons.append(name)
        else:
            flavors.append(name)

        # toppings or ingredients
        t = item.get("toppings") or item.get("ingredients") or []
        if isinstance(t, list):
            for top in t:
                if top:
                    toppings_set.add(str(top).strip())
        elif isinstance(t, str):
            toppings_set.add(t.strip())

        # sizes/prices
        s = item.get("sizes")
        if isinstance(s, dict):
            prices.setdefault(name, {})
            for size_key, size_val in s.items():
                if size_key is None:
                    continue
                key = str(size_key).strip()
                sizes_set.add(key)
                price_val = None
                if isinstance(size_val, dict):
                    price_val = size_val.get("price") or size_val.get("cost")
                elif isinstance(size_val, (int, float)):
                    price_val = size_val
                try:
                    prices[name][key] = float(price_val) if price_val is not None else None
                except Exception:
                    prices[name][key] = None
        else:
            # simple price field -> default size
            price = item.get("price")
            if price is not None:
                sizes_set.add("default")
                try:
                    prices.setdefault(name, {})["default"] = float(price)
                except Exception:
                    prices.setdefault(name, {})["default"] = None

    # Candidate section keys
    if isinstance(raw, dict):
        main_sections = ["Pizza", "Pizzas", "pizza", "pizzas", "flavors", "items", "menu_items"]
        addon_sections = ["Sides", "Drinks", "addons", "extras", "sides", "drinks"]

        for sec in main_sections:
            sec_items = raw.get(sec)
            if isinstance(sec_items, list):
                for it in sec_items:
                    _process_item(it, treat_as_addon=False)

        for sec in addon_sections:
            sec_items = raw.get(sec)
            if isinstance(sec_items, list):
                for it in sec_items:
                    _process_item(it, treat_as_addon=True)

        # Heuristic scan if no flavors found
        if not flavors:
            for k, v in raw.items():
                if isinstance(v, list) and v:
                    sample = v[0]
                    if isinstance(sample, dict) and ("sizes" in sample or "toppings" in sample or "description" in sample):
                        for it in v:
                            _process_item(it, treat_as_addon=False)
                    else:
                        for it in v:
                            _process_item(it, treat_as_addon=True)

    elif isinstance(raw, list):
        for it in raw:
            _process_item(it, treat_as_addon=False)

    # sizes normalization:
    if sizes_set:
        sizes = sorted(sizes_set)
        low_sizes = {s.strip().lower() for s in sizes}
        # If remote menu only says 'default' or 'regular', expose human sizes
        if low_sizes <= {"default"} or low_sizes <= {"regular"} or low_sizes <= {"default", "regular"}:
            sizes = ["Small", "Medium", "Large"]
        else:
            # Title-case for nicer UX
            sizes = [str(s).strip().capitalize() for s in sizes]
    else:
        # no sizes -> expose human sizes (your requirement: no local fallback but menu sizes should be human)
        sizes = ["Small", "Medium", "Large"]

    toppings = sorted(toppings_set)

    # Normalize prices mapping: make display-key + lowercased alias available
    normalized_prices: Dict[str, Dict[str, Optional[float]]] = {}
    for display_name, size_map in prices.items():
        disp = display_name.strip()
        normalized_prices[disp] = {}
        for size_key, price_val in (size_map or {}).items():
            normalized_prices[disp][str(size_key).strip()] = (float(price_val) if price_val is not None else None)
        # also provide a lowercase alias
        normalized_prices[disp.lower()] = normalized_prices[disp].copy()

    return {
        "flavors": flavors,
        "toppings": toppings,
        "addons": addons,
        "sizes": sizes,
        "prices": normalized_prices,
    }


def _empty_menu() -> Dict[str, Any]:
    """Canonical empty menu when remote fetch fails (no local fallback)."""
    return {"flavors": [], "toppings": [], "addons": [], "sizes": [], "prices": {}}


# ------------------------------
# Synchronous + Async get_menu with TTL
# ------------------------------
def get_menu(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Synchronous menu fetch using blocking requests.
    Uses module-level cache with TTL. Only uses remote MENU_API_URL.
    If the remote fetch fails, returns an empty canonical menu (no local fallback).
    """
    global _cached_menu, _cached_menu_ts

    now = int(time.time())
    if _cached_menu is not None and not force_refresh and _cached_menu_ts and (now - _cached_menu_ts) < _MENU_CACHE_TTL:
        return _cached_menu

    if not MENU_API_URL:
        logger.error("MENU_API_URL not set; returning empty menu (no local fallback).")
        _cached_menu = _empty_menu()
        _cached_menu_ts = now
        return _cached_menu

    remote = fetch_remote_menu(MENU_API_URL)
    if isinstance(remote, dict) and remote:
        try:
            _cached_menu = _normalize_remote_menu(remote)
        except Exception:
            logger.exception("Failed to normalize remote menu; returning empty menu.")
            _cached_menu = _empty_menu()
        _cached_menu_ts = now
        return _cached_menu

    logger.error("Failed to fetch or parse remote menu from %s; returning empty menu.", MENU_API_URL)
    _cached_menu = _empty_menu()
    _cached_menu_ts = now
    return _cached_menu


async def async_fetch_remote_menu(url: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    """
    Run blocking fetch_remote_menu in a thread so async callers don't block the event loop.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fetch_remote_menu(url, timeout=timeout))


async def async_get_menu(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Async version of get_menu(). Mirrors synchronous behavior and cache TTL.
    """
    global _cached_menu, _cached_menu_ts

    now = int(time.time())
    if _cached_menu is not None and not force_refresh and _cached_menu_ts and (now - _cached_menu_ts) < _MENU_CACHE_TTL:
        return _cached_menu

    if not MENU_API_URL:
        logger.error("MENU_API_URL not set; returning empty menu (no local fallback).")
        _cached_menu = _empty_menu()
        _cached_menu_ts = now
        return _cached_menu

    remote = await async_fetch_remote_menu(MENU_API_URL)
    if isinstance(remote, dict) and remote:
        try:
            _cached_menu = _normalize_remote_menu(remote)
        except Exception:
            logger.exception("Failed to normalize remote menu; returning empty menu.")
            _cached_menu = _empty_menu()
        _cached_menu_ts = now
        return _cached_menu

    logger.error("Failed to fetch remote menu (async) from %s; returning empty menu.", MENU_API_URL)
    _cached_menu = _empty_menu()
    _cached_menu_ts = now
    return _cached_menu


# --- Prompt builder that tolerates missing keys ---
def build_prompt_from_menu(menu: Optional[Dict[str, Any]] = None) -> str:
    m = menu or get_menu()
    flavors = m.get("flavors") or m.get("pizzas") or m.get("items") or []
    toppings = m.get("toppings") or []
    addons = m.get("addons") or m.get("extras") or []
    sizes = m.get("sizes") or []

    def to_list_of_strings(x):
        if not x:
            return []
        if isinstance(x, dict):
            return list(x.keys())
        if isinstance(x, list):
            return [str(i) for i in x]
        return [str(x)]

    flavors = to_list_of_strings(flavors)
    toppings = to_list_of_strings(toppings)
    addons = to_list_of_strings(addons)
    sizes = to_list_of_strings(sizes)

    snippet = {
        "flavors": flavors,
        "toppings": toppings,
        "addons": addons,
        "sizes": sizes,
    }
    try:
        menu_snippet = json.dumps(snippet, indent=2, ensure_ascii=False)
    except Exception:
        menu_snippet = (
            "Flavors: " + ", ".join(flavors) + ". "
            "Toppings: " + ", ".join(toppings) + ". "
            "Add-ons: " + ", ".join(addons) + ". "
            "Sizes: " + ", ".join(sizes) + "."
        )

    prompt = (
        "You are an AI pizza ordering assistant.\n\n"
        "Use the following menu when making suggestions and validating user choices:\n"
        f"{menu_snippet}\n\n"
        "Ask clarifying questions when necessary (size, quantity, toppings, address). "
        "Always confirm phone numbers before checkout. Do not finalize orders without explicit confirmation."
    )
    return prompt


# --- Re-introduce build_deepgram_settings so other modules can import it ---
def build_deepgram_settings(prompt: Optional[str] = None) -> Dict[str, Any]:
    """
    Build the Deepgram 'Settings' payload expected by agent_client / agent setup.
    If prompt is not provided, it will be generated from the current menu.
    """
    effective_prompt = prompt or build_prompt_from_menu()
    return {
        "type": "Settings",
        "audio": {
            "input": {"encoding": "linear16", "sample_rate": 48000},
            "output": {"encoding": "linear16", "sample_rate": 24000, "container": "none"},
        },
        "agent": {
            "language": AGENT_LANGUAGE,
            "listen": {"provider": LISTEN_PROVIDER},
            "think": {
                "provider": THINK_PROVIDER,
                "prompt": (
                    "You are an AI-powered Pizza Ordering Assistant for phone-call customers.\n\n"
                    "High-level: Greet the caller, determine whether they want to place a new order or check an order status, "
                    "and then guide them step-by-step to complete or check the order. Use the provided tool functions (menu_summary, "
                    "add_to_cart, modify_cart_item, remove_from_cart, get_cart, save_order_type, save_phone_number, confirm_phone_number, "
                    "save_address, checkout_order, order_status, extract_phone_and_order, get_cart_totals_for_call, calculate_cart_total, apply_pricing_adjustments) "
                    "to perform actions — do not invent state or finalize an order without calling the appropriate tools.\n\n"

                    "Staged ordering flow (follow exactly):\n"
                    "1) Greeting: Say hello and ask whether they want to place an order or check an existing order. If checking, ask for phone or order number and call order_status.\n"
                    "2) Menu: If ordering, call menu_summary when helpful and offer menu suggestions (flavors, sizes, toppings, add-ons).\n"
                    "3) Build cart: Add pizzas using add_to_cart. If the caller wants adjustments, use modify_cart_item or remove_from_cart. Use set_size_quantity or quantity fields where required.\n"
                    "4) Confirm cart: Call get_cart and read the cart back clearly (flavor, size, toppings, add-ons, quantity). Ask the caller to confirm the cart contents before proceeding.\n"
                    "5) Pricing check (required before checkout): Always call get_cart_totals_for_call(call_sid=<current session>) to compute the detailed pricing breakdown (unit_price, qty, addons, unit_total, line_total, subtotal). If you need to price an ad-hoc cart payload instead, call calculate_cart_total. If your business needs tax/delivery/discount computations, call apply_pricing_adjustments with the subtotal to compute tax, delivery_fee, discount and final total. Attach the detailed pricing block to the pending order before calling checkout_order.\n"
                    "6) Order type (required): Ask whether the order is PICKUP or DELIVERY. Call save_order_type to persist the choice. Do not proceed to collect address for PICKUP orders.\n"
                    "7) Contact details:\n"
                    "   - For PICKUP: request phone number, call save_phone_number, then call confirm_phone_number to confirm.\n"
                    "   - For DELIVERY: request phone and full delivery address, call save_phone_number and save_address, and confirm the phone with confirm_phone_number.\n"
                    "8) Final validation: Before checkout, re-read cart, pricing (subtotal and per-item line totals), order type, phone, and address (if delivery). Ask: 'Is everything correct?' Only proceed when customer explicitly says 'yes' or 'confirm'.\n"
                    "9) Checkout: Call checkout_order to generate an order number (do not auto-finalize outside this call). Only after checkout_order returns an order number tell the caller the order number and expected next steps. Do NOT claim payment or completion—just give the order number and next steps.\n\n"

                    "Tool usage rules and behavior:\n"
                    "- Always use the provided tool that matches the intent (e.g., save_order_type for order type, save_address for delivery address). Use get_cart_totals_for_call to obtain pricing before checkout.\n"
                    "- If the caller gives free-form text containing numbers, use extract_phone_and_order to parse potential phone or 4-digit order numbers.\n"
                    "- If a requested flavor, topping, or add-on is not on the menu, politely tell the caller and offer alternatives from menu_summary.\n"
                    "- Enforce limits: do not add more than the maximum allowed pizzas; inform the caller clearly if limits are reached.\n"
                    "- When saving phone numbers, normalize but ask the user to confirm the final format before checkout.\n"
                    "- Never finalize or claim the order is placed unless checkout_order returned an order number and the caller explicitly confirmed.\n\n"

                    "Tone and responsibilities:\n"
                    "- Be friendly, calm, and professional. Speak clearly and avoid jargon.\n"
                    "- Guide the caller step-by-step, ask concise clarifying questions only when needed.\n"
                    "- Repeat back important details (cart contents, pricing line items, phone, address, order type) and request explicit confirmation.\n"
                    "- If the caller asks about an existing order, gather phone or order number and use order_status to answer.\n\n"

                    "Your goal is to ensure the order is accurate, complete, and explicitly confirmed before checkout."
                ),
                # Functions schema will be supplied by agent_functions module at runtime (the agent client consumes it).
            },
            "speak": {"provider": SPEAK_PROVIDER},
            "greeting": os.getenv("AGENT_GREETING", "Hi! Welcome to Lapinoz-Pizza, i am clara your AI assitant.How can i help you today ? I can check your order status or help you place a new order."),
        },
    }


def get_default_prompt(force_refresh: bool = False) -> str:
    if force_refresh:
        global _cached_menu, _cached_menu_ts
        _cached_menu = None
        _cached_menu_ts = None
    return build_prompt_from_menu()
