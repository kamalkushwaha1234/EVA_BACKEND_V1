#!/bin/bash
#
# EVA Backend - Automated AWS EC2 Deployment Script
# Run this on a fresh Ubuntu 22.04 instance
#
# Usage: bash deploy.sh
#

set -e  # Exit on error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APP_USER="eva"
APP_DIR="/home/$APP_USER/EVA_BACKEND_V1"
REPO_URL="https://github.com/kamalkushwaha1234/EVA_BACKEND_V1.git"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║       EVA Backend - AWS EC2 Deployment Script                  ║"
echo "║                                                                ║"
echo "║  Instance: c7i.large                                          ║"
echo "║  OS: Ubuntu 22.04 LTS                                         ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ============================================================================
# 1. Update System
# ============================================================================
echo -e "${YELLOW}[1/8]${NC} Updating system packages..."
sudo apt update && sudo apt upgrade -y

# ============================================================================
# 2. Install Dependencies
# ============================================================================
echo -e "${YELLOW}[2/8]${NC} Installing dependencies..."

# Python & Build Tools
sudo apt install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    build-essential \
    libssl-dev \
    libffi-dev

# Database & Utilities
sudo apt install -y \
    sqlite3 \
    git \
    curl \
    wget \
    htop \
    nano \
    unzip

# Whisper dependencies
sudo apt install -y \
    cmake \
    gcc \
    g++ \
    make

# Additional tools
sudo apt install -y \
    supervisor \
    nginx \
    certbot \
    python3-certbot-nginx \
    jq

echo -e "${GREEN}✓ Dependencies installed${NC}"

# ============================================================================
# 3. Create Application User
# ============================================================================
echo -e "${YELLOW}[3/8]${NC} Setting up application user..."

if ! id -u $APP_USER > /dev/null 2>&1; then
    sudo useradd -m -s /bin/bash -d /home/$APP_USER $APP_USER
    sudo usermod -aG sudo $APP_USER
    echo -e "${GREEN}✓ User '$APP_USER' created${NC}"
else
    echo -e "${GREEN}✓ User '$APP_USER' already exists${NC}"
fi

# Create necessary directories
sudo mkdir -p /home/$APP_USER/logs
sudo mkdir -p /home/$APP_USER/uploads
sudo mkdir -p /home/$APP_USER/backups
sudo chown -R $APP_USER:$APP_USER /home/$APP_USER/

# ============================================================================
# 4. Clone Repository
# ============================================================================
echo -e "${YELLOW}[4/8]${NC} Cloning repository..."

if [ ! -d "$APP_DIR" ]; then
    sudo -u $APP_USER git clone $REPO_URL $APP_DIR
    echo -e "${GREEN}✓ Repository cloned${NC}"
else
    echo -e "${GREEN}✓ Repository already exists${NC}"
fi

# ============================================================================
# 5. Setup Python Virtual Environment
# ============================================================================
echo -e "${YELLOW}[5/8]${NC} Setting up Python virtual environment..."

cd $APP_DIR
sudo -u $APP_USER python3.11 -m venv venv
sudo -u $APP_USER ./venv/bin/pip install --upgrade pip setuptools wheel
sudo -u $APP_USER ./venv/bin/pip install -r requirements.txt

echo -e "${GREEN}✓ Virtual environment configured${NC}"

# ============================================================================
# 6. Create Environment File
# ============================================================================
echo -e "${YELLOW}[6/8]${NC} Creating environment configuration..."

if [ ! -f "$APP_DIR/.env" ]; then
    # Generate random secrets
    SECRET_KEY=$(openssl rand -hex 32)
    JWT_SECRET=$(openssl rand -hex 32)
    
    cat > $APP_DIR/.env << EOF
# Flask Configuration
FLASK_ENV=production
FLASK_APP=run.py
SECRET_KEY=$SECRET_KEY

# Database
DATABASE_URL=sqlite:////home/$APP_USER/eva_production.db

# JWT Configuration
JWT_SECRET_KEY=$JWT_SECRET
JWT_ACCESS_TOKEN_EXPIRES=900
JWT_REFRESH_TOKEN_EXPIRES=2592000

# MQTT Configuration
MQTT_BROKER_HOST=your-mqtt-broker.com
MQTT_BROKER_PORT=8883
MQTT_USERNAME=your-mqtt-user
MQTT_PASSWORD=your-mqtt-password

# Azure/GitHub Models
GITHUB_TOKEN=your-github-token

# Redis (optional)
REDIS_URL=redis://localhost:6379/0

# Whisper (STT)
WHISPER_BIN=$APP_DIR/whisper/whisper.cpp/build/bin/whisper-cli
WHISPER_MODEL=$APP_DIR/whisper/whisper.cpp/models/ggml-tiny.bin

# Logging
LOG_LEVEL=INFO
LOG_FILE=/home/$APP_USER/logs/eva.log
EOF

    chmod 600 $APP_DIR/.env
    sudo chown $APP_USER:$APP_USER $APP_DIR/.env
    
    echo -e "${GREEN}✓ Environment file created${NC}"
    echo -e "${YELLOW}  ⚠️  IMPORTANT: Update .env with your actual values${NC}"
else
    echo -e "${GREEN}✓ Environment file already exists${NC}"
fi

# ============================================================================
# 7. Initialize Database
# ============================================================================
echo -e "${YELLOW}[7/8]${NC} Initializing database..."

cd $APP_DIR
sudo -u $APP_USER ./venv/bin/python << 'EOF'
from app import create_app
from app.extensions import db

app = create_app()
with app.app_context():
    db.create_all()
    print("✓ Database initialized successfully")
EOF

# ============================================================================
# 8. Setup Whisper (Optional - commented out for manual control)
# ============================================================================
echo -e "${YELLOW}[8/8]${NC} Whisper setup instructions..."
echo -e "${BLUE}"
cat << 'EOF'
  To setup Whisper (speech-to-text), run:
  
  cd /home/eva/EVA_BACKEND_V1/whisper
  bash setup.sh
  
  This will:
    - Clone whisper.cpp
    - Build the binary (takes 20-30 minutes)
    - Download the tiny model (75MB)
  
  For now, continuing with Flask setup...
EOF
echo -e "${NC}"

# ============================================================================
# 9. Setup Gunicorn Service
# ============================================================================
echo -e "${YELLOW}Setting up Gunicorn service...${NC}"

# Create systemd service
sudo tee /etc/systemd/system/eva-backend.service > /dev/null << 'EOF'
[Unit]
Description=EVA Backend Flask Application
After=network.target

[Service]
Type=notify
User=eva
WorkingDirectory=/home/eva/EVA_BACKEND_V1
Environment="PATH=/home/eva/EVA_BACKEND_V1/venv/bin"
Environment="FLASK_ENV=production"
ExecStart=/home/eva/EVA_BACKEND_V1/venv/bin/gunicorn \
    --workers 9 \
    --worker-class sync \
    --bind 127.0.0.1:5000 \
    --timeout 120 \
    --access-logfile /home/eva/logs/access.log \
    --error-logfile /home/eva/logs/error.log \
    run:app

Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Install gunicorn
sudo -u $APP_USER $APP_DIR/venv/bin/pip install gunicorn

# Reload systemd
sudo systemctl daemon-reload
sudo systemctl enable eva-backend

echo -e "${GREEN}✓ Gunicorn service configured${NC}"

# ============================================================================
# 10. Setup Nginx (Reverse Proxy)
# ============================================================================
echo -e "${YELLOW}Setting up Nginx reverse proxy...${NC}"

# Backup default config
sudo cp /etc/nginx/sites-available/default /etc/nginx/sites-available/default.backup

# Create eva-backend config
sudo tee /etc/nginx/sites-available/eva-backend > /dev/null << 'EOF'
upstream eva_app {
    server 127.0.0.1:5000;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    
    server_name _;
    client_max_body_size 50M;

    access_log /var/log/nginx/eva_access.log;
    error_log /var/log/nginx/eva_error.log;

    location / {
        proxy_pass http://eva_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

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
EOF

# Enable config
sudo ln -sf /etc/nginx/sites-available/eva-backend /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test nginx config
sudo nginx -t

# Enable and start nginx
sudo systemctl enable nginx
sudo systemctl restart nginx

echo -e "${GREEN}✓ Nginx configured${NC}"

# ============================================================================
# 11. Create Backup Script
# ============================================================================
echo -e "${YELLOW}Setting up backup script...${NC}"

sudo tee /home/$APP_USER/backup.sh > /dev/null << 'EOF'
#!/bin/bash
BACKUP_DIR="/home/eva/backups"
mkdir -p $BACKUP_DIR

# Backup database
cp /home/eva/eva_production.db $BACKUP_DIR/eva_$(date +%Y%m%d_%H%M%S).db

# Keep only last 7 days
find $BACKUP_DIR -mtime +7 -delete

echo "Backup completed at $(date)" >> /home/eva/logs/backup.log
EOF

sudo chmod +x /home/$APP_USER/backup.sh
sudo chown $APP_USER:$APP_USER /home/$APP_USER/backup.sh

# Add to crontab (backup daily at 2 AM)
(sudo -u $APP_USER crontab -l 2>/dev/null || true; echo "0 2 * * * /home/eva/backup.sh") | \
    sudo -u $APP_USER crontab -

echo -e "${GREEN}✓ Backup script configured${NC}"

# ============================================================================
# 12. Create Health Check Script
# ============================================================================
echo -e "${YELLOW}Setting up health check...${NC}"

sudo tee /home/$APP_USER/health-check.sh > /dev/null << 'EOF'
#!/bin/bash
ENDPOINT="http://127.0.0.1:5000/health"
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" $ENDPOINT)

if [ "$RESPONSE" -eq 200 ]; then
    echo "✓ Service healthy"
    exit 0
else
    echo "✗ Service unhealthy (HTTP $RESPONSE)"
    exit 1
fi
EOF

sudo chmod +x /home/$APP_USER/health-check.sh
sudo chown $APP_USER:$APP_USER /home/$APP_USER/health-check.sh

# ============================================================================
# Summary
# ============================================================================
echo -e "${GREEN}"
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                   🎉 Setup Complete! 🎉                        ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "${BLUE}Next Steps:${NC}"
echo ""
echo -e "1. ${YELLOW}Update Environment Variables${NC}"
echo "   nano $APP_DIR/.env"
echo "   (Update MQTT_BROKER_HOST, GITHUB_TOKEN, etc.)"
echo ""

echo -e "2. ${YELLOW}Setup Whisper (Optional)${NC}"
echo "   sudo su - $APP_USER"
echo "   cd $APP_DIR/whisper"
echo "   bash setup.sh"
echo ""

echo -e "3. ${YELLOW}Start Application${NC}"
echo "   sudo systemctl start eva-backend"
echo "   sudo systemctl status eva-backend"
echo ""

echo -e "4. ${YELLOW}View Logs${NC}"
echo "   sudo journalctl -u eva-backend -f"
echo ""

echo -e "5. ${YELLOW}Test Endpoint${NC}"
echo "   curl http://localhost/health"
echo ""

echo -e "${BLUE}Useful Commands:${NC}"
echo "  Monitor service:       sudo systemctl status eva-backend"
echo "  View logs:            sudo journalctl -u eva-backend -f"
echo "  Restart service:      sudo systemctl restart eva-backend"
echo "  Update code:          cd $APP_DIR && git pull"
echo "  Check disk:           df -h"
echo "  Check memory:         free -h"
echo "  Check CPU usage:      htop"
echo ""

echo -e "${YELLOW}⚠️  IMPORTANT: Don't forget to:${NC}"
echo "  ✓ Update .env with real values"
echo "  ✓ Setup MQTT broker connection"
echo "  ✓ Generate GitHub token for Azure API"
echo "  ✓ Configure domain name (if applicable)"
echo "  ✓ Setup SSL certificate (certbot)"
echo "  ✓ Run Whisper setup for speech-to-text"
echo ""

echo -e "${BLUE}Security Groups to Allow:${NC}"
echo "  ✓ SSH (22) - for server access"
echo "  ✓ HTTP (80) - for web traffic"
echo "  ✓ HTTPS (443) - for encrypted traffic"
echo ""

echo -e "${GREEN}Deployment completed successfully!${NC}"
