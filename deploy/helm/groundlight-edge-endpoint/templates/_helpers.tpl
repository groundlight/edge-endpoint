{{/*
Expand the name of the chart.
*/}}
{{- define "groundlight-edge-endpoint.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "groundlight-edge-endpoint.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "groundlight-edge-endpoint.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "groundlight-edge-endpoint.labels" -}}
helm.sh/chart: {{ include "groundlight-edge-endpoint.chart" . }}
{{ include "groundlight-edge-endpoint.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "groundlight-edge-endpoint.selectorLabels" -}}
app.kubernetes.io/name: {{ include "groundlight-edge-endpoint.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "groundlight-edge-endpoint.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "groundlight-edge-endpoint.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
    We want to "own" the namespace we install into. This is a safety mechanism to ensure that
    can run the full lifecycle without getting tangled up with other stuff going on in the cluster.
*/}}
{{- define "validate.namespace" -}}
{{- $ns := lookup "v1" "Namespace" "" .Values.namespace }}
{{- if $ns }}
  {{- $helmOwner := index $ns.metadata.labels "app.kubernetes.io/managed-by" | default "" }}
  {{- $releaseName := index $ns.metadata.labels "app.kubernetes.io/instance" | default "" }}
  {{- if or (ne $helmOwner "Helm") (ne $releaseName .Release.Name) }}
    {{ fail (printf "❌ Error: Namespace '%s' already exists but is NOT owned by this Helm release ('%s'). Aborting deployment!" .Values.namespace .Release.Name) }}
  {{- end }}
{{- end }}
{{- end }}

{{/*
  Canonical origin (scheme://host) of upstreamEndpoint for edgeArtifactsMap lookup.
  Drops path, query, and trailing slash. Requires an absolute HTTPS URL.
*/}}
{{- define "groundlight-edge-endpoint.upstreamOrigin" -}}
{{- $parsed := urlParse .Values.upstreamEndpoint -}}
{{- $scheme := index $parsed "scheme" -}}
{{- $host := index $parsed "host" -}}
{{- if or (ne $scheme "https") (not $host) -}}
{{- fail (printf "upstreamEndpoint %q must be an absolute HTTPS URL" .Values.upstreamEndpoint) -}}
{{- end -}}
{{- printf "%s://%s" $scheme $host -}}
{{- end -}}

{{/*
  edgeArtifactsMap entry for the canonical upstream origin, as JSON. Fails closed
  when the origin is absent from the map.
*/}}
{{- define "groundlight-edge-endpoint.edgeArtifacts" -}}
{{- $origin := include "groundlight-edge-endpoint.upstreamOrigin" . -}}
{{- if not (hasKey .Values.edgeArtifactsMap $origin) -}}
{{- fail (printf "The provided upstreamEndpoint %q is not a recognized Groundlight API URL. Verify the value and try again." .Values.upstreamEndpoint) -}}
{{- end -}}
{{- index .Values.edgeArtifactsMap $origin | toJson -}}
{{- end -}}

{{/*
  Default image tag: values.imageTag if set, otherwise edgeArtifactsMap for the
  upstream. edgeEndpointTag / inferenceTag override this per image.
*/}}
{{- define "groundlight-edge-endpoint.imageTag" -}}
{{- if .Values.imageTag -}}
{{- .Values.imageTag -}}
{{- else -}}
{{- (include "groundlight-edge-endpoint.edgeArtifacts" . | fromJson).imageTag -}}
{{- end -}}
{{- end -}}

{{/*
  Determine the correct image tag to use for each container type. If the specific
  override is set for that image, use it. Otherwise, use the resolved imageTag.
*/}}
{{- define "groundlight-edge-endpoint.edgeEndpointTag" -}}
{{- .Values.edgeEndpointTag | default (include "groundlight-edge-endpoint.imageTag" .) }}
{{- end }}

{{- define "groundlight-edge-endpoint.inferenceTag" -}}
{{- .Values.inferenceTag | default (include "groundlight-edge-endpoint.imageTag" .) }}
{{- end }}

{{/*
  Resolve the edge image base (ECR registry host plus optional repo prefix) for the
  configured upstreamEndpoint via edgeArtifactsMap. An explicit .Values.ecrRegistry
  overrides the map. Unknown upstreams fail at render time (see edgeArtifacts).
  The result is prepended to each image repo name, so it never ends with a slash.
*/}}
{{- define "groundlight-edge-endpoint.ecrRegistry" -}}
{{- if .Values.ecrRegistry -}}
{{- .Values.ecrRegistry -}}
{{- else -}}
{{- (include "groundlight-edge-endpoint.edgeArtifacts" . | fromJson).ecrRegistry -}}
{{- end -}}
{{- end -}}

{{/*
  The registry host portion of the resolved image base (everything before the first
  "/"). Image pull secrets key on the registry host, so the registry-credentials
  docker-server must use this rather than the full image base.
*/}}
{{- define "groundlight-edge-endpoint.ecrRegistryHost" -}}
{{- include "groundlight-edge-endpoint.ecrRegistry" . | splitList "/" | first -}}
{{- end -}}

{{/*
  AWS region for the ECR login, derived from the resolved registry host
  (<acct>.dkr.ecr[-fips].<region>.amazonaws.com). An ECR authorization token is
  region-scoped: a token minted in one region is rejected with 400 Bad Request by a
  registry in another, so this must track ecrRegistry rather than the chart-wide
  awsRegion. Falls back to .Values.awsRegion when ecrRegistry has been overridden to
  something that is not an ECR host, so that escape hatch keeps working.
*/}}
{{- define "groundlight-edge-endpoint.ecrRegion" -}}
{{- $host := include "groundlight-edge-endpoint.ecrRegistryHost" . -}}
{{- $p := splitList "." $host -}}
{{- if and (eq (len $p) 6) (eq (index $p 1) "dkr") (hasPrefix "ecr" (index $p 2)) (eq (index $p 4) "amazonaws") (eq (index $p 5) "com") -}}
{{- index $p 3 -}}
{{- else -}}
{{- .Values.awsRegion -}}
{{- end -}}
{{- end -}}

{{/*
  Resolve the S3 bucket for model-weight mounts from edgeArtifactsMap, unless
  s3Mount.bucket is set as an explicit override.
*/}}
{{- define "groundlight-edge-endpoint.s3Bucket" -}}
{{- if .Values.s3Mount.bucket -}}
{{- .Values.s3Mount.bucket -}}
{{- else -}}
{{- (include "groundlight-edge-endpoint.edgeArtifacts" . | fromJson).s3Bucket -}}
{{- end -}}
{{- end -}}

{{/*
  Resolve the S3 region for model-weight mounts from edgeArtifactsMap, unless
  s3Mount.region is set as an explicit override.
*/}}
{{- define "groundlight-edge-endpoint.s3Region" -}}
{{- if .Values.s3Mount.region -}}
{{- .Values.s3Mount.region -}}
{{- else -}}
{{- (include "groundlight-edge-endpoint.edgeArtifacts" . | fromJson).s3Region -}}
{{- end -}}
{{- end -}}

{{/*
  Cron schedule for the refresh-ecr-creds job, derived from edgeArtifactsMap so
  environments with shorter credential TTLs (edge-artifacts AssumeRole, 1h) can
  refresh more often without changing the cadence for legacy GL_Public installs.
*/}}
{{- define "groundlight-edge-endpoint.credentialRefreshSchedule" -}}
{{- (include "groundlight-edge-endpoint.edgeArtifacts" . | fromJson).credentialRefreshSchedule -}}
{{- end -}}

{{/*
  Determine the correct pull policy to use for each container type. If it is 
  a dev tag, we use "Never" to avoid pulling from the registry. Otherwise,
  we use the global pull policy.
*/}}
{{- define "groundlight-edge-endpoint.edgeEndpointPullPolicy" -}}
{{- $tag := include "groundlight-edge-endpoint.edgeEndpointTag" . -}}
{{- if eq $tag "dev" -}}
Never
{{- else -}}
{{- default "IfNotPresent" .Values.imagePullPolicy -}}
{{- end -}}
{{- end -}}

{{- define "groundlight-edge-endpoint.inferencePullPolicy" -}}
{{- $tag := include "groundlight-edge-endpoint.inferenceTag" . -}}
{{- if eq $tag "dev" -}}
Never
{{- else -}}
{{- default "IfNotPresent" .Values.imagePullPolicy -}}
{{- end -}}
{{- end -}}

{{/*
  Get the edge config. If the user supplies one via `--set-file configFile=...yaml`,
  use that. Otherwise, fall back to an empty config; the EdgeEndpointConfig pydantic
  model in the python-sdk provides all defaults. This helper is also used as a nonce
  to restart the pod when the config changes.
*/}}
{{- define "groundlight-edge-endpoint.edgeConfig" -}}
{{- if .Values.configFile }}
{{- .Values.configFile }}
{{- else }}
{}
{{- end }}
{{- end }}

{{/*
  Validate that edge-config.yaml is parseable YAML at template-render time.
  Structural/semantic validation is handled by the Pydantic models at app startup.
*/}}
{{- define "validate.edgeConfig" -}}
{{- $raw := include "groundlight-edge-endpoint.edgeConfig" . -}}
{{- $parsed := fromYaml $raw -}}
{{- if and (kindIs "map" $parsed) (hasKey $parsed "Error") (eq (len $parsed) 1) (hasPrefix "error converting YAML to JSON:" (toString (index $parsed "Error"))) -}}
  {{- fail (printf "edge-config.yaml contains invalid YAML:\n%s" (index $parsed "Error")) -}}
{{- end -}}
{{- end -}}

{{/*
  Validate that the model-updater's rollout-ready timeout stays strictly under the
  inference pod's startupProbe ceiling (failureThreshold * 10s). If it doesn't,
  kubelet can kill the inference pod for a failed startup probe while the
  model-updater is still polling for it to become Ready  -  pods can effectively
  never start up. Catch the misconfiguration at `helm install/upgrade` rather
  than 45 min later when pods start crash-looping.
*/}}
{{- define "validate.timeouts" -}}
{{- $rollout := int .Values.modelUpdater.rolloutReadyTimeoutSeconds -}}
{{- $ceiling := mul (int .Values.inferenceDeployment.startupProbe.failureThreshold) 10 -}}
{{- if ge $rollout $ceiling -}}
  {{- fail (printf "modelUpdater.rolloutReadyTimeoutSeconds (%ds) must be less than inferenceDeployment.startupProbe.failureThreshold × 10s (%ds). Raise inferenceDeployment.startupProbe.failureThreshold proportionally when increasing modelUpdater.rolloutReadyTimeoutSeconds." $rollout $ceiling) -}}
{{- end -}}
{{- end -}}

{{/*
  Same busybox as apply-edge-config. FIPS app images are distroless and have
  no chown; do not pull a second image (aws-cli) just for this init.
*/}}
{{- define "groundlight-edge-endpoint.hostPathChown.image" -}}
busybox:1.36
{{- end -}}

{{/*
  Root init container that chowns Edge-owned writable mounts to uid 65532.

  FIPS images run as USER 65532. kubelet creates hostPath DirectoryOrCreate as
  root, and fsGroup does not chown hostPath. The PVC (edge-endpoint-pvc) is
  included too so a local-path volume that happened to be root-owned still
  works; fsGroup would usually cover that case. The chart does not set a
  global runAsUser: FIPS-ness is the image USER plus which registry the
  device pulls.

  Caller passes a list of dicts with name, mountPath, and optional chownPath
  (defaults to mountPath). Optional exclude is a space-separated list of
  immediate child names to leave alone (pinamod FUSE dirs on the shared PVC).
  Chown the whole device hostPath: tokens, edge-metrics, and edge-profiling
  are all written by USER 65532. certs are also a separate nginx-certs volume.
  When exclude is set, also chown the mount root itself (not recursive) so
  USER 65532 can create siblings of the excluded dirs.
*/}}
{{- define "groundlight-edge-endpoint.chownHostPaths.initContainer" -}}
- name: chown-hostpaths
  image: {{ include "groundlight-edge-endpoint.hostPathChown.image" . }}
  imagePullPolicy: IfNotPresent
  securityContext:
    runAsUser: 0
  command:
    - /bin/sh
    - -ec
    - mkdir -p{{ range . }} {{ .chownPath | default .mountPath }}{{ end }}; {{ range . }}{{ if .exclude }}chown 65532:65532 {{ .mountPath }}; find {{ .mountPath }} -mindepth 1 -maxdepth 1{{ range (splitList " " .exclude) }} ! -name {{ . | quote }}{{ end }} -exec chown -R 65532:65532 {} +; {{ else }}chown -R 65532:65532 {{ .chownPath | default .mountPath }}; {{ end }}{{ end }}
  volumeMounts:
  {{- range . }}
    - name: {{ .name }}
      mountPath: {{ .mountPath }}
  {{- end }}
{{- end -}}

