"""
Fabric tools to connect to the EEUT and see how it's doing.
"""
from functools import lru_cache
from typing import Callable
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

def which_status_file(conn: Connection) -> str:
    """Returns the name of the status file if it exists, or None if it doesn't."""
    with conn.cd("/opt/groundlight/ee-install-status"):
        if check_for_file(conn, "installing"):
            return "installing"
        if check_for_file(conn, "success"):
            return "success"
        if check_for_file(conn, "failed"):
            return "failed"
        return None

def wait_for_any_status(conn: Connection, wait_minutes: int = 10) -> str:
    """Waits for the EEUT to begin setup.  This is a brand new sleepy server
    rubbing its eyes and waking up.  Give it a bit to start doing something.
    """
    start_time = time.time()
    while time.time() - start_time < 60 * wait_minutes:
        try:
            status_file = which_status_file(conn)
            if status_file:
                return status_file
            else:
                print("No status file found yet.")
        except Exception as e:
            print(f"Still unable to check status file: {e}")
        time.sleep(2)
    raise RuntimeError(f"No status file found after {wait_minutes} minutes.")

def eesetup_installing(conn: Connection) -> bool:
    """Checks if the EEUT is still installing."""
    if check_for_file(conn, "installing"):
        return True

def eesetup_success(conn: Connection) -> bool:
    """Checks if the EEUT installation succeeded."""
    return check_for_file(conn, "success")

@task
def wait_for_ee_setup(c, wait_minutes: int = 10):
    """Waits for the EEUT to finish setup.  If it fails, prints the log."""
    # TODO: Consider refactoring this to use wait_for_condition.
    conn = connect_server()
    status_file = wait_for_any_status(conn, wait_minutes=3)
    with conn.cd(f"/opt/groundlight/ee-install-status"):
        conn.run(f"ls -alh")  # just to see what's in there
        # There are three possible files here:
        # - installing:  still installing
        # - success:  installed successfully
        # - failed:  installation failed
        start_time = time.time()
        while time.time() - start_time < 60 * wait_minutes:
            if check_for_file(conn, "success"):
                print("EE installed successfully.")
                return
            if check_for_file(conn, "failed"):
                print("EE installation failed.  Printing complete log...")
                conn.run("cat /var/log/cloud-init-output.log")
                raise RuntimeError("EE installation failed.")
            if not check_for_file(conn, "installing"):
                print(f"No 'installing' status - maybe cloud-init never ran?")
                raise RuntimeError("EE installation never started.")
            else:
                print(f"EE still installing after {int(time.time() - start_time)} seconds.")
            time.sleep(10)
        raise RuntimeError(f"EE installation check timed out after {wait_minutes} minutes.")


def wait_for_condition(conn: Connection, condition: Callable[[Connection], bool], wait_minutes: int = 10) -> bool:
    """Waits for a condition to be true.  Returns True if the condition is true, False otherwise."""
    start_time = time.time()
    name = condition.__name__
    while time.time() - start_time < 60 * wait_minutes:
        try:
            if condition(conn):
                print(f"Condition {name} is true.")
                return True
            else:
                print(f"Condition {name} is false.")
        except Exception as e:
            print(f"Condition {name} failed: {e}")
        time.sleep(2)
    print(f"Condition {name} timed out after {wait_minutes} minutes.")
    return False


@task
def check_k8_deployments(c):
    """Checks that the edge-endpoint deployment goes online.
    """
    conn = connect_server()
    def can_run_kubectl(conn: Connection) -> bool:  
        conn.run("kubectl get pods")  # If this works at all, we're happy
        return True
    if not wait_for_condition(conn, can_run_kubectl):
        raise RuntimeError("Failed to run kubectl.")
    def see_deployments(conn: Connection) -> bool:
        out = conn.run("kubectl get deployments")
        # Need to see the edge-endpoint deployment  
        return "edge-endpoint" in out.stdout
    if not wait_for_condition(conn, see_deployments):
        conn.run("kubectl get all -A")
        raise RuntimeError("Failed to see edge-endpoint deployment.")
    def edge_endpoint_ready(conn: Connection) -> bool:
        out = conn.run("kubectl get deployments edge-endpoint")
        return "1/1" in out.stdout
    if not wait_for_condition(conn, edge_endpoint_ready):
        conn.run("kubectl get deployments edge-endpoint -o yaml")
        conn.run("kubectl describe deployments edge-endpoint")
        conn.run("kubectl logs deployment/edge-endpoint")
        raise RuntimeError("Failed to see edge-endpoint deployment ready.")


