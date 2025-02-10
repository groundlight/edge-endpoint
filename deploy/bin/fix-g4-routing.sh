#!/bin/bash

set -e  # Exit on error
set -o pipefail

# Define the netplan config file
NETPLAN_CONFIG="/etc/netplan/60-ens5.yaml"

# Get the primary IP of the system
PRIMARY_IP=$(ip route get 1.1.1.1 | awk '{print $7}')

# Check if the problematic rule exists
if ip rule show | grep -q "from $PRIMARY_IP lookup 1000"; then
    echo "Removing problematic routing rule..."
    sudo ip rule delete from "$PRIMARY_IP" table 1000
else
    echo "No problematic rule found, exiting..."
    exit 0
fi

# Backup the netplan config before modifying
if [[ -f "$NETPLAN_CONFIG" ]]; then
    echo "Backing up netplan configuration to $NETPLAN_CONFIG.bak"
    sudo cp "$NETPLAN_CONFIG" "$NETPLAN_CONFIG.bak"
else
    echo "Warning: Netplan config file not found at $NETPLAN_CONFIG"
    exit 1
fi

# Remove the routing-policy and table 1000 from netplan
echo "Updating netplan configuration..."
sudo sed -i '/^ *routes:/,/table: 1000/d' "$NETPLAN_CONFIG"
sudo sed -i '/^ *routing-policy:/,/table: 1000/d' "$NETPLAN_CONFIG"

# Apply the updated netplan configuration
echo "Applying netplan changes..."
sudo netplan apply

# Restart systemd-networkd
echo "Restarting systemd-networkd..."
sudo systemctl restart systemd-networkd

# Verify that the rule has been removed
echo "Verifying that the rule has been removed..."
if ip rule show | grep -q "from $PRIMARY_IP table 1000"; then
    echo "❌ Error: The routing rule is still present."
    exit 1
else
    echo "✅ Success: The routing rule has been removed."
fi

echo "System networking has been fixed."
