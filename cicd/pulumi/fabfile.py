"""
Fabric tools to connect to the EEUT and see how it's doing.
"""
from functools import lru_cache
import os
import time
import io

from fabric import task, Connection, Config
from invoke import run as local
import boto3
import paramiko

def fetch_secret(secret_id: str) -> str:
    """Fetches a secret from AWS Secrets Manager."""
    client = boto3.client("secretsmanager", region_name="us-west-2")
    response = client.get_secret_value(SecretId=secret_id)
    return response['SecretString']

def connect_server() -> Connection:
    """Connects to the EEUT looking up its IP address from Pulumi.
    It's saved as an output called "eeut_private_ip" in Pulumi.
    """
    ip_lookup_result = local("pulumi stack output eeut_private_ip")
    ip = ip_lookup_result.stdout.strip()
    try:
        private_key = fetch_secret("ghar2eeut-private-key")
        private_key_file = io.StringIO(private_key)
        key = paramiko.Ed25519Key.from_private_key(private_key_file)
        conn = Connection(
            ip,
            user='ubuntu',
            connect_kwargs={"pkey": key},
        )
        conn.run(f"echo 'Successfully logged in to {ip}'")
        return conn
    except paramiko.ssh_exception.SSHException as e:
        print(f"Failed to connect to {ip}")
        raise


@task
def connect(c, patience: int = 30):
    """Just connect to a server to validate connection is working.

    Args:
        patience (int): Number of seconds to keep retrying for.
    """
    print("Fab/fabric is working.  Connecting to server...")
    start_time = time.time()
    attempt = 1
    while time.time() - start_time < patience:
        try:
            connect_server()
            print(f"Successfully connected to server on attempt {attempt}.")
            return
        except Exception as e:
            print(f"Attempt {attempt} failed to connect to server: {e}")
            time.sleep(3)
            attempt += 1
    raise RuntimeError(f"Failed to connect to server after {patience} seconds.")


def check_for_file(conn: Connection, name: str) -> bool:
    """Checks if a file is present in the EEUT's install status directory."""
    with conn.cd("/opt/groundlight/ee-install-status"):
        result = conn.run(f"test -f {name}", warn=True)
        return result.ok

@task
def wait_for_ee_setup(c, wait_minutes: int = 10):
    """Waits for the EEUT to finish setup.  If it fails, prints the log."""
    conn = connect_server()
    with conn.cd(f"/opt/groundlight/ee-install-status"):
        conn.run(f"ls -alh")
        # There are three possible files here:
        # - installing:  still installing
        # - success:  installed successfully
        # - failed:  installation failed
        start_time = time.time()
        while time.time() - start_time < 60 * wait_minutes:
            if check_for_file(conn, "success"):
                print("EEUT installed successfully.")
                return
            if check_for_file(conn, "failed"):
                print("EEUT installation failed.")
                conn.run("cat /var/log/cloud-init-output.log")
                raise RuntimeError("EEUT installation failed.")
            if not check_for_file(conn, "installing"):
                print(f"No 'installing' status - maybe cloud-init never ran?")
                raise RuntimeError("EEUT installation never started.")
            time.sleep(10)
        raise RuntimeError(f"EEUT still installing after {wait_minutes} minutes.")

@task
def check_k8_deployment(c, deployment_name: str):
    """Checks if a k8 deployment is running. (Not implemented yet.)"""
    # TODO: implement this
    raise NotImplementedError("Not implemented yet.")
