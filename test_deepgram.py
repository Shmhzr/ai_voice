#!/usr/bin/env python3
"""
Test script to verify Deepgram Agent API connection
"""
import asyncio
import json
import os
import sys
import websockets
from dotenv import load_dotenv

load_dotenv()

DG_API_KEY = os.getenv("DEEPGRAM_API_KEY")

if not DG_API_KEY:
    print("❌ DEEPGRAM_API_KEY not found in .env")
    sys.exit(1)

print(f"✅ Found API Key: {DG_API_KEY[:20]}...")

async def test_connection():
    """Test WebSocket connection to Deepgram Agent"""
    url = "wss://agent.deepgram.com/v1/agent/converse"
    headers = [("Authorization", f"Token {DG_API_KEY}")]
    
    try:
        print(f"🔗 Connecting to {url}...")
        ws = await websockets.connect(url, extra_headers=headers, max_size=2**24)
        print("✅ WebSocket connected!")
        
        # Send minimal settings
        settings = {
            "type": "Settings",
            "audio": {
                "input": {"encoding": "linear16", "sample_rate": 48000},
                "output": {"encoding": "linear16", "sample_rate": 24000, "container": "none"},
            },
            "agent": {
                "language": "en",
                "listen": {"provider": {"type": "deepgram", "model": "flux-general-en"}},
                "think": {
                    "provider": {"type": "google", "model": "gemini-2.0-flash"},
                    "prompt": "You are a helpful assistant. Respond briefly.",
                },
                "speak": {"provider": {"type": "deepgram", "model": "aura-2-odysseus-en"}},
                "greeting": "Hello, I'm here to help!",
            },
        }
        
        print(f"📤 Sending settings...")
        await ws.send(json.dumps(settings))
        print("✅ Settings sent!")
        
        # Wait for welcome message
        print(f"📥 Waiting for response (5 seconds)...")
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(response)
            print(f"✅ Received: {json.dumps(msg, indent=2)}")
            
            if msg.get("type") == "Welcome":
                print("✅ Agent is ready!")
                return True
            elif msg.get("type") == "Error":
                print(f"❌ Agent error: {msg.get('error')}")
                return False
        except asyncio.TimeoutError:
            print("❌ No response from agent (timeout)")
            return False
        finally:
            await ws.close()
            
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_connection())
    sys.exit(0 if success else 1)
