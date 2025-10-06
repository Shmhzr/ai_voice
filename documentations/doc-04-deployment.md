# Production Deployment Guide

Complete guide for deploying Deepgram BobaRista to production on AWS EC2.

Before starting, complete these guides:
- ✅ [EC2 Setup](02-ec2-setup.md) - Server configured and running
- ✅ [Twilio Setup](03-twilio-setup.md) - Phone numbers purchased

You should have:
- EC2 instance with Ubuntu 22.04
- Elastic IP assigned
- Domain name (or ready to use IP directly)
- Twilio phone numbers
- All necessary API keys

## Step 1: Configure Domain (DNS)

### Option A: Using Your Own Domain

1. **Go to your DNS provider** (Cloudflare, Route53, Namecheap, etc.)

2. **Add A Record:**
   Type: A
   Name: voice.boba-demo (or your subdomain)
   Value: xx.xxx.xx.xx (your EC2 Elastic IP)
   TTL: 300 (5 minutes)

3. **Wait for DNS propagation** (5-15 minutes)

4. **Test DNS:**
   nslookup voice.boba-demo.deepgram.com
   # Should return your Elastic IP

   ping voice.boba-demo.deepgram.com
   # Should ping your server

### Option B: Using IP Address (Not Recommended)

You can use the Elastic IP directly, but this has limitations:
- No SSL certificate from Let's Encrypt (requires domain)
- Less professional
- Harder to remember

**If using IP:**
- Skip SSL setup
- Use `http://` instead of `https://`
- Configure Twilio with HTTP (less secure)

## Step 2: Deploy Application Code

### 2.1 Upload Code to Server

**Option A: Using Git (Recommended)**

# SSH into your server
ssh -i your-key.pem ubuntu@your-elastic-ip

# Clone repository
git clone https://github.com/your-username/DG-Boba-Assitant.git .

**Option B: Using SCP**

From your local machine:
# Upload entire directory
scp -i your-key.pem -r ./app ubuntu@your-elastic-ip:/opt/bobarista/
scp -i your-key.pem requirements.txt ubuntu@your-elastic-ip:/opt/bobarista/
scp -i your-key.pem sample.env.txt ubuntu@your-elastic-ip:/opt/bobarista/

**Option C: Using rsync**

rsync -avz -e "ssh -i your-key.pem" \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '.env' \
  ./ ubuntu@your-elastic-ip:/opt/bobarista/

### 2.2 Set Up Python Environment

# Create virtual environment

# Activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies

**Verify installation:**
python -c "import fastapi; print('FastAPI OK')"
python -c "import websockets; print('WebSockets OK')"
python -c "import twilio; print('Twilio OK')"

## Step 3: Configure Environment Variables

### 3.1 Create .env File

nano .env

### 3.2 Fill in Production Values

# Server Configuration

# Deepgram Configuration

# Twilio Messaging (for SMS)
MSG_TWILIO_ACCOUNT_SID=your_msg_twilio_account_sid_here
MSG_TWILIO_AUTH_TOKEN=your_msg_twilio_auth_token_here
MSG_TWILIO_FROM_E164=+1234567890

**Save:** Ctrl+O, Enter, Ctrl+X

### 3.3 Secure the .env File

# Set restrictive permissions
chmod 600 .env

ls -la .env
# Should show: -rw------- ubuntu ubuntu

## Step 4: Set Up Nginx Reverse Proxy

### 4.1 Create Nginx Configuration

sudo nano /etc/nginx/sites-available/bobarista

**Paste this configuration:**

```nginx
upstream bobarista {
    server xxx-xxx-xxxx:8000;
}

map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;

server {
    listen 80;
    server_name voice.boba-demo.deepgram.com;

    # Will be updated by certbot for HTTPS redirect

    location / {
        proxy_pass http://bobarista;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $xxx;
        proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket support
    location /twilio {
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;

    # Server-Sent Events
    location /orders/events {
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        xxx off;

### 4.2 Enable Site

# Create symbolic link
sudo ln -s /etc/nginx/sites-available/bobarista /etc/nginx/sites-enabled/

# Remove default site
sudo rm /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Expected output:
# nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# nginx: configuration file /etc/nginx/nginx.conf test is successful

**Don't start Nginx yet** - we need SSL first.

## Step 5: Set Up SSL Certificate

### 5.1 Install Certificate

# Get certificate from Let's Encrypt
sudo certbot --nginx -d voice.boba-demo.deepgram.com

**Follow the prompts:**

Enter email address: your-email@example.com
Agree to terms: (A)gree
Share email: (Y)es or (N)o

Redirect HTTP to HTTPS?
1: No redirect
2: Redirect (recommended)
Choose: 2

**Certbot will automatically:**
- Obtain SSL certificate
- Update Nginx configuration
- Set up HTTPS redirect
- Configure auto-renewal

### 5.2 Verify SSL

# Test certificate
sudo certbot certificates

# Certificate Name: voice.boba-demo.deepgram.com
#   Domains: voice.boba-demo.deepgram.com
#   Expiry Date: [date]
#   Certificate Path: /etc/letsencrypt/live/.../fullchain.pem

### 5.3 Test Auto-Renewal

# Dry run renewal
sudo certbot renew --dry-run

# Should complete successfully

**Auto-renewal is automatic** - certbot sets up a systemd timer.

## Step 6: Create Systemd Service

### 6.1 Create Service File

sudo nano /etc/systemd/system/bobarista.service

**Paste this content:**

```ini
[Unit]
Description=Deepgram BobaRista Voice Ordering System
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/bobarista
Environment="PATH=/opt/bobarista/venv/bin"
ExecStart=/opt/bobarista/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target

### 6.2 Enable and Start Service

# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)

# Start service

sudo systemctl status bobarista

**Expected output:**
● bobarista.service - Deepgram BobaRista Voice Ordering System
     Loaded: loaded (/etc/systemd/system/bobarista.service; enabled)
     Active: active (running) since...

### 6.3 View Logs

# Follow live logs

# View last 100 lines
sudo journalctl -u bobarista -n 100

# View errors only
sudo journalctl -u bobarista -p err

## Step 7: Start Nginx

# Start Nginx
sudo systemctl start nginx

# Enable on boot
sudo systemctl enable nginx

sudo systemctl status nginx

## Step 8: Verify Deployment

### 8.1 Test HTTP Endpoints

# Test landing page
curl https://voice.boba-demo.deepgram.com

curl -X POST https://voice.boba-demo.deepgram.com/voice

# Test orders JSON
curl https://voice.boba-demo.deepgram.com/orders.json

### 8.2 Test WebSocket

# Install wscat if not already installed
npm install -g wscat

# Test WebSocket connection
wscat -c wss://voice.boba-demo.deepgram.com/twilio

Press Ctrl+C to exit.

### 8.3 Test in Browser

Open these URLs:
- Landing page: https://voice.boba-demo.deepgram.com
- Orders TV: https://voice.boba-demo.deepgram.com/orders
- Barista console: https://voice.boba-demo.deepgram.com/barista

### 8.4 Test Phone Call

1. **Call your Twilio number**: `xxx-xxx-xxxx`
2. **Expected:**
   - Hear greeting
   - Can place order
   - Receive order number
   - Get SMS confirmation

## Step 9: Configure Monitoring

### 9.1 Set Up Log Rotation

sudo nano /etc/logrotate.d/bobarista

**Add:**
/var/log/nginx/bobarista-*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        systemctl reload nginx > /dev/null
    endscript

### 9.2 Monitor Resources

sudo apt install -y htop iotop

# Check system status

# Check memory

### 9.3 Set Up Alerts (Optional)

Consider using:
- **AWS CloudWatch** for server metrics
- **UptimeRobot** for uptime monitoring
- **Sentry** for error tracking

## Step 10: Update Twilio Webhook

### 10.1 Update Voice Webhook

2. Navigate to **Phone Numbers** → **Manage** → **Active Numbers**
3. Click on `+1 (xxx) xxx-xxx-xxxx`
4. Update **Voice Configuration**:
   Webhook: https://voice.boba-demo.deepgram.com/voice
   HTTP: POST

### 10.2 Test End-to-End

Call the number and complete an order to verify everything works.

## Common Deployment Issues

### Issue: "502 Bad Gateway"

**Cause:** Application not running or Nginx can't reach it.

# Check if app is running

# Check if listening on port 8000
sudo netstat -tulpn | grep 8000

# Check application logs
sudo journalctl -u bobarista -n 50

# Restart application
sudo systemctl restart bobarista

### Issue: "Connection refused" on WebSocket

**Cause:** Nginx WebSocket proxy misconfigured.

# Check Nginx configuration

# Check Nginx error log
sudo tail -f /var/log/nginx/error.log

# Verify WebSocket location block exists
sudo cat /etc/nginx/sites-enabled/bobarista | grep -A 10 "/twilio"

# Restart Nginx
sudo systemctl restart nginx

### Issue: SSL Certificate Error

**Cause:** Certificate not properly installed or expired.

# Check certificate status

# Renew certificate manually
sudo certbot renew

# Check Nginx SSL configuration

### Issue: Application Crashes on Start

**Check logs:**
sudo journalctl -u bobarista -n 100 --no-pager

**Common causes:**
- Missing environment variables
- Invalid API keys
- Missing Python dependencies
- Port already in use

## Backup Strategy

### Application Code

# Backup code (if not using git)
tar -czf bobarista-backup-$(date +%Y%m%d).tar.gz /opt/bobarista

### Orders Data

# Backup orders.json
cp /opt/bobarista/app/orders.json ~/backups/orders-$(date +%Y%m%d).json

### Database (if using one)

# Example for PostgreSQL
pg_dump bobarista > bobarista-$(date +%Y%m%d).sql

### EC2 Snapshots

1. Go to AWS Console → EC2 → Elastic Block Store → Snapshots
2. Click **Create snapshot**
3. Select your instance's volume
4. Add description: "Bobarista backup YYYY-MM-DD"
5. Click **Create snapshot**

## Updating the Application

### Method 1: Git Pull (if using Git)

git pull origin main

### Method 2: Manual Upload

# From local machine
scp -i your-key.pem -r ./app ubuntu@your-server:/opt/bobarista/

# On server
