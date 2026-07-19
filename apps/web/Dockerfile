FROM nginx:1.27-alpine
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY apps/web /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=20s --timeout=4s --retries=5 CMD wget -q -O - http://localhost/healthz || exit 1
