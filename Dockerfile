FROM python:3.12-slim

WORKDIR /app

# Install nginx, supervisor, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx supervisor curl && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /var/log/supervisor /var/run /run /var/log/nginx && \
    ln -sf /dev/stdout /var/log/nginx/access.log && \
    ln -sf /dev/stderr /var/log/nginx/error.log

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Nginx: place config in sites-available and symlink
COPY nginx.conf /etc/nginx/sites-available/default
RUN rm -f /etc/nginx/sites-enabled/default && \
    ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default && \
    ls -la /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default

# Nginx: override gzip settings in conf.d (avoids duplicate directive with Debian defaults)
RUN printf 'gzip_vary on;\ngzip_min_length 256;\ngzip_proxied any;\ngzip_comp_level 5;\ngzip_types text/plain text/css text/html application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml;\n' > /etc/nginx/conf.d/gzip.conf

# Nginx: disable daemon (supervisor runs it as foreground)
# Insert 'daemon off;' at the very TOP of nginx.conf (before events{} block)
RUN sed -i '1s/^/daemon off;\n/' /etc/nginx/nginx.conf

# Validate nginx config syntax at build time
RUN nginx -t

# Build initial landing.html
RUN python /app/build_landing.py || true

EXPOSE 80

HEALTHCHECK CMD curl --fail http://localhost/health || exit 1

CMD ["supervisord", "-c", "/app/supervisord.conf"]
