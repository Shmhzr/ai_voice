# Twilio Setup Guide

Complete guide for configuring Twilio phone numbers, webhooks, and SMS for Deepgram BobaRista.

## Step 1: Get Account Credentials

### 1.1 Find Your Account SID and Auth Token

2. You'll see the dashboard with:

Account Info
├── Account SID: ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
└── Auth Token: ********************************

3. **Click the eye icon** to reveal Auth Token
4. **Copy both values** - you'll need them for `.env` file

**Save these securely:**
```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
```

## Step 2: Upgrade Account

⚠️ **Important**: Trial accounts have limitations. For production use, you must upgrade.

### 2.1 Add Billing Information

1. Click **Billing** in left sidebar
2. Click **Add payment method**
3. Enter credit card information
4. Click **Save**

### 2.2 Upgrade to Paid Account

1. Go to **Console** → **Account**
2. Click **Upgrade** button
3. Confirm upgrade

**Benefits of paid account:**
- No trial limitations on SMS
- Call any phone number (not just verified)
- Remove "Twilio trial" message
- Access to all features

## Step 3: Purchase Phone Number (Voice)

### 3.1 Navigate to Phone Numbers

1. In Twilio Console, click **Phone Numbers** (left sidebar)
2. Click **Manage** → **Buy a number**

### 3.2 Search for Number

**Search Criteria:**
Country: United States
Capabilities: 
  ☑ Voice
  ☐ SMS (optional for now)
  ☐ MMS (optional)

Number type: Local or Toll-free

**For production (recommended):**
- Select **Toll-free** number
- Customers can call for free
- More professional appearance
- Example: `+1 ((xxx) xxx-xxxx`

**For testing/development:**
- Select **Local** number
- Cheaper ($1/month vs $2/month for toll-free)
- Example: `+1 (xxx) xxx-xxxx`

### 3.3 Purchase Number

1. Click **Search**
2. Browse available numbers
3. Click **Buy** next to your chosen number
4. Confirm purchase

**Your Voice Number**: `+1 (xxx) xxx-xxxx`

💰 **Cost**: 
- Local: ~$1/month + $0.0085/minute
- Toll-free: ~$2/month + $0.022/minute

## Step 4: Configure Voice Webhook

### 4.1 Navigate to Number Settings

2. Click on your purchased number (e.g., `+1 (xxx) xxx-xxxx`)

### 4.2 Configure Voice Settings

Scroll down to **Voice Configuration** section:

A CALL COMES IN
├── Webhook: https://voice.boba-demo.deepgram.com/voice
├── HTTP: POST
└── Primary handler fails: (leave empty)

CALL STATUS CHANGES (optional)
└── (can leave empty)

**Important:**
- Use **HTTPS** (not HTTP)
- Use **POST** method
- URL must be publicly accessible
- Must end with `/voice`

### 4.3 Save Configuration

Click **Save configuration** at bottom of page.

## Step 5: Purchase Phone Number (SMS)

You can use the same number for both voice and SMS, or get a separate number.

### Option A: Use Same Number

1. Go to your voice number settings
2. Check the **SMS** capability box
3. Upgrade if needed
4. Save

### Option B: Get Separate Number (Recommended)

Having separate numbers is clearer for customers:
- Voice number: for ordering
- SMS number: for notifications

**Purchase SMS Number:**

1. Go to **Phone Numbers** → **Manage** → **Buy a number**
2. **Search Criteria:**
   Capabilities: ☑ SMS, ☑ MMS
   Number type: Local
3. **Buy number**

**Your SMS Number**: `+1 (xxx) xxx-xxxx`

## Step 6: Configure Environment Variables

Update your `.env` file with Twilio credentials:

# Twilio Messaging (for sending SMS)
xxx=xxx-xxx-xxxx

# Server configuration

**Restart your application** after updating `.env`.

## Troubleshooting

### Issue: Webhook Not Working

**Symptoms:**
- Call connects but no audio
- Call drops immediately
- "We're sorry, an application error has occurred"

**Solutions:**

1. **Check webhook URL:**
   # Must be accessible
   curl -X POST https://your-domain.com/voice

   # Should return valid TwiML

2. **Check webhook logs** in Twilio Console:
   - Monitor → Logs → Calls
   - Click on call
   - Check "Request Inspector"

3. **Common mistakes:**
   - Using HTTP instead of HTTPS
   - Wrong URL path (/voice)
   - Server not publicly accessible
   - Firewall blocking Twilio IPs

4. **Test locally with ngrok:**
   # Use ngrok URL in Twilio webhook

### Issue: No Audio on Call

**Check these:**

1. **WebSocket URL correct:**
   wss://your-domain.com/twilio (not ws://)

2. **Server logs:**
   sudo journalctl -u bobarista -f
   # Look for WebSocket connection errors

3. **Deepgram API key valid:**
   # Check .env file
   cat /opt/bobarista/.env | grep DEEPGRAM

### Issue: SMS Not Sending

1. **Twilio credentials correct:**
   # Verify in .env
   cat .env | grep MSG_TWILIO

2. **Phone number has SMS capability:**
   - Twilio Console → Phone Numbers
   - Check "SMS" is enabled

3. **Check SMS logs:**
   - Monitor → Logs → Messages
   - Look for error messages

4. **Common errors:**
   - `21408`: Phone number has no SMS capability
   - `21211`: Invalid 'To' phone number
   - `21614`: Invalid 'From' phone number

### Issue: Call Quality Problems

1. **Check Deepgram model:**

2. **Check server resources:**
   htop  # Check CPU/memory usage

3. **Check network latency:**
   ping deepgram.com

Now that Twilio is configured:

- 🚀 [Deploy Application](04-deployment.md)
- 🏗️ [Understand Architecture](05-architecture.md)
- 🧪 [Test Your System](../README.md#quick-test)

