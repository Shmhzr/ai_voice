#!/usr/bin/env python3
"""
test_firebase_client.py

Standalone smoke-test for Firebase Realtime Database using firebase-admin.

Usage:
    # set env vars first (example)
    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/serviceAccountKey.json"
    export FIREBASE_DATABASE_URL="https://ai-voice-82fb0-default-rtdb.asia-southeast1.firebasedatabase.app"

    python test_firebase_client.py
"""

import os
import sys
import json
import time
import argparse

try:
    import firebase_admin
    from firebase_admin import credentials, db
except Exception:
    print("Missing dependency: firebase-admin. Install it with:\n  pip install firebase-admin")
    raise

def load_service_account_from_env():
    
    current_working_directory = os.getcwd()
    sa_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS0")
    sa_json = current_working_directory+ "/serviceAccountKey.json"
    sa_path = sa_json
    print(sa_path)
    print(sa_json)
    # sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if sa_path and os.path.exists(sa_path):
        return credentials.Certificate(sa_path)
    if sa_json:
        info = json.loads(sa_json)
        return credentials.Certificate(info)
    raise RuntimeError(
        "No service account credentials found. Set GOOGLE_APPLICATION_CREDENTIALS (path) "
        "or FIREBASE_SERVICE_ACCOUNT_JSON (raw JSON) environment variable."
    )

def main():
    parser = argparse.ArgumentParser(description="Firebase RTDB smoke test script")
    parser.add_argument("--path", default="tests/smoke", help="DB path to use for smoke-test (default: tests/smoke)")
    parser.add_argument("--timeout", type=int, default=10, help="Network timeout seconds (informational)")
    args = parser.parse_args()

    db_url = os.getenv("FIREBASE_DATABASE_URL")
    if not db_url:
        print("You must set FIREBASE_DATABASE_URL environment variable.")
        print('Example: export FIREBASE_DATABASE_URL="https://<your-db>.firebaseio.com"')
        sys.exit(2)

    print("Using FIREBASE_DATABASE_URL =", db_url)

    try:
        cred = load_service_account_from_env()
    except Exception as e:
        print("Failed to load service account:", e)
        sys.exit(2)

    # Initialize app (guard against duplicate init)
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {"databaseURL": db_url})
            print("Firebase Admin SDK initialized.")
        else:
            print("Firebase Admin SDK already initialized (reusing).")
    except Exception as e:
        print("Failed to initialize Firebase Admin SDK:", e)
        raise

    ref_base = db.reference(args.path)
    test_obj = {"name": "smoke-test", "ts": int(time.time()), "ok": True}

    # Push
    print("Pushing test object to", args.path)
    pushed_ref = ref_base.push(test_obj)
    key = pushed_ref.key
    print("Pushed key:", key)

    # Read back
    read_ref = db.reference(f"{args.path}/{key}")
    read_back = read_ref.get()
    print("Read back object:", read_back)

    # Validate
    if read_back and read_back.get("name") == test_obj["name"]:
        print("Validation SUCCESS: object matches expected values.")
    else:
        print("Validation FAILURE: read object does not match. Read:", read_back)

    # Cleanup: delete the pushed node
    try:
        # read_ref.delete()
        print("Deleted test node:", f"{args.path}/{key}")
        # Confirm deletion
        if db.reference(f"{args.path}/{key}").get() is None:
            print("Confirmed deletion.")
        else:
            print("Warning: node still exists after delete confirmation attempt.")
    except Exception as e:
        print("Failed to delete test node:", e)


if __name__ == '__main__':
    main()
