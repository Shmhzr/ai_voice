#!/usr/bin/env python3
"""
Debug script to test voice call and show full server logs
"""
import subprocess
import sys
import time
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("🔍 DEBUGGING VOICE CALL")
print("=" * 80)
print()

# Check if server is running
print("1️⃣  Checking if server is running on port 8000...")
result = subprocess.run(
    "curl -s http://localhost:8000 > /dev/null && echo 'OK' || echo 'FAIL'",
    shell=True,
    capture_output=True,
    text=True
)

if "FAIL" in result.stdout:
    print("❌ Server not running!")
    print("   Start it with: python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
    sys.exit(1)
else:
    print("✅ Server is running")

print()
print("2️⃣  Making test call (watch the terminal where server is running for logs)...")
print("    This will call your phone number:", end=" ")

import os
phone = os.getenv("TWILIO_TO_E164", "+918777684725")
print(phone)
print()

print("📝 Server logs to watch for:")
print("   - 'Agent: {\"type\": \"Welcome\"...}' = Agent connected ✅")
print("   - 'Agent: {\"type\": \"ConversationText\"...}' = AI speaking ✅")
print("   - Error messages = Problem ❌")
print()

print("⏳ Starting call in 2 seconds...")
print("   (Make sure you have the server terminal visible)")
print()
time.sleep(2)

# Import and run the call
from app.call import *

print("📞 Call initiated!")
print()
print("⏱️  Listening for 45 seconds...")
print("   - Answer the phone when it rings")
print("   - Watch server logs for AI messages")
print()

time.sleep(45)

print()
print("=" * 80)
print("🔍 DEBUGGING COMPLETE")
print("=" * 80)
print()
print("What to check:")
print("1. Did you hear Twilio say 'Connecting you to Deepgram Boba Rista'?")
print("2. Did you hear the AI voice say 'Hey! I am your Deepgram AI Pizza...'?")
print()
print("If NO to #2, check server logs for:")
print("- 'Agent: {\"type\": \"Error\"...}' = API issue")
print("- No agent messages at all = Connection issue")
print()
