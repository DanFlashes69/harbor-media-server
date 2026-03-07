FROM alpine:3.19

RUN apk add --no-cache \
    bash \
    clamav \
    clamav-daemon \
    inotify-tools \
    curl \
    jq \
    xxd \
    netcat-openbsd \
    dos2unix \
    && mkdir -p /logs /quarantine

COPY scan.sh /usr/local/bin/scan.sh

# Fix Windows line endings (CRLF -> LF) and make executable
RUN dos2unix /usr/local/bin/scan.sh && chmod +x /usr/local/bin/scan.sh

# Configure ClamAV to connect to remote daemon
RUN mkdir -p /etc/clamav && \
    printf "TCPSocket 3310\nTCPAddr clamav\n" > /etc/clamav/clamd.conf && \
    printf "ServerHost clamav\nServerPort 3310\n" > /etc/clamav/clamdscan.conf

CMD ["/usr/local/bin/scan.sh"]
