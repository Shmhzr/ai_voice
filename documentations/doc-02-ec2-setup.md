# AWS EC2 Setup Guide

This guide covers setting up an AWS EC2 instance for hosting Deepgram BobaRista in production.

- AWS account (sign up at https://aws.amazon.com)
- Credit card for AWS (free tier available)
- SSH client (Terminal on macOS/Linux, PuTTY on Windows)

## Step 1: Create AWS Account

1. Go to https://aws.amazon.com
2. Click **Create an AWS Account**
3. Follow the registration process
4. Verify your email and phone number
5. Add payment method (required even for free tier)

## Step 2: Launch EC2 Instance

### 2.1 Navigate to EC2

1. Login to [AWS Console](https://console.aws.amazon.com)
2. Search for **EC2** in the search bar
3. Click **EC2** to open the EC2 Dashboard
4. Click **Launch Instance**

### 2.2 Configure Instance

**Name and Tags:**
Name: deepgram-bobarista

**Application and OS Images (AMI):**
OS: Ubuntu
Version: Ubuntu Server 22.04 LTS (HVM), SSD Volume Type
Architecture: 64-bit (x86)
✅ This is **Free tier eligible**

**Instance Type:**
Type: t2.small (minimum recommended)
      or t2.medium (better performance)

Specs:
  t2.small:  1 vCPU,  2 GB RAM
  t2.medium: 2 vCPUs, 4 GB RAM

**Note**: t2.micro (1GB RAM) may run out of memory.

**Key Pair (Login):**
Option 1: Create new key pair
  - Name: bobarista-key
  - Type: RSA
  - Format: .pem (for macOS/Linux) or .ppk (for Windows/PuTTY)
  - Click "Create key pair"
  - SAVE THE FILE - you can't download it again!

Option 2: Use existing key pair
  - Select from dropdown

**Network Settings:**

Click **Edit** to customize:

VPC: (default VPC is fine)
Subnet: No preference
Auto-assign public IP: Enable

**Firewall (Security Groups):**

- Select **Create security group**
- Security group name: `bobarista-sg`
- Description: `Security group for Deepgram BobaRista`

Add these rules:

| Type | Protocol | Port Range | Source | Description |
|------|----------|------------|--------|-------------|
| SSH | TCP | 22 | My IP | SSH access |
| HTTP | TCP | 80 | 0.0.0.0/0 | HTTP (redirect to HTTPS) |
| HTTPS | TCP | 443 | 0.0.0.0/0 | HTTPS traffic |
| Custom TCP | TCP | 8000 | 0.0.0.0/0 | FastAPI (temporary) |

**Storage:**
Size: 20 GB
Volume Type: gp3 (General Purpose SSD)

**Advanced Details:**
Leave defaults (can skip this section)

### 2.3 Review and Launch

1. Review all settings
2. Click **Launch Instance**
3. Wait 1-2 minutes for instance to start
4. Click **View Instances** to see your new instance

## Step 3: Allocate Elastic IP

An Elastic IP gives you a permanent public IP address that won't change if you restart your instance.

1. In EC2 Dashboard, click **Elastic IPs** (left sidebar under "Network & Security")
2. Click **Allocate Elastic IP address**
3. **Settings:**
   - Network Border Group: (leave default)
   - Public IPv4 address pool: Amazon's pool
4. Click **Allocate**
5. **Associate the Elastic IP:**
   - Select the new Elastic IP
   - Click **Actions** → **Associate Elastic IP address**
   - **Instance**: Select `deepgram-bobarista`
   - Click **Associate**

**Your Elastic IP** (example): `xx.xxx.xx.xx`

**Important**: Elastic IPs are free ONLY when associated with a running instance. If you stop your instance, you'll be charged $0.005/hour for the IP.

## Step 4: Configure Security Group

If you need to modify security group later:

1. Go to **EC2** → **Security Groups**
2. Select `bobarista-sg`
3. Click **Inbound rules** tab
4. Click **Edit inbound rules**
5. Add/modify rules as needed
6. Click **Save rules**

**Recommended security enhancement:**

After initial setup, change SSH rule:
Type: SSH
Port: 22
Source: My IP (instead of 0.0.0.0/0)

This restricts SSH access to only your IP address.

## Step 5: Connect to Your Instance

### 5.1 Set Key Permissions (macOS/Linux)

# Navigate to where you saved your key
# Set correct permissions (required by SSH)
chmod 400 bobarista-key.pem

### 5.2 Get Connection Info

1. In EC2 Dashboard, select your instance
2. Click **Connect** button at top
3. Note the connection command

### 5.3 Connect via SSH

# Replace with your Elastic IP and key file path
ssh -i bobarista-key.pem ubuntu@xx.xxx.xx.xx

First time connection:
The authenticity of host 'xx.xxx.xx.xx' can't be established.
Are you sure you want to continue connecting (yes/no)? yes

You should see:
Welcome to Ubuntu 22.04.3 LTS
ubuntu@ip-xxx-xx-xx-xx:~$

## Step 6: Update System

# Update package list
sudo apt update

# Upgrade installed packages
sudo apt upgrade -y

# This may take 5-10 minutes

## Step 7: Install Dependencies

### 7.1 Install Python 3.11

# Add Python PPA
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa

# Install Python 3.11 and dev tools
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# Verify installation
python3.11 --version
# Output: Python 3.11.x

### 7.2 Install System Tools

# Install required system packages
sudo apt install -y \
  git \
  nginx \
  certbot \
  python3-certbot-nginx \
  build-essential \
  curl \
  htop

# Verify installations
git --version
nginx -v
certbot --version

## Step 8: Configure Firewall (UFW)

Ubuntu includes UFW (Uncomplicated Firewall):

# Allow SSH (before enabling firewall!)
sudo ufw allow 22/tcp

# Allow HTTP and HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Allow app port (temporary)
sudo ufw allow 8000/tcp

# Enable firewall
sudo ufw enable

sudo ufw status

Output should show:
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
443/tcp                    ALLOW       Anywhere
8000/tcp                   ALLOW       Anywhere

## Step 9: Set Up Application Directory

# Create app directory
sudo mkdir -p /opt/bobarista
sudo chown ubuntu:ubuntu /opt/bobarista

# Verify ownership
ls -la /opt/ | grep bobarista
# Should show: drwxr-xr-x 2 ubuntu ubuntu

## Step 10: System Monitoring Setup

### Install Monitoring Tools

# Install monitoring tools
sudo apt install -y htop iotop nethogs

# Check system resources
# Press 'q' to quit

### Set Up Automatic Security Updates

# Install unattended-upgrades
sudo apt install -y unattended-upgrades

# Enable automatic security updates
sudo dpkg-reconfigure -plow unattended-upgrades
# Select: Yes

## Step 11: Configure Timezone

# Set timezone
sudo timedatectl set-timezone America/New_York

# Verify
timedatectl

## Step 12: Create Swap File (Optional but Recommended)

Adds virtual memory to prevent out-of-memory issues:

# Create 2GB swap file
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

sudo swapon --show
free -h

## Instance Management

### Start/Stop Instance

# From AWS Console:
1. Select instance
2. Click "Instance state" dropdown
3. Choose "Stop" or "Start"

**Warning**: If you stop the instance, you may need to reassociate the Elastic IP.

### Reboot Instance

# From SSH:
sudo reboot

Instance state → Reboot instance

### Check Instance Logs

Actions → Monitor and troubleshoot → Get system log

## Useful EC2 Commands

# Check system info
uname -a
lsb_release -a

# Check disk usage
df -h

# Check memory usage

# Check CPU info
lscpu

# Check running processes
ps aux

# Check network connections
netstat -tulpn

# Check system logs
sudo journalctl -xe

## Cost Optimization Tips

### Use EC2 Instance Scheduler

Stop instance during off-hours:
# Add to crontab
crontab -e

# Stop at midnight (00:00)
0 0 * * * sudo shutdown -h now

# Or use AWS Instance Scheduler service

### Monitor Costs

1. AWS Console → **Billing Dashboard**
2. Set up **Billing Alerts**:
   - CloudWatch → Alarms → Create alarm
   - Metric: EstimatedCharges
   - Threshold: e.g., $10

### Free Tier Limits

- **EC2**: 750 hours/month of t2.micro (1st year)
- **Data Transfer**: 100 GB/month out to internet
- **Elastic IP**: Free when associated with running instance

## Security Best Practices

### 1. Use SSH Keys Only

# Disable password: xxx
sudo nano /etc/ssh/sshd_config

# Set these values:
xxx no
PermitRootLogin no

# Restart SSH
sudo systemctl restart sshd

### 2. Keep System Updated

# Weekly update routine
sudo apt update && sudo apt upgrade -y

### 3. Monitor Login Attempts

# Check failed login attempts
sudo grep "Failed password" /var/log/auth.log

# Install fail2ban (blocks repeated failed logins)
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

### 4. Regular Backups

Consider setting up:
- **EBS Snapshots** (AWS Console → EC2 → Snapshots)
- **AMI Backups** (create image of entire instance)

Now that your EC2 instance is configured, proceed to:

- [Twilio Setup Guide](03-twilio-setup.md) - Configure phone numbers
- [Deployment Guide](04-deployment.md) - Deploy the application

**SSH Connection:**
ssh -i ~/path/to/key.pem ubuntu@xx.xxx.xx.xx

**Instance Details:**
- AMI: Ubuntu Server 22.04 LTS
- Type: t2.small or t2.medium
- Storage: 20 GB gp3
- Security Group: bobarista-sg (ports 22, 80, 443, 8000)
- Elastic IP: Associated

**Next**: Configure Twilio or deploy the application!
