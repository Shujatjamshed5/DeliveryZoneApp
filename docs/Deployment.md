# Deployment Guide

## Option 1 — Local / Development

```bash
# Activate venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Run Flask development server
python app.py
# → http://localhost:5000
```

> **Warning**: Flask's built-in server is for development only. Do not expose it to the internet.

---

## Option 2 — Production (Windows)

### With Waitress (Recommended for Windows)

Waitress is a production-grade WSGI server for Windows.

```bash
pip install waitress

# Run with 2 worker threads (adjust based on your load)
waitress-serve --host=127.0.0.1 --port=5000 --threads=2 app:app
```

> **Note**: Use `--host=127.0.0.1` to bind to localhost only, then use IIS or Nginx as a reverse proxy.

---

## Option 3 — Production (Linux / Ubuntu)

### With Gunicorn + Nginx

```bash
pip install gunicorn
```

Create a systemd service:

**`/etc/systemd/system/deliveryzoneapp.service`**:
```ini
[Unit]
Description=AI Areas Importer — Delivery Zone Sync
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/DeliveryZoneApp
Environment="PATH=/var/www/DeliveryZoneApp/venv/bin"
ExecStart=/var/www/DeliveryZoneApp/venv/bin/gunicorn \
    --workers=2 \
    --bind=127.0.0.1:5000 \
    --timeout=300 \
    --keep-alive=5 \
    --log-file=/var/log/deliveryzoneapp/gunicorn.log \
    --log-level=info \
    app:app

Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable deliveryzoneapp
sudo systemctl start deliveryzoneapp
sudo systemctl status deliveryzoneapp
```

### Nginx Configuration

**`/etc/nginx/sites-available/deliveryzoneapp`**:
```nginx
server {
    listen 80;
    server_name yourdomain.com;

    # Redirect HTTP → HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    # ── SSE — disable buffering ──────────────────────────────────────
    # CRITICAL: SSE requires proxy buffering to be OFF
    proxy_buffering off;
    proxy_cache off;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header   Host             $host;
        proxy_set_header   X-Real-IP        $remote_addr;
        proxy_set_header   X-Forwarded-For  $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto https;

        # SSE-specific headers
        proxy_set_header   Connection '';
        chunked_transfer_encoding on;

        # Extended timeout for long-running operations (3 min)
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # Static files served directly by Nginx
    location /static/ {
        alias /var/www/DeliveryZoneApp/static/;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }

    # File upload size limit (match Flask config)
    client_max_body_size 16M;
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/deliveryzoneapp /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## Option 4 — Docker

### Dockerfile

```dockerfile
FROM python:3.12-slim

# System dependencies for Selenium + Tesseract
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    chromium \
    chromium-driver \
    libglib2.0-0 \
    libnss3 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn

# Copy application
COPY . .

# Create required directories
RUN mkdir -p uploads logs

# Selenium Chrome path for Linux
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

CMD ["gunicorn", \
     "--workers=2", \
     "--bind=0.0.0.0:5000", \
     "--timeout=300", \
     "--log-level=info", \
     "app:app"]
```

### docker-compose.yml

```yaml
version: '3.9'

services:
  web:
    build: .
    container_name: deliveryzoneapp
    ports:
      - "5000:5000"
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - FLASK_ENV=production
    env_file:
      - .env
    volumes:
      - ./data:/app/data          # area_mapping.json, branch_city_mapping.json
      - ./logs:/app/logs
      - uploads_vol:/app/uploads
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/"]
      interval: 30s
      timeout: 10s
      retries: 3

  nginx:
    image: nginx:alpine
    container_name: deliveryzoneapp_nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./static:/var/www/static:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - web
    restart: unless-stopped

volumes:
  uploads_vol:
```

### Running with Docker

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f web

# Stop
docker-compose down

# Rebuild after code changes
docker-compose up -d --build
```

---

## Environment Variables for Production

```env
# .env (production)
GEMINI_API_KEY=your_real_key_here
FLASK_ENV=production
FLASK_DEBUG=0

# Tesseract (if using OCR)
TESSERACT_PATH=/usr/bin/tesseract
```

---

## Security Hardening Checklist

- [ ] Set `FLASK_DEBUG=0` in production
- [ ] Run behind Nginx/IIS — do not expose Flask directly
- [ ] Use HTTPS (Let's Encrypt / certbot)
- [ ] Restrict `/api/branch-mapping` to admin IP or add auth
- [ ] Add rate limiting (Flask-Limiter)
- [ ] Set `client_max_body_size 16M` in Nginx (matches Flask)
- [ ] Run as non-root user (Docker) or www-data (Linux)
- [ ] Keep `venv/` and `.env` out of the web server's document root

---

## SSL Certificate Setup (Let's Encrypt)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
sudo systemctl reload nginx

# Auto-renew (runs twice daily via cron)
sudo certbot renew --dry-run
```
