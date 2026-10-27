# Compile the fork so native controls are embedded in every generated report.
FROM alpine:3.22 AS build
RUN apk add --no-cache autoconf automake build-base gettext-dev libmaxminddb-dev openssl-dev ncurses-dev pkgconf
WORKDIR /source
COPY . .
RUN autoreconf -fiv && ./configure --prefix=/usr --enable-utf8 --with-openssl --enable-geoip=mmdb \
    && make -j2 && make DESTDIR=/dist install
FROM alpine:3.22
RUN apk add --no-cache nginx python3 tzdata gettext-libs libmaxminddb ncurses-libs openssl
COPY --from=build /dist/usr/bin/goaccess /usr/bin/goaccess
COPY --from=build /dist/usr/share /usr/share
COPY deploy/date-reports/server.py /opt/monitoring/server.py
COPY deploy/date-reports/entrypoint.sh /usr/local/bin/rms-monitor-entrypoint
COPY deploy/date-reports/nginx.conf /etc/nginx/http.d/default.conf
RUN chmod +x /usr/local/bin/rms-monitor-entrypoint && mkdir -p /usr/share/nginx/html/reports
ENTRYPOINT ["/usr/local/bin/rms-monitor-entrypoint"]
