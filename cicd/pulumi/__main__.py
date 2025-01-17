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

with open('../bin/firstrun-ubuntu.sh', 'r') as file:
    # Load the script that installs everything on the instance
    user_data_script = file.read()

eeut_instance = aws.ec2.Instance("ee-cicd-instance",
    instance_type=instance_type,
    ami="ami-0d2047d61ff42e139",  # Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.5 (Ubuntu 22.04) x86/64
    key_name=None,  # can we leave this out?
    vpc_security_group_ids=[eeut_sg.id],
    subnet_id=subnet.id,
    user_data=user_data_script,
    tags={
        "Name": f"ee-cicd-{stackname}",
    }
)

pulumi.export("eeut_instance_id", eeut_instance.id)
