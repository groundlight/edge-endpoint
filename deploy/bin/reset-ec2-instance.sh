#!/bin/bash

# Step 1: Retrieve the Instance Details
INSTANCE_ID="i-0ee2c13effe2b61e9"
aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0]' > instance_details.json

# Step 2: Terminate the Instance
aws ec2 terminate-instances --instance-ids $INSTANCE_ID

# Step 3: Extract Details from JSON and Create a New Identical Instance
AMI_ID=$(jq -r '.ImageId' instance_details.json)
INSTANCE_TYPE=$(jq -r '.InstanceType' instance_details.json)
KEY_NAME=$(jq -r '.KeyName' instance_details.json)
SECURITY_GROUP_ID=$(jq -r '.SecurityGroups[0].GroupId' instance_details.json)
SUBNET_ID=$(jq -r '.SubnetId' instance_details.json)
INSTANCE_NAME=$(jq -r '.Tags[] | select(.Key=="Name") | .Value' instance_details.json)

# Create new instance and get its ID
NEW_INSTANCE_ID=$(aws ec2 run-instances --image-id $AMI_ID --count 1 --instance-type $INSTANCE_TYPE --key-name $KEY_NAME --security-group-ids $SECURITY_GROUP_ID --subnet-id $SUBNET_ID --query 'Instances[0].InstanceId' --output text)

# Step 4: Apply the Name Tag to the New Instance
aws ec2 create-tags --resources $NEW_INSTANCE_ID --tags Key=Name,Value="$INSTANCE_NAME"

# Clean up
rm instance_details.json

echo "The operation is complete. An identical instance has been created and is initializing."
