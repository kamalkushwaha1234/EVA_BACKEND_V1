# AWS EC2 Deployment Checklist

Complete checklist for deploying EVA Backend to AWS EC2 c7i.large instance.

---

## 📋 Pre-Deployment (Local Machine)

- [ ] Create AWS account at https://console.aws.amazon.com/
- [ ] Generate AWS Access Key ID and Secret Access Key
- [ ] Install AWS CLI (`pip install awscli` or download installer)
- [ ] Run `aws configure` with your credentials
- [ ] Save GitHub token for cloning repository
- [ ] Generate strong passwords for MQTT, database admin, etc.
- [ ] Prepare environment variables list
- [ ] Download `eva-backend-key.pem` and save securely

---

## 🚀 AWS Setup (Console)

### Step 1: Create EC2 Instance

- [ ] Go to AWS EC2 Dashboard
- [ ] Click "Launch Instances"
- [ ] **Name:** `eva-backend-prod`
- [ ] **AMI:** Ubuntu Server 22.04 LTS
- [ ] **Instance Type:** `c7i.large`
- [ ] **Key Pair:** Create new → `eva-backend-key` → Download `.pem` file
- [ ] **Security Group:** Create new `eva-backend-sg`
- [ ] **Storage:** 50 GB gp3
- [ ] **Launch Instance**

### Step 2: Get Instance Details

```bash
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=eva-backend-prod" \
  --query 'Reservations[0].Instances[0].[PublicIpAddress,InstanceId]' \
  --output text
```

- [ ] Save **Public IP**: ____________
- [ ] Save **Instance ID**: ____________

### Step 3: Configure Security Group

Use AWS CLI or Console:

```bash
SECURITY_GROUP_ID="sg-xxxxx"

# SSH
aws ec2 authorize-security-group-ingress --group-id $SECURITY_GROUP_ID \
  --protocol tcp --port 22 --cidr 0.0.0.0/0

# HTTP
aws ec2 authorize-security-group-ingress --group-id $SECURITY_GROUP_ID \
  --protocol tcp --port 80 --cidr 0.0.0.0/0

# HTTPS
aws ec2 authorize-security-group-ingress --group-id $SECURITY_GROUP_ID \
  --protocol tcp --port 443 --cidr 0.0.0.0/0
```

- [ ] SSH rule added (port 22)
- [ ] HTTP rule added (port 80)
- [ ] HTTPS rule added (port 443)

---

## 🔐 SSH Setup

### Fix Key Permissions

**Windows PowerShell:**
```powershell
$KeyPath = "C:\path\to\eva-backend-key.pem"
icacls $KeyPath /grant:r "%USERNAME%:R"
icacls $KeyPath /inheritance:r
```

**Linux/macOS:**
```bash
chmod 400 eva-backend-key.pem
```

- [ ] Key file permissions fixed

### Connect to Instance

```bash
ssh -i eva-backend-key.pem ubuntu@YOUR_PUBLIC_IP
```

- [ ] Can SSH to instance
- [ ] Instance responding

---

## 📦 Server Setup (SSH into Instance)

### Step 1: Run Deployment Script

Transfer the `deploy.sh` script to instance:

```bash
scp -i eva-backend-key.pem deploy.sh ubuntu@YOUR_PUBLIC_IP:~
```

Connect and run:

```bash
ssh -i eva-backend-key.pem ubuntu@YOUR_PUBLIC_IP

# Run deployment script
bash ~/deploy.sh
```

- [ ] Deployment script executed successfully
- [ ] No errors during installation

### Expected Output:
```
╔════════════════════════════════════════════════════════════════╗
║       EVA Backend - AWS EC2 Deployment Script                  ║
║                 🎉 Setup Complete! 🎉                         ║
╚════════════════════════════════════════════════════════════════╝
```

---

## ⚙️ Configuration (on Instance)

### Step 1: Update Environment File

```bash
nano /home/eva/EVA_BACKEND_V1/.env
```

Update these values:

- [ ] `MQTT_BROKER_HOST` = your MQTT broker address
- [ ] `MQTT_BROKER_PORT` = 8883 or 1883
- [ ] `MQTT_USERNAME` = your MQTT username
- [ ] `MQTT_PASSWORD` = your MQTT password
- [ ] `GITHUB_TOKEN` = your GitHub token for Azure API
- [ ] `SECRET_KEY` = already generated ✓
- [ ] `JWT_SECRET_KEY` = already generated ✓

Save: `Ctrl+X` → `Y` → `Enter`

### Step 2: Initialize Application

```bash
# Verify environment
cat /home/eva/EVA_BACKEND_V1/.env

# Test database connection
cd /home/eva/EVA_BACKEND_V1
source venv/bin/activate
python -c "from app import create_app; app = create_app(); print('✓ App loads successfully')"
```

- [ ] `.env` file updated with all values
- [ ] Application loads without errors

---

## 🗣️ Whisper Setup (Optional)

### Setup Speech-to-Text

```bash
sudo su - eva
cd /home/eva/EVA_BACKEND_V1/whisper

# Run setup (takes 20-30 minutes)
bash setup.sh

# Verify
echo $WHISPER_BIN
ls -l $WHISPER_BIN
```

- [ ] Whisper repository cloned
- [ ] Binary compiled successfully
- [ ] Model downloaded (ggml-tiny.bin)
- [ ] Binary executable found

**Time estimate:** 20-30 minutes depending on CPU/internet

---

## 🚀 Start Application

### Option A: Development (Testing)

```bash
cd /home/eva/EVA_BACKEND_V1
source venv/bin/activate
python run.py
```

Test: `curl http://localhost:5000/health`

- [ ] Flask server starts
- [ ] No connection errors
- [ ] Health endpoint responds

### Option B: Production (Recommended)

```bash
# Start Gunicorn service
sudo systemctl start eva-backend

# Check status
sudo systemctl status eva-backend

# View logs
sudo journalctl -u eva-backend -f
```

- [ ] Service started successfully
- [ ] Status shows "active (running)"
- [ ] No errors in logs

### Option C: With Nginx (Full Production)

```bash
# Nginx is already configured
sudo systemctl start nginx
sudo systemctl status nginx

# Test
curl http://YOUR_PUBLIC_IP/health
```

- [ ] Nginx running
- [ ] Nginx responds to health endpoint
- [ ] API reachable from public IP

---

## ✅ Verification

### Test Endpoints

```bash
# From instance or local machine
curl http://YOUR_PUBLIC_IP/health
curl http://YOUR_PUBLIC_IP/api/v1/health

# Test with auth (requires token)
curl -H "Authorization: Bearer YOUR_TOKEN" http://YOUR_PUBLIC_IP/api/v1/user
```

- [ ] Health endpoint returns 200
- [ ] API endpoints responding
- [ ] CORS configured correctly

### Check Services

```bash
# All should show "active (running)"
sudo systemctl status eva-backend
sudo systemctl status nginx
sudo systemctl status supervisor  # if using supervisor

# Check logs for errors
sudo journalctl -u eva-backend -n 50
tail -f /home/eva/logs/error.log
```

- [ ] eva-backend service running
- [ ] nginx service running
- [ ] No critical errors in logs

### Monitor Resources

```bash
# Check usage
free -h          # Memory
df -h            # Disk
top -b -n 1      # CPU
```

- [ ] Memory usage reasonable (~1-2 GB)
- [ ] Disk space available (>10 GB)
- [ ] CPU usage normal

---

## 🔒 Security Hardening (Optional)

### Install Fail2Ban

```bash
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
```

- [ ] Fail2Ban installed

### Setup SSL Certificate

```bash
# If using domain name
sudo certbot --nginx -d your-domain.com

# For self-signed (development)
sudo certbot --nginx --register --agree-tos -m admin@eva.ai
```

- [ ] SSL certificate configured
- [ ] HTTPS working (https://your-domain.com)

### Firewall Rules

```bash
# Restrict SSH to your IP only (optional)
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp --port 22 \
  --cidr YOUR_IP/32
```

- [ ] Firewall rules optimized
- [ ] Only necessary ports open

---

## 📊 Monitoring Setup

### View Logs

```bash
# Real-time logs
sudo journalctl -u eva-backend -f

# Last 100 lines
sudo journalctl -u eva-backend -n 100

# Error logs
tail -f /home/eva/logs/error.log

# Access logs
tail -f /home/eva/logs/access.log
```

- [ ] Can view application logs
- [ ] Can identify errors

### Set Up Monitoring

```bash
# Check if service is running
/home/eva/health-check.sh

# Add to crontab to check every 5 minutes
*/5 * * * * /home/eva/health-check.sh >> /home/eva/logs/health-check.log 2>&1
```

- [ ] Health check script working
- [ ] Monitoring configured

---

## 🔄 Maintenance

### Regular Updates

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Update Python packages
cd /home/eva/EVA_BACKEND_V1
source venv/bin/activate
pip install --upgrade -r requirements.txt

# Restart service
sudo systemctl restart eva-backend
```

- [ ] Scheduled update plan
- [ ] Backup procedure documented

### Backups

```bash
# Manual backup
sudo -u eva /home/eva/backup.sh

# Check backups
ls -lh /home/eva/backups/

# Auto backup (cron job - already configured)
# Runs daily at 2 AM
```

- [ ] Backup script working
- [ ] At least one backup exists
- [ ] Cron job configured

---

## 📈 Performance Optimization

- [ ] Gunicorn workers set to 9 (for c7i.large: 2×CPU+1 = 9)
- [ ] Rate limiting configured
- [ ] Database indexed
- [ ] Static files served via Nginx
- [ ] Gzip compression enabled
- [ ] Keep-alive connections configured

---

## 🎯 Production Checklist

### Before Going Live

- [ ] SSL certificate configured
- [ ] Domain name pointing to instance
- [ ] Backups verified (tested restore)
- [ ] Monitoring alerts set up
- [ ] Error logging configured
- [ ] Rate limiting tested
- [ ] Database optimization complete
- [ ] Redis configured (if using)
- [ ] MQTT connection stable
- [ ] Whisper working (if using STT)

### Day 1 Monitoring

- [ ] Monitor error logs for issues
- [ ] Check response times
- [ ] Verify all endpoints working
- [ ] Monitor resource usage
- [ ] Test failover/restart procedures

---

## 🆘 Troubleshooting

### Application Won't Start

```bash
# Check logs
sudo journalctl -u eva-backend -n 50

# Check if port is in use
sudo lsof -i :5000

# Restart
sudo systemctl restart eva-backend
```

- [ ] Root cause identified
- [ ] Issue resolved

### High Memory Usage

```bash
# Check processes
ps aux --sort=-%mem | head -10

# Restart service if needed
sudo systemctl restart eva-backend
```

- [ ] Memory usage normalized
- [ ] No memory leaks detected

### Database Errors

```bash
# Check database
sqlite3 /home/eva/eva_production.db ".tables"

# Reinitialize if needed
cd /home/eva/EVA_BACKEND_V1
source venv/bin/activate
python -c "from app import create_app; from app.extensions import db; \
app = create_app(); \
with app.app_context(): db.create_all()"
```

- [ ] Database accessible
- [ ] Tables created
- [ ] No corruption

---

## 📞 Support Resources

- **AWS Support:** https://console.aws.amazon.com/support
- **Nginx Docs:** https://nginx.org/en/docs/
- **Gunicorn Docs:** https://gunicorn.org/
- **Flask Docs:** https://flask.palletsprojects.com/
- **Whisper.cpp:** https://github.com/ggerganov/whisper.cpp

---

## 📝 Instance Info

| Property | Value |
|----------|-------|
| **Instance Type** | c7i.large |
| **Instance ID** | ______________ |
| **Public IP** | ______________ |
| **Public DNS** | ______________ |
| **Region** | ______________ |
| **Key Pair** | eva-backend-key |
| **Security Group** | eva-backend-sg |
| **Root Volume Size** | 50 GB |
| **Root Volume Type** | gp3 |

---

## ✨ Deployment Complete!

### Next Steps:
1. Monitor application for 24 hours
2. Test all endpoints thoroughly
3. Set up alerting/monitoring
4. Document any customizations
5. Plan scaling strategy

### Cost Estimation (Monthly):
- **c7i.large:** ~$62
- **Data Transfer:** ~$5-10
- **Storage (50GB):** ~$4
- **Total:** ~$70-75/month

---

**Last Updated:** May 31, 2026
**Version:** 1.0
**Maintainer:** Your Team
