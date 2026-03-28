FROM alpine:3.19
RUN apk add --no-cache bash curl docker-cli
COPY update-port.sh /update-port.sh
RUN chmod +x /update-port.sh
CMD ["/update-port.sh"]
