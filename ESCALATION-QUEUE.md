# Escalation Queue

## Overview

The escalation queue ensures that escalated image queries will eventually make it to the cloud, even in the case of temporary network outages. The `escalation-queue-reader` container in the `edge-endpoint` pod runs a single-threaded process which continuously monitors the file-based queue for new entries. When it sees a queued item it attempts to escalate it to the Groundlight cloud service, retrying the request when applicable (see [Retrying failed escalations](#retrying-failed-escalations)).

Escalations from the queue are entirely asynchronous and the response from the cloud is never surfaced to the client. Escalations are written to the queue when either a) a synchronous escalation attempt fails or b) the edge answer is returned but the query is also escalated to the cloud due to low confidence or an audit. 

## Architecture

<img src="images/escalation-queue-flow.png" alt="Escalation queue flow" width="1200"/>

## Retrying failed escalations

If an escalation fails, we want to retry the request if we think it might eventually succeed and give up otherwise. Here's how we interpret errors from the escalation process:

| Exception                                  | Retry? | Explanation |
| :--------------------------------------    | :----: | :---------- |
| `GroundlightClientError` (on client init)  | Yes    | Client initialization failed (often no internet or transient SDK/client issue). We retry since it may start working again (e.g., when connectivity returns). |
| `FileNotFoundError` (on image load)        | No     | Image file is missing, so we can't submit the image query. |
| `MaxRetryError`                            | Yes    | SDK exhausted HTTP retries (likely network issue); we retry because it could succeed if the network comes back. |
| `HTTPException (400 Bad Request)`          | No     | Bad request (often a duplicate escalation or invalid request parameters); the request will not succeed even if retried. |
| `HTTPException (429 Too Many Requests)`    | Yes    | Throttled; once enough time passes, the escalation should succeed. |
| `HTTPException (other status)`             | No     | Unknown HTTP error; unknown whether a retry would help. |
| `Exception` (any other)                    | No     | Unexpected error; unknown whether a retry would help. |
