FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    nginx \
    ffmpeg \
    curl \
    ca-certificates \
    jq \
    && apt-get clean

# نعمل مجلدات HLS ونسخ الإعدادات
RUN mkdir -p /var/www/html/hls /scripts
COPY nginx.conf /etc/nginx/nginx.conf
COPY start.sh /scripts/start.sh
COPY parse_variants.sh /scripts/parse_variants.sh
RUN chmod +x /scripts/start.sh /scripts/parse_variants.sh

EXPOSE 80
CMD ["/scripts/start.sh"]
