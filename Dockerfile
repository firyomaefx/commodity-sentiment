FROM python:3.12-slim

WORKDIR /app

# Install nginx, supervisor, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx supervisor curl && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /var/log/supervisor /var/run /run && \
    ln -sf /dev/stdout /var/log/nginx/access.log && \
    ln -sf /dev/stderr /var/log/nginx/error.log

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Nginx config
COPY nginx.conf /etc/nginx/sites-enabled/default
RUN rm -f /etc/nginx/sites-enabled/default 2>/dev/null; \
    cp /etc/nginx/sites-enabled/default /etc/nginx/sites-available/default 2>/dev/null || true; \
    echo "daemon off;" >> /etc/nginx/nginx.conf

# Build initial landing.html immediately
RUN python /app/build_landing.py || true

EXPOSE 80

HEALTHCHECK CMD curl --fail http://localhost/health || exit 1

CMD ["supervisord", "-c", "/app/supervisord.conf"]
