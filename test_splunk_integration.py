#!/usr/bin/env python3
"""
Test script to verify Splunk integration works in edge-endpoint.
This script tests the Splunk HEC handler and logging integration.
"""

import os
import sys
import time
import requests
from unittest.mock import patch

# Add the app directory to the path so we can import modules
sys.path.insert(0, 'app')

def test_splunk_handler():
    """Test the SplunkHECHandler can be imported and initialized."""
    print("Testing SplunkHECHandler import and initialization...")
    
    try:
        from app.utils.splunk_handler import SplunkHECHandler, create_splunk_logger
        print("✅ Successfully imported SplunkHECHandler")
        
        # Test handler initialization
        handler = SplunkHECHandler(
            hec_url="http://localhost:8088",
            hec_token="test-token",
            index="test",
            verify_ssl=False
        )
        print("✅ Successfully initialized SplunkHECHandler")
        
        # Test logger creation
        logger = create_splunk_logger("test", component="test_component")
        print("✅ Successfully created Splunk logger")
        
        # Clean up
        handler.close()
        return True
        
    except Exception as e:
        print(f"❌ Error testing SplunkHECHandler: {e}")
        return False

def test_loghelper():
    """Test the loghelper can be imported and creates loggers."""
    print("\nTesting loghelper import and logger creation...")
    
    try:
        from app.utils.loghelper import create_logger
        print("✅ Successfully imported loghelper")
        
        # Test logger creation without Splunk (should work)
        logger = create_logger("test", is_test=True, component="test_component")
        print("✅ Successfully created logger with loghelper")
        
        # Test logging
        logger.info("Test log message")
        print("✅ Successfully logged message")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing loghelper: {e}")
        return False

def test_environment_variables():
    """Test that environment variables are properly read."""
    print("\nTesting environment variable handling...")
    
    # Test with environment variables set
    test_env = {
        "SPLUNK_HEC_URL": "http://splunk:8088",
        "SPLUNK_HEC_TOKEN": "test-token-123",
        "SPLUNK_INDEX": "test_index"
    }
    
    with patch.dict(os.environ, test_env):
        try:
            from app.utils.splunk_handler import SplunkHECHandler
            
            handler = SplunkHECHandler()
            
            assert handler.hec_url == "http://test-splunk:8088"
            assert handler.hec_token == "test-token-123"
            assert handler.index == "test_index"
            
            print("✅ Environment variables correctly read")
            handler.close()
            return True
            
        except Exception as e:
            print(f"❌ Error testing environment variables: {e}")
            return False

def test_integration():
    """Test the integration can be used in main.py style."""
    print("\nTesting main.py style integration...")
    
    try:
        from app.utils.loghelper import create_logger
        
        # This is how it would be used in main.py
        logger = create_logger(__name__, component="edge_logic")
        logger.info("Test message from edge logic", extra={
            "detector_id": "test_detector",
            "request_id": "test_request"
        })
        
        print("✅ Successfully used logger in main.py style")
        return True
        
    except Exception as e:
        print(f"❌ Error testing main.py integration: {e}")
        return False

def main():
    """Run all tests."""
    print("🧪 Testing Splunk Integration for Edge Endpoint")
    print("=" * 50)
    
    tests = [
        test_splunk_handler,
        test_loghelper,
        test_environment_variables,
        test_integration
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test {test.__name__} failed with exception: {e}")
            results.append(False)
    
    print("\n" + "=" * 50)
    print("📊 Test Results:")
    print(f"✅ Passed: {sum(results)}/{len(results)}")
    print(f"❌ Failed: {len(results) - sum(results)}/{len(results)}")
    
    if all(results):
        print("\n🎉 All tests passed! Splunk integration is working correctly.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    exit(main())

