# QDStar website: static files served by nginx. The unprivileged variant runs
# as uid 101 and listens on 8080, so the container needs no capabilities.
FROM nginxinc/nginx-unprivileged:1.29-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY site/ /usr/share/nginx/html/

EXPOSE 8080
