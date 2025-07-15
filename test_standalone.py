#!/usr/bin/env python3
"""
Test the standalone Bluetti implementation
"""

import time
import logging
from bluetti_standalone import create_client

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_standalone():
    """Test the standalone implementation"""
    
    MAC_ADDRESS = "XX:XX:XX:XX:XX:XX"   ###  <---  CHANGE THIS TO YOUR BLUETTI MAC ADDRESS
    
    print("=== Testing Standalone Bluetti Implementation ===")
    print(f"MAC Address: {MAC_ADDRESS}")
    
    # Create client
    client = create_client(MAC_ADDRESS, logger)
    
    try:
        # Start client
        print("1. Starting client...")
        client.start()
        time.sleep(1)
        
        # Connect
        print("2. Connecting...")
        if client.connect():
            print("✓ Connected successfully")
            
            # Poll data
            print("3. Polling data...")
            data = client.poll_data()
            
            if data:
                print(f"✓ Got {len(data)} data fields")
                
                # Show key fields
                key_fields = ['device_type', 'total_battery_percent', 'ac_output_power', 
                             'ac_output_on', 'ups_mode', 'battery_range_start', 'battery_range_end']
                
                for field in key_fields:
                    if field in data:
                        print(f"  {field}: {data[field]}")
                        
                # Show pack data
                for pack_num in [2, 4]:
                    pack_key = f'pack_{pack_num}_battery_percent'
                    if pack_key in data:
                        print(f"  Pack {pack_num} battery: {data[pack_key]}%")
                        
            else:
                print("⚠ No data received")
                
            # Test command
            print("4. Testing command...")
            success = client.send_command(3001, 2)  # Set UPS mode to PV Priority
            if success:
                print("✓ Command sent successfully")
            else:
                print("⚠ Command failed")
                
        else:
            print("✗ Connection failed")
            
    except Exception as e:
        print(f"✗ Error: {e}")
        
    finally:
        print("5. Cleaning up...")
        client.stop()
        print("✓ Client stopped")

if __name__ == "__main__":
    test_standalone()
