# app/firebase_client.py
import asyncio
import json
import logging
from typing import Any, Optional, Dict

from firebase_admin import credentials, initialize_app, db, _apps
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

logger = logging.getLogger(__name__)

class FirebaseClientError(Exception):
    pass

class FirebaseClient:
    """
    Singleton-like client for Firebase Realtime Database (Admin SDK).
    Use the module-level `firebase_client` instance (created at bottom).
    """
    def __init__(self):
        self._initialized = False
        self._app = None

    def init_app(self, service_account_path: Optional[str] = None,
                 service_account_json: Optional[str] = None,
                 database_url: Optional[str] = None) -> None:
        """
        Initialize the firebase admin SDK. Can pass either a path to a
        service account JSON file or the raw JSON string.
        This method is synchronous and should be called at app startup.
        """
        if self._initialized:
            logger.debug("Firebase already initialized.")
            return

        if service_account_json:
            info = json.loads(service_account_json)
            cred = credentials.Certificate(info)
        elif service_account_path:
            cred = credentials.Certificate(service_account_path)
        else:
            raise FirebaseClientError("Provide service_account_path or service_account_json")

        try:
            self._app = initialize_app(cred, {"databaseURL": database_url})
            self._initialized = True
            logger.info("Firebase Admin SDK initialized.")
        except Exception as e:
            logger.exception("Failed to initialize Firebase Admin SDK")
            raise FirebaseClientError(str(e)) from e

    def _ensure_initialized(self):
        if not self._initialized or self._app is None:
            raise FirebaseClientError("Firebase client not initialized. Call init_app() first.")

    # ---- Helpers to run blocking db calls in threadpool ----
    async def _run_blocking(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    # ---- Database operations (async wrappers) ----
    @retry(wait=wait_exponential(multiplier=0.5, max=10), stop=stop_after_attempt(4),
           retry=retry_if_exception_type(Exception))
    async def push(self, ref_path: str, data: Any) -> str:
        """Push an item (auto-id). Returns the generated key."""
        self._ensure_initialized()
        def _push():
            ref = db.reference(ref_path, app=self._app)
            new_ref = ref.push(data)
            return new_ref.key
        key = await self._run_blocking(_push)
        logger.debug("Pushed to %s -> key=%s", ref_path, key)
        return key

    @retry(wait=wait_exponential(multiplier=0.5, max=10), stop=stop_after_attempt(4),
           retry=retry_if_exception_type(Exception))
    async def set(self, ref_path: str, data: Any) -> None:
        """Set (overwrite) data at the reference path."""
        self._ensure_initialized()
        def _set():
            ref = db.reference(ref_path, app=self._app)
            ref.set(data)
        await self._run_blocking(_set)
        logger.debug("Set data at %s", ref_path)

    @retry(wait=wait_exponential(multiplier=0.5, max=10), stop=stop_after_attempt(4),
           retry=retry_if_exception_type(Exception))
    async def get(self, ref_path: str) -> Any:
        """Get data from path. Returns Python object or None."""
        self._ensure_initialized()
        def _get():
            ref = db.reference(ref_path, app=self._app)
            return ref.get()
        result = await self._run_blocking(_get)
        logger.debug("Got data from %s: %s", ref_path, type(result))
        return result

    @retry(wait=wait_exponential(multiplier=0.5, max=10), stop=stop_after_attempt(4),
           retry=retry_if_exception_type(Exception))
    async def update(self, ref_path: str, data: Dict[str, Any]) -> None:
        """Shallow update at ref path with a dict."""
        self._ensure_initialized()
        def _update():
            ref = db.reference(ref_path, app=self._app)
            ref.update(data)
        await self._run_blocking(_update)
        logger.debug("Updated %s with keys: %s", ref_path, list(data.keys()))

    @retry(wait=wait_exponential(multiplier=0.5, max=10), stop=stop_after_attempt(4),
           retry=retry_if_exception_type(Exception))
    async def delete(self, ref_path: str) -> None:
        """Delete the node at ref_path."""
        self._ensure_initialized()
        def _delete():
            ref = db.reference(ref_path, app=self._app)
            ref.delete()
        await self._run_blocking(_delete)
        logger.debug("Deleted %s", ref_path)


# Module-level singleton to import from anywhere
firebase_client = FirebaseClient()
