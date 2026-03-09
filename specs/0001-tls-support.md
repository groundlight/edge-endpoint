# Spec: Enable TLS for Edge-Endpoint (EE) with Self-Signed Certificate

status: completed

## Summary
Currently, the Edge-Endpoint (EE) only listens on unencrypted HTTP (port 30101). This spec describes the changes required to expose an HTTPS port (443) with a self-signed certificate, following the pattern used in Janzu.

## Proposed Changes

### 1. Certificate Generation
A new script `generate-tls-cert.sh` will be added to `edge-endpoint/app/bin/`. This script will generate a self-signed RSA certificate and private key using `openssl`.

### 2. Deployment Updates (`edge-endpoint/deploy/helm/groundlight-edge-endpoint/templates/edge-deployment.yaml`)
- **Init Container**: A new init container `generate-tls-cert` will be added to the `edge-endpoint` pod. It will run the `generate-tls-cert.sh` script.
- **Shared Volume**: An `emptyDir` volume named `nginx-certs` will be added to the pod to share the generated certificate and key between the init container and the `nginx` container.
- **Volume Mounts**: 
  - The `generate-tls-cert` init container will mount `nginx-certs` at `/etc/nginx/certs`.
  - The `nginx` container will mount `nginx-certs` at `/etc/nginx/certs`.

### 3. Nginx Configuration (`edge-endpoint/deploy/helm/groundlight-edge-endpoint/files/nginx.conf`)
The Nginx configuration will be updated to:
- Listen on port 443 with SSL enabled.
- Use the certificate and key from `/etc/nginx/certs/certificate.crt` and `/etc/nginx/certs/private.key`.
- Maintain existing port 30101 for backward compatibility (HTTP).

### 4. Service Updates (`edge-endpoint/deploy/helm/groundlight-edge-endpoint/templates/edge-deployment.yaml` and `values.yaml`)
- The `edge-endpoint-service` will be updated to include a new port named `https` on port 443.
- A new value `edgeEndpointHttpsPort` will be added to `values.yaml` with a default value of `30143` (to avoid conflicts and follow NodePort conventions).

## Detailed Design

### Certificate Generation Script
The script will be a direct copy of `zuuul/janzu/bin/generate-tls-cert.sh` but adjusted for the EE path if necessary.

### Kubernetes Manifest Changes
#### Init Container
```yaml
- name: generate-tls-cert
  image: *edgeEndpointImage
  volumeMounts:
    - name: nginx-certs
      mountPath: /etc/nginx/certs
  command: ["/bin/bash", "/groundlight-edge/app/bin/generate-tls-cert.sh"]
```

#### Nginx Container Ports
```yaml
ports:
- containerPort: 30101
  name: http
- containerPort: 443
  name: https
```

#### Service Ports
```yaml
ports:
- protocol: TCP
  port: 30101
  name: http
  nodePort: {{ .Values.edgeEndpointPort }}
- protocol: TCP
  port: 443
  name: https
  nodePort: {{ .Values.edgeEndpointHttpsPort }}
```

## Verification Plan
1. Deploy the updated Helm chart.
2. Verify that the `generate-tls-cert` init container completes successfully.
3. Verify that the `nginx` container starts and logs show it listening on 443.
4. Execute `curl -k https://<node-ip>:30143/status` and verify it returns a successful response.
5. Verify that HTTP still works: `curl http://<node-ip>:30101/status`.

### SDK Configuration
To use the Groundlight Python SDK with the self-signed certificate, the following environment variables are required:
```bash
export GROUNDLIGHT_ENDPOINT=https://<node-ip>:30143
export DISABLE_TLS_VARIABLE_NAME=1
```
