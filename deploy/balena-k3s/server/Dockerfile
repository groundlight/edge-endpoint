# https://hub.docker.com/r/rancher/k3s/tags
# https://github.com/k3s-io/k3s/blob/master/package/Dockerfile
# https://github.com/balena-io-experimental/balena-k3s/blob/main/server/Dockerfile
FROM rancher/k3s:v1.26.14-k3s1

COPY server.sh /server.sh
RUN chmod +x /server.sh

# Make pinamod-public directory for hostmapped volume
RUN mkdir -p /opt/groundlight/edge/pinamod-public

ENTRYPOINT []
CMD [ "/server.sh" ]