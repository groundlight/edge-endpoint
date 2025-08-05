# Escalation Queue

## Overview

The escalation queue provides a persistent, reliable mechanism for handling image query escalations to the Groundlight cloud service. When the edge endpoint determines that a query needs escalation (due to low confidence results, audit sampling, or failed direct escalations), it writes the escalation request to a local file-based queue for background processing.

## Architecture

The escalation queue system operates across two containers within the edge-endpoint pod:

```mermaid
flowchart LR
    subgraph POD ["edge-endpoint pod"]
        subgraph CONT1 ["edge-endpoint container"]
            EDGE[Edge Endpoint<br/>Image Query Processing]
            DECISION{Needs<br/>Escalation?}
            QUEUE_WRITE[Write to<br/>Escalation Queue]
        end
        
        subgraph CONT2 ["escalation-queue-reader container"]
            QUEUE_READ[Queue Reader<br/>Background Service]
            CLOUD_SUBMIT[Submit to<br/>Groundlight Cloud]
        end
    end
    
    subgraph STORAGE ["Local Persistent Storage"]
        QUEUE[File-based Queue<br/>Persistent Storage]
    end
    
    %% Main Flow
    EDGE --> DECISION
    DECISION -->|"Asynchronous<br/>(low confidence, audit)"| QUEUE_WRITE
    DECISION -->|"Synchronous<br/>(direct return)"| RESPONSE[Return to Client]
    QUEUE_WRITE --> QUEUE
    QUEUE_WRITE --> RESPONSE
    
    %% Background Flow
    QUEUE --> |Continuously monitors<br/>and processes| QUEUE_READ
    QUEUE_READ --> CLOUD_SUBMIT
    
    %% Individual node styling
    classDef nodeMain fill:#e8f5e8,stroke:#2e7d32,stroke-width:2px,color:#000000
    classDef nodeStorage fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px,color:#000000
    classDef nodeBackground fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#000000
    classDef nodeResponse fill:#fff3e0,stroke:#f57c00,stroke-width:2px,color:#000000
    
    %% Subgraph styling (big container backgrounds)
    classDef subgraphOffWhite fill:#fafafa,stroke:#424242,stroke-width:1px
    
    %% Apply node styles (individual rectangles/shapes)
    class EDGE,DECISION,QUEUE_WRITE nodeMain
    class QUEUE nodeStorage
    class QUEUE_READ,CLOUD_SUBMIT nodeBackground
    class RESPONSE nodeResponse
    
    %% Apply subgraph styles (big container backgrounds)
    class POD,CONT1,STORAGE subgraphOffWhite
```

## Key Features

### Persistence
- Escalations are stored in local persistent storage that survives container restarts
- Queue processing can resume after interruptions without losing escalation requests

### Asynchronous Processing
- Client requests return immediately after queue writing (non-blocking)
- Background container continuously processes queued escalations
- Separates fast request handling from slower cloud communication

### Reliability
- File-based queue with atomic operations prevents data loss
- Retry logic with exponential backoff handles network failures
- Duplicate detection prevents processing the same request multiple times

## Components

- **edge-endpoint container**: Handles main API requests and writes escalations to queue
- **escalation-queue-reader container**: Background service that reads from queue and submits to cloud
- **Local Persistent Storage**: File-based queue storage shared between containers
