# AWS EC2 Deployment Guide - EVA Backend

Complete guide to deploy EVA Backend on AWS EC2 c7i.large instance.

---

## 📋 Table of Contents

1. [AWS Setup](#aws-setup)
2. [EC2 Instance Configuration](#ec2-instance-configuration)
3. [Security Groups](#security-groups)
4. [SSH Access](#ssh-access)
5. [Server Setup](#server-setup)
6. [Code Deployment](#code-deployment)
7. [Database & MQTT](#database--mqtt)
8. [Whisper Setup](#whisper-setup)
9. [Running the Application](#running-the-application)
10. [Monitoring & Maintenance](#monitoring--maintenance)
11. [Troubleshooting](#troubleshooting)

---

## AWS Setup

### Step 1: Create AWS Account & Access Key

1. Go to https://console.aws.amazon.com/
2. Create account if needed
3. Go to **IAM** → **Users** → **Your User** → **Security Credentials**
4. Create **Access Key** for CLI/programmatic access
5. Save:
   - Access Key ID
   - Secret Access Key

### Step 2: Install AWS CLI

**Windows:**
```powershell
# Download installer
Invoke-WebRequest -Uri "https://awscli.amazonaws.com/AWSCLIV2.msi" -OutFile "C:\AWSCLIV2.msi"

# Run installer
msiexec.exe /i C:\AWSCLIV2.msi
```

**Linux:**
```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```

### Step 3: Configure AWS CLI

```bash
aws configure

# Enter when prompted:
# AWS Access Key ID: [your-access-key-id]
# AWS Secret Access Key: [your-secret-access-key]
# Default region name: ap-south-1  # or your preferred region
# Default output format: json
```

---

## EC2 Instance Configuration

### Step 1: Create EC2 Instance

**Using AWS Console:**

1. Go to **EC2** → **Instances** → **Launch Instances**

2. **Name:** `eva-backend-prod`

3. **AMI:** Ubuntu Server 22.04 LTS (free tier eligible)

4. **Instance Type:** `c7i.large`
   - 4 vCPUs
   - 8 GB RAM
   - $0.085/hour (approx)

5. **Key Pair:** 
   - Create new: `eva-backend-key`
   - Download: `eva-backend-key.pem` (save safely)

6. **Network Settings:**
   - VPC: Default
   - Subnet: Any
   - Auto-assign Public IP: **Enable**
   - Create Security Group: `eva-backend-sg`

7. **Storage:**
   - 50 GB gp3 (general purpose)
   - (Free tier: 30GB)

8. **Launch Instance**

### Step 2: Get Instance Details

Once instance is running:

```bash
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=eva-backend-prod" \
  --query 'Reservations[0].Instances[0].[PublicIpAddress,InstanceId]' \
  --output text
```

Save:
- **Public IP:** e.g., `13.201.45.67`
- **Instance ID:** e.g., `i-0a1b2c3d4e5f6g7h8`

---

## Security Groups

### Step 1: Configure Inbound Rules

In **EC2** → **Security Groups** → `eva-backend-sg`:

| Type | Protocol | Port | Source | Purpose |
|------|----------|------|--------|---------|
| SSH | TCP | 22 | 0.0.0.0/0 | Server access |
| HTTP | TCP | 80 | 0.0.0.0/0 | API traffic |
| HTTPS | TCP | 443 | 0.0.0.0/0 | SSL/TLS traffic |
| Custom | TCP | 5000 | 0.0.0.0/0 | Flask dev (if needed) |
| Custom | TCP | 8883 | 0.0.0.0/0 | MQTT (if external) |

**Using AWS CLI:**

```bash
SECURITY_GROUP_ID="sg-0a1b2c3d4e5f6g7h8"  # Your security group ID

# SSH
aws ec2 authorize-security-group-ingress \
  --group-id $SECURITY_GROUP_ID \
  --protocol tcp --port 22 \
  --cidr 0.0.0.0/0

# HTTP
aws ec2 authorize-security-group-ingress \
  --group-id $SECURITY_GROUP_ID \
  --protocol tcp --port 80 \
  --cidr 0.0.0.0/0

# HTTPS
aws ec2 authorize-security-group-ingress \
  --group-id $SECURITY_GROUP_ID \
  --protocol tcp --port 443 \
  --cidr 0.0.0.0/0

# Flask (optional)
aws ec2 authorize-security-group-ingress \
  --group-id $SECURITY_GROUP_ID \
  --protocol tcp --port 5000 \
  --cidr 0.0.0.0/0
```

---

## SSH Access

### Step 1: Fix Key Permissions (Windows PowerShell)

```powershell
# Set key permissions
icacls "C:\path\to\eva-backend-key.pem" /grant:r "%USERNAME%:R"
icacls "C:\path\to\eva-backend-key.pem" /inheritance:r
```

### Step 2: Connect to Instance

**Using PowerShell:**

```powershell
$Instance_IP = "13.201.45.67"  # Your instance public IP
$KeyPath = "C:\path\to\eva-backend-key.pem"

ssh -i $KeyPath ubuntu@$Instance_IP
```

**Using Git Bash / WSL:**

```bash
ssh -i /c/path/to/eva-backend-key.pem ubuntu@13.201.45.67
```

### Step 3: Create Connection Script

**Windows PowerShell:** Save as `connect.ps1`

```powershell
# AWS EC2 Connection Script
$Instance_IP = "13.201.45.67"
$KeyPath = "$PSScriptRoot\eva-backend-key.pem"

ssh -i $KeyPath ubuntu@$Instance_IP
```

**Linux/macOS:** Save as `connect.sh`

```bash
#!/bin/bash
ssh -i eva-backend-key.pem ubuntu@13.201.45.67
```

---

## Server Setup

Once connected via SSH:

### Step 1: Update System

```bash
sudo apt update && sudo apt upgrade -y
```

### Step 2: Install Required Packages

```bash
# Python & Build Tools
sudo apt install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    build-essential \
    libssl-dev \
    libffi-dev

# Database & Tools
sudo apt install -y \
    sqlite3 \
    git \
    curl \
    wget \
    htop \
    nano \
    unzip

# For Whisper.cpp
sudo apt install -y \
    cmake \
    git \
    gcc \
    g++ \
    make

# For SSL/TLS (if using HTTPS)
sudo apt install -y certbot python3-certbot-nginx

# For process management
sudo apt install -y supervisor
```

### Step 3: Create Application User

```bash
# Create non-root user for app
sudo useradd -m -s /bin/bash -d /home/eva eva

# Give sudo permissions (optional)
sudo usermod -aG sudo eva

# Switch to app user
sudo su - eva
```

---

## Code Deployment

### Step 1: Clone Repository

```bash
# As eva user
cd ~
git clone https://github.com/kamalkushwaha1234/EVA_BACKEND_V1.git
cd EVA_BACKEND_V1
```

### Step 2: Create Virtual Environment

```bash
# Create venv
python3.11 -m venv venv

# Activate venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel
```

### Step 3: Install Python Dependencies

```bash
# Install from requirements.txt
pip install -r requirements.txt

# Verify installation
pip list
```

### Step 4: Create Environment File

Create `.env` file:

```bash
nano .env
```

Add (customize as needed):

```env
# Flask Configuration
FLASK_ENV=production
FLASK_APP=run.py
SECRET_KEY=your-secret-key-generate-with-openssl-rand-32

# Database
DATABASE_URL=sqlite:///eva_production.db

# JWT Configuration
JWT_SECRET_KEY=your-jwt-secret-key
JWT_ACCESS_TOKEN_EXPIRES=900
JWT_REFRESH_TOKEN_EXPIRES=2592000

# MQTT Configuration
MQTT_BROKER_HOST=your-mqtt-broker.com
MQTT_BROKER_PORT=8883
MQTT_USERNAME=your-mqtt-user
MQTT_PASSWORD=your-mqtt-password

# Azure/GitHub Models
GITHUB_TOKEN=your-github-token-for-models-api

# Redis (for rate limiting)
REDIS_URL=redis://localhost:6379/0

# Whisper (STT)
WHISPER_BIN=/home/eva/EVA_BACKEND_V1/whisper/whisper.cpp/build/bin/whisper-cli
WHISPER_MODEL=/home/eva/EVA_BACKEND_V1/whisper/whisper.cpp/models/ggml-tiny.bin

# Logging
LOG_LEVEL=INFO
LOG_FILE=/home/eva/logs/eva.log
```

Save: `Ctrl+X` → `Y` → `Enter`

### Step 5: Set File Permissions

```bash
# Make directories writable
mkdir -p ~/logs ~/uploads
chmod 755 ~/logs ~/uploads

# Set environment file permissions
chmod 600 .env
```

---

## Database & MQTT

### Step 1: Initialize Database

```bash
# Activate venv if not already
source venv/bin/activate

# Initialize database
python -c "
from app import create_app
from app.extensions import db
app = create_app()
with app.app_context():
    db.create_all()
    print('Database initialized successfully')
"
```

### Step 2: Create Admin User (Optional)

```bash
python -c "
from app import create_app
from app.models.user import User
from app.extensions import db
app = create_app()
with app.app_context():
    admin = User(
        username='admin',
        email='admin@eva.ai',
        password='set-strong-password'
    )
    db.session.add(admin)
    db.session.commit()
    print('Admin user created')
"
```

### Step 3: MQTT Setup

**Option A: Use Existing MQTT Broker**

Update `.env`:
```env
MQTT_BROKER_HOST=your-existing-broker.com
MQTT_BROKER_PORT=8883
```

**Option B: Install Local MQTT Broker**

```bash
# Install EMQ (MQTT broker)
wget https://www.emqx.com/en/downloads/broker/latest/emqx-5.0.0-otp25.2-ubuntu22.04-amd64.tar.gz
tar xfz emqx-*.tar.gz
cd emqx

# Start broker
./bin/emqx start

# Verify
./bin/emqx ping
```

Update `.env`:
```env
MQTT_BROKER_HOST=localhost
MQTT_BROKER_PORT=1883
```

---

## Whisper Setup

### Step 1: Download Setup Script

```bash
cd ~/EVA_BACKEND_V1/whisper

# For Linux, use the bash script
bash setup.sh
```

This will:
- Clone whisper.cpp
- Build the binary
- Download tiny model (75MB)
- Takes ~20-30 minutes

### Step 2: Verify Installation

```bash
# Test whisper binary
~/EVA_BACKEND_V1/whisper/whisper.cpp/build/bin/whisper-cli --version

# Should output: whisper : V1.4.0 ...
```

### Step 3: Update Paths in .env

Verify these match (auto-detected):

```bash
echo $WHISPER_BIN
echo $WHISPER_MODEL
```

---

## Running the Application

### Option 1: Development (Testing)

```bash
# Activate venv
cd ~/EVA_BACKEND_V1
source venv/bin/activate

# Run Flask
python run.py

# Should output:
# WARNING: This is a development server. Do not use it in production.
# Running on http://0.0.0.0:5000
```

Access at: `http://13.201.45.67:5000`

### Option 2: Production (Gunicorn + Systemd)

#### Step 1: Install Gunicorn

```bash
source ~/EVA_BACKEND_V1/venv/bin/activate
pip install gunicorn
```

#### Step 2: Create Systemd Service

Create service file:

```bash
sudo nano /etc/systemd/system/eva-backend.service
```

Add:

```ini
[Unit]
Description=EVA Backend Flask Application
After=network.target

[Service]
Type=notify
User=eva
WorkingDirectory=/home/eva/EVA_BACKEND_V1
Environment="PATH=/home/eva/EVA_BACKEND_V1/venv/bin"
ExecStart=/home/eva/EVA_BACKEND_V1/venv/bin/gunicorn \
    --workers 4 \
    --worker-class sync \
    --bind 0.0.0.0:5000 \
    --timeout 120 \
    --access-logfile /home/eva/logs/access.log \
    --error-logfile /home/eva/logs/error.log \
    run:app

Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Save: `Ctrl+X` → `Y` → `Enter`

#### Step 3: Enable & Start Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable on boot
sudo systemctl enable eva-backend

# Start service
sudo systemctl start eva-backend

# Check status
sudo systemctl status eva-backend

# View logs
sudo journalctl -u eva-backend -f
```

### Option 3: Production with Nginx (Recommended)

#### Step 1: Install Nginx

```bash
sudo apt install -y nginx
```

#### Step 2: Create Nginx Config

```bash
sudo nano /etc/nginx/sites-available/eva-backend
```

Add:

```nginx
upstream eva_app {
    server 127.0.0.1:5000;
}

server {
    listen 80;
    server_name 13.201.45.67;  # or your domain
    client_max_body_size 50M;

    # Access logs
    access_log /var/log/nginx/eva_access.log;
    error_log /var/log/nginx/eva_error.log;

    # Proxy to Gunicorn
    location / {
        proxy_pass http://eva_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    # WebSocket support
    location /socket.io {
        proxy_pass http://eva_app/socket.io;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

#### Step 3: Enable Nginx Config

```bash
# Create symlink
sudo ln -s /etc/nginx/sites-available/eva-backend /etc/nginx/sites-enabled/

# Remove default config
sudo rm /etc/nginx/sites-enabled/default

# Test config
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx

# Enable on boot
sudo systemctl enable nginx
```

#### Step 4: Setup SSL/TLS (Optional but Recommended)

```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Get certificate (requires domain)
sudo certbot --nginx -d your-domain.com

# Auto-renew
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer
```

---

## Monitoring & Maintenance

### Step 1: Monitor Application

```bash
# Check service status
sudo systemctl status eva-backend

# View logs (real-time)
sudo journalctl -u eva-backend -f

# View logs (last 100 lines)
sudo journalctl -u eva-backend -n 100

# View error log
tail -f /home/eva/logs/error.log

# View access log
tail -f /home/eva/logs/access.log
```

### Step 2: Monitor System Resources

```bash
# Check CPU/Memory usage
htop

# Check disk space
df -h

# Check memory usage
free -h

# Check network connections
netstat -tulpn
```

### Step 3: Automatic Backups

Create backup script: `~/backup.sh`

```bash
#!/bin/bash
BACKUP_DIR="/home/eva/backups"
mkdir -p $BACKUP_DIR

# Backup database
cp ~/EVA_BACKEND_V1/instance/eva_production.db \
   $BACKUP_DIR/eva_$(date +%Y%m%d_%H%M%S).db

# Keep only last 7 days
find $BACKUP_DIR -mtime +7 -delete

echo "Backup completed at $(date)"
```

Schedule with cron:

```bash
crontab -e

# Add line (backup daily at 2 AM):
0 2 * * * /home/eva/backup.sh
```

### Step 4: Monitor Logs

```bash
# Check for errors in last hour
sudo journalctl -u eva-backend --since "1 hour ago" | grep ERROR

# Get stats
sudo journalctl -u eva-backend --since "today" -S -1h | wc -l
```

---

## Troubleshooting

### 1. Application Won't Start

```bash
# Check logs
sudo journalctl -u eva-backend -n 50

# Check if port is in use
sudo lsof -i :5000

# Kill process on port
sudo fuser -k 5000/tcp

# Restart
sudo systemctl restart eva-backend
```

### 2. Database Errors

```bash
# Check database file
ls -lh ~/EVA_BACKEND_V1/instance/eva_production.db

# Recreate database
cd ~/EVA_BACKEND_V1
source venv/bin/activate
rm instance/eva_production.db
python -c "from app import create_app; from app.extensions import db; app = create_app(); \
with app.app_context(): db.create_all()"
```

### 3. MQTT Connection Issues

```bash
# Test MQTT connection
cd ~/EVA_BACKEND_V1
source venv/bin/activate

python -c "
import paho.mqtt.client as mqtt
client = mqtt.Client()
client.connect('your-mqtt-host', 8883)
client.loop_start()
print('MQTT connected successfully')
"
```

### 4. Whisper Not Found

```bash
# Verify paths
echo $WHISPER_BIN
echo $WHISPER_MODEL

# Check if files exist
ls -l $WHISPER_BIN
ls -l $WHISPER_MODEL

# Rebuild whisper
cd ~/EVA_BACKEND_V1/whisper/whisper.cpp
cmake --build build --config Release
```

### 5. High Memory Usage

```bash
# Check what's using memory
ps aux --sort=-%mem | head -10

# If Python process is huge, restart app
sudo systemctl restart eva-backend
```

### 6. SSL/Certificate Issues

```bash
# Check certificate validity
sudo certbot certificates

# Renew now
sudo certbot renew --force-renewal

# Check renewal logs
sudo journalctl -u certbot.timer -n 50
```

---

## Performance Tips

1. **Gunicorn Workers:** Set to `(2 × CPU_cores) + 1 = 9` for c7i.large
2. **Rate Limiting:** Adjust in config.py based on traffic
3. **Database:** Consider PostgreSQL for production
4. **Redis:** Enable for better rate limiting and caching
5. **CDN:** Use CloudFront for static assets
6. **Auto Scaling:** Setup Auto Scaling Group with Load Balancer

---

## Estimated Costs

**c7i.large on AWS EC2 (monthly estimate):**
- Instance: ~$62 (730 hours/month)
- Data Transfer: ~$5-10 (depends on usage)
- Storage (50GB): ~$4
- **Total: ~$70-75/month**

**Free tier (1 year):**
- t2.micro: Free
- 30GB storage: Free

---

## Useful Commands Reference

```bash
# Start/stop service
sudo systemctl start eva-backend
sudo systemctl stop eva-backend
sudo systemctl restart eva-backend

# View logs
sudo journalctl -u eva-backend -f
tail -f /home/eva/logs/error.log

# SSH to instance
ssh -i eva-backend-key.pem ubuntu@13.201.45.67

# SCP files to instance
scp -i eva-backend-key.pem file.txt ubuntu@13.201.45.67:~/

# Monitor
htop
df -h
free -h

# Update code
cd ~/EVA_BACKEND_V1
git pull
pip install -r requirements.txt
sudo systemctl restart eva-backend
```

---

## Next Steps

1. ✅ Create EC2 instance (c7i.large)
2. ✅ Configure security groups
3. ✅ Setup server & dependencies
4. ✅ Deploy code
5. ✅ Configure Whisper
6. ✅ Start application
7. ⏭️ Monitor & optimize
8. ⏭️ Setup CI/CD pipeline (GitHub Actions)
9. ⏭️ Configure domain name
10. ⏭️ Setup database backups to S3

---

**Questions? Check logs with:** `sudo journalctl -u eva-backend -f`
