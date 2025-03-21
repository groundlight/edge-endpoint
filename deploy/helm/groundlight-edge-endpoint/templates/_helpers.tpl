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
  Get the edge-config.yaml file. If the user supplies one via `--set-file configFile=...yaml`
  then use that. Otherwise, use the default version in the `files/` directory. We define this
  as a function so that we can use it as a nonce to restart the pod when the config changes.
*/}}
{{- define "groundlight-edge-endpoint.edgeConfig" -}}
{{- if .Values.configFile }}
{{- .Values.configFile }}
{{- else }}
{{- .Files.Get "files/default-edge-config.yaml" }}
{{- end }}
{{- end }}

