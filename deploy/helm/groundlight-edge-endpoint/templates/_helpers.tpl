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
  Determine the correct image tag to use for each container type. If the specific override
  is set for that image, use it. Otherwise, use the global image tag.
*/}}
{{- define "groundlight-edge-endpoint.edgeEndpointTag" -}}
{{- .Values.edgeEndpointTag | default .Values.imageTag }}
{{- end }}

{{- define "groundlight-edge-endpoint.inferenceTag" -}}
{{- .Values.inferenceTag | default .Values.imageTag }}
{{- end }}

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

{{/*
  Resolve the per-install inference image mode. The new knob is `inferenceImageMode`;
  the legacy `useMinimalImage` boolean is honored for one release with explicit mapping:
    useMinimalImage: true  → fully_minimal
    useMinimalImage: false → standard
  Setting both fails the install — last-wins would be too easy to misuse during migration.
*/}}
{{- define "groundlight-edge-endpoint.inferenceImageMode" -}}
{{- /* `inferenceImageMode` default in values.yaml is "standard"; we treat a non-default
       value as "user explicitly set". hasKey on `useMinimalImage` works because the
       new chart no longer ships a default for it. Setting both fails the install. */ -}}
{{- $newSet := and (hasKey .Values "inferenceImageMode") (ne (toString .Values.inferenceImageMode) "standard") -}}
{{- $hasLegacy := hasKey .Values "useMinimalImage" -}}
{{- if and $newSet $hasLegacy -}}
  {{- fail "Both `inferenceImageMode` and the deprecated `useMinimalImage` are set. Remove `useMinimalImage` and use only `inferenceImageMode`." -}}
{{- else if $hasLegacy -}}
  {{- if .Values.useMinimalImage -}}fully_minimal{{- else -}}standard{{- end -}}
{{- else -}}
  {{- default "standard" .Values.inferenceImageMode -}}
{{- end -}}
{{- end -}}

{{/*
  Compute the full ECR image URI (incl. tag) for the inference server, picking the
  full vs minimal repository based on the boolean argument.
*/}}
{{- define "groundlight-edge-endpoint.inferenceImageFull" -}}
{{- printf "%s/gl-edge-inference:%s" .Values.ecrRegistry (include "groundlight-edge-endpoint.inferenceTag" .) -}}
{{- end -}}

{{- define "groundlight-edge-endpoint.inferenceImageMinimal" -}}
{{- printf "%s/gl-edge-inference-minimal:%s" .Values.ecrRegistry (include "groundlight-edge-endpoint.inferenceTag" .) -}}
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
  model-updater is still polling for it to become Ready — pods can effectively
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

