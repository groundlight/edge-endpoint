import subprocess

import boto3
import pulumi
import pulumi_aws as aws

config = pulumi.Config("ee-cicd")
instance_type = config.require("instanceType")
stackname = pulumi.get_stack()

# We're creating an "edge endpoint under test" (eeut)

# Find network resources we need.
eeut_sg = aws.ec2.get_security_group(filters=[{
    "name": "tag:Name",
    "values": ["eeut-sg"]
}])
subnet = aws.ec2.get_subnet(filters=[{
    "name": "tag:Name",
    "values": ["cicd-subnet"]
}])

def get_instance_profile_by_tag(tag_key: str, tag_value: str) -> str:
    """Fetches the instance profile name by tag.
    Pulumi should do this, but their get_instance_profile doesn't support filtering.
    """
    iam_client = boto3.client("iam")
    paginator = iam_client.get_paginator("list_instance_profiles")
    
    for page in paginator.paginate():
        for profile in page["InstanceProfiles"]:
            # Check if the profile has the desired tag
            tags = iam_client.list_instance_profile_tags(InstanceProfileName=profile["InstanceProfileName"])
            for tag in tags["Tags"]:
                if tag["Key"] == tag_key and tag["Value"] == tag_value:
                    return profile["InstanceProfileName"]
    raise ValueError(f"No instance profile found with tag {tag_key}: {tag_value}")

def get_target_commit() -> str:
    """Gets the target commit hash."""
    target_commit = config.require("targetCommit")
    if target_commit == "main":
        target_commit = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
    print(f"Using target commit {target_commit}")
    return target_commit

def load_user_data_script() -> str:
    """Loads and customizes the user data script for the instance, which is used to install 
    everything on the instance."""
    with open('../bin/install-on-ubuntu.sh', 'r') as file:
        user_data_script0 = file.read()
    
    # Do all synchronous replacements first
    target_commit = get_target_commit()
    user_data_script1 = user_data_script0.replace("__EE_COMMIT_HASH__", target_commit)
    
    # Apply image tag replacement (also synchronous)
    image_tag = config.get("eeImageTag") or "release"
    user_data_script2 = user_data_script1.replace("__EEIMAGETAG__", image_tag)
    
    # Apply API token replacement as the final async transformation
    api_token = config.require_secret("groundlightApiToken")
    final_script = api_token.apply(
        lambda token: user_data_script2.replace("__GROUNDLIGHTAPITOKEN__", token)
    )
    
    return final_script

instance_profile_name = get_instance_profile_by_tag("Name", "edge-device-instance-profile")

eeut_instance = aws.ec2.Instance("ee-cicd-instance",
    instance_type=instance_type,
    ami="ami-0d2047d61ff42e139",  # Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.5 (Ubuntu 22.04) x86/64
    key_name="ghar2eeut",
    vpc_security_group_ids=[eeut_sg.id],
    subnet_id=subnet.id,
    user_data=load_user_data_script(),
    associate_public_ip_address=True,
    iam_instance_profile=instance_profile_name,
    root_block_device={
        "volume_size": 100,
        "volume_type": "gp3",
    },
    tags={
        "Name": f"eeut-{stackname}",
    },
)

pulumi.export("eeut_instance_id", eeut_instance.id)
pulumi.export("eeut_private_ip", eeut_instance.private_ip)
