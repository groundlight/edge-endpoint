FROM rancher/k3s:v1.24.10-k3s1 AS k3s

FROM alpine:3.20 

COPY --from=k3s /bin /bin
COPY --from=k3s /etc /etc
COPY --from=k3s /lib /lib

# Copied in from the final stage of the k3s container build
# https://github.com/k3s-io/k3s/blob/master/package/Dockerfile
VOLUME /var/lib/kubelet
VOLUME /var/lib/rancher/k3s
VOLUME /var/lib/cni
VOLUME /var/log
ENV PATH="$PATH:/bin/aux"
ENV CRI_CONFIG_FILE="/var/lib/rancher/k3s/agent/etc/crictl.yaml"

RUN apk -U --no-cache add jq aws-cli bash envsubst

COPY startup.sh /opt/groundlight/startup/
COPY tmp/ /opt/groundlight/

ENTRYPOINT ["/opt/groundlight/startup/startup.sh"]