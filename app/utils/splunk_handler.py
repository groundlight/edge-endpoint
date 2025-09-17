import json
import logging
import os
import time
import requests
from typing import Dict, Any, Optional
from threading import Thread, Event
from queue import Queue, Empty
import urllib3

# Disable SSL warnings for local development
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SplunkHECHandler(logging.Handler):
    """
    Custom logging handler that sends logs to Splunk via HTTP Event Collector (HEC).
    Implements async batching and retry logic for reliability.
    """
    
    def __init__(
        self,
        hec_url: Optional[str] = None,
        hec_token: Optional[str] = None,
        index: Optional[str] = None,
        source: str = "edge-endpoint",
        sourcetype: str = "edge:endpoint:logs",
        batch_size: int = 1,  # Send immediately for debugging
        flush_interval: float = 1.0,  # Flush quickly
        retry_count: int = 3,
        verify_ssl: bool = False
    ):
        super().__init__()
        
        # HEC configuration from environment or parameters
        self.hec_url = hec_url or os.getenv("SPLUNK_HEC_URL", "http://localhost:8088")
        self.hec_token = hec_token or os.getenv("SPLUNK_HEC_TOKEN", "")
        # Use "main" as fallback index for better compatibility
        self.index = index or os.getenv("SPLUNK_INDEX", "main")
        self.source = source
        self.sourcetype = sourcetype
        self.verify_ssl = verify_ssl
        
        # Batching configuration
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.retry_count = retry_count
        
        # Queue for async processing
        self.queue = Queue(maxsize=1000)
        self.stop_event = Event()
        
        # Start background thread for sending events
        self.sender_thread = Thread(target=self._sender_loop, daemon=True)
        self.sender_thread.start()
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Splunk {self.hec_token}",
            "Content-Type": "application/json"
        })
        
        # Track connection status
        self.connected = False
        self.last_connection_attempt = 0
        self._test_connection()
        
        # Start reconnection thread
        self.reconnect_thread = Thread(target=self._reconnect_loop, daemon=True)
        self.reconnect_thread.start()
    
    def _test_connection(self, retry_count=10, retry_delay=10):
        """Test connection to Splunk HEC endpoint with retries"""
        for attempt in range(retry_count):
            try:
                health_url = f"{self.hec_url}/services/collector/health"
                response = self.session.get(
                    health_url,
                    timeout=5,
                    verify=self.verify_ssl
                )
                if response.status_code == 200:
                    if not self.connected:
                        print(f"Successfully connected to Splunk HEC at {self.hec_url}")
                    self.connected = True
                    self.last_connection_attempt = time.time()
                    return True
                else:
                    if attempt == 0:
                        print(f"Warning: Splunk HEC returned status {response.status_code}")
                    self.connected = False
            except Exception as e:
                if attempt == 0:
                    print(f"Warning: Could not connect to Splunk HEC: {e}")
                self.connected = False
            
            if attempt < retry_count - 1:
                time.sleep(retry_delay * (attempt + 1))
        
        self.last_connection_attempt = time.time()
        return False
    
    def _reconnect_loop(self):
        """Background thread that attempts to reconnect to Splunk periodically"""
        reconnect_interval = 30  # Try to reconnect every 30 seconds
        
        while not self.stop_event.is_set():
            # Wait for the reconnect interval or until stop event
            self.stop_event.wait(reconnect_interval)
            
            if self.stop_event.is_set():
                break
            
            # Only try to reconnect if we're not connected and enough time has passed
            if not self.connected:
                time_since_last = time.time() - self.last_connection_attempt
                if time_since_last >= reconnect_interval:
                    print(f"Attempting to reconnect to Splunk HEC...")
                    if self._test_connection(retry_count=1):
                        print(f"Reconnected to Splunk HEC successfully")
                        # Process any queued events
                        self._flush_queue()
    
    def emit(self, record: logging.LogRecord):
        """
        Queue log record for sending to Splunk.
        Non-blocking to avoid impacting application performance.
        """
        try:
            # Format the record
            event = self._format_event(record)
            
            # Add to queue even if not connected (will be sent when connection is restored)
            self.queue.put_nowait(event)
        except Exception:
            # Silently drop if queue is full to avoid blocking
            pass
    
    def _format_event(self, record: logging.LogRecord) -> Dict[str, Any]:
        """Format log record as Splunk HEC event"""
        # Build event content
        event_content = {
            "message": self.format(record),
            "level": record.levelname,
            "logger": record.name,
            "thread": record.thread,
            "threadName": record.threadName,
            "process": record.process,
            "processName": record.processName,
            "pathname": record.pathname,
            "lineno": record.lineno,
            "funcName": record.funcName
        }
        
        # Add custom fields if present
        if hasattr(record, "detector_id"):
            event_content["detector_id"] = record.detector_id
        if hasattr(record, "component"):
            event_content["component"] = record.component
        if hasattr(record, "request_id"):
            event_content["request_id"] = record.request_id
        if hasattr(record, "image_query_id"):
            event_content["image_query_id"] = record.image_query_id
        
        # Add exception info if present
        if record.exc_info:
            event_content["exception"] = self.format(record)
        
        # Format for Splunk HEC - index must be at root level
        event_data = {
            "time": record.created,
            "host": os.getenv("HOSTNAME", "edge-endpoint"),
            "source": self.source,
            "sourcetype": self.sourcetype,
            "index": self.index,
            "event": event_content
        }
        
        return event_data
    
    def _sender_loop(self):
        """Background thread that sends events to Splunk in batches"""
        batch = []
        last_flush = time.time()
        
        while not self.stop_event.is_set():
            try:
                # Get events from queue with timeout
                timeout = max(0.1, self.flush_interval - (time.time() - last_flush))
                event = self.queue.get(timeout=timeout)
                batch.append(event)
                
                # Send batch if it reaches batch_size and we're connected
                if len(batch) >= self.batch_size and self.connected:
                    self._send_batch(batch)
                    batch = []
                    last_flush = time.time()
                    
            except Empty:
                # Queue is empty, check if we need to flush based on time
                if batch and self.connected and (time.time() - last_flush) >= self.flush_interval:
                    self._send_batch(batch)
                    batch = []
                    last_flush = time.time()
        
        # Send any remaining events when stopping
        if batch and self.connected:
            self._send_batch(batch)
    
    def _flush_queue(self):
        """Flush all queued events to Splunk"""
        if not self.connected:
            return
        
        batch = []
        while not self.queue.empty():
            try:
                event = self.queue.get_nowait()
                batch.append(event)
                
                if len(batch) >= 100:  # Send in chunks of 100
                    self._send_batch(batch)
                    batch = []
            except Empty:
                break
        
        if batch:
            self._send_batch(batch)
    
    def _send_batch(self, events: list):
        """Send a batch of events to Splunk HEC"""
        if not events or not self.connected:
            return
        
        # Format events for HEC batch endpoint
        payload = "\n".join(json.dumps(event) for event in events)
        
        # Retry logic
        for attempt in range(self.retry_count):
            try:
                response = self.session.post(
                    f"{self.hec_url}/services/collector/event",
                    data=payload,
                    timeout=10,
                    verify=self.verify_ssl
                )
                
                if response.status_code == 200:
                    # Success
                    return
                elif response.status_code == 401:
                    # Authentication failed, don't retry
                    print(f"Splunk HEC authentication failed. Check token.")
                    self.connected = False
                    return
                else:
                    # Other error, will retry
                    print(f"Splunk HEC returned {response.status_code}: {response.text}")
                    if attempt == self.retry_count - 1:
                        print(f"Failed to send to Splunk after {self.retry_count} attempts")
                        
            except requests.exceptions.RequestException as e:
                if attempt == self.retry_count - 1:
                    print(f"Error sending to Splunk: {e}")
                else:
                    # Wait before retry with exponential backoff
                    time.sleep(2 ** attempt)
    
    def flush(self):
        """Force flush any pending events"""
        # Send stop signal to trigger final flush
        self.stop_event.set()
        # Wait for sender thread to finish
        self.sender_thread.join(timeout=5)
    
    def close(self):
        """Clean up resources"""
        self.stop_event.set()
        self.flush()
        self.session.close()
        super().close()


class SplunkContextFilter(logging.Filter):
    """Filter to add additional context fields to log records"""
    
    def __init__(self, detector_id: Optional[str] = None, component: Optional[str] = None):
        super().__init__()
        self.detector_id = detector_id
        self.component = component
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Add context fields to record"""
        if self.detector_id:
            record.detector_id = self.detector_id
        if self.component:
            record.component = self.component
        return True


def create_splunk_logger(
    name: str,
    detector_id: Optional[str] = None,
    component: Optional[str] = None,
    level: int = logging.INFO
) -> logging.Logger:
    """
    Create a logger with Splunk HEC handler configured.
    
    Args:
        name: Logger name
        detector_id: Detector identifier for context
        component: Component name for context
        level: Logging level
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(f"splunk.{name}")
    logger.setLevel(level)
    
    # Avoid adding handlers repeatedly
    if not logger.handlers:
        # Add Splunk HEC handler
        splunk_handler = SplunkHECHandler()
        splunk_handler.setLevel(level)
        
        # Add formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        splunk_handler.setFormatter(formatter)
        
        # Add context filter if provided
        if detector_id or component:
            context_filter = SplunkContextFilter(detector_id, component)
            splunk_handler.addFilter(context_filter)
        
        logger.addHandler(splunk_handler)
    
    return logger



