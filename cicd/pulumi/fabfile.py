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


class StatusFileChecker:
    """Encapsulates all the logic for checking status files."""

    def __init__(self, conn: Connection, path: str):
        self.conn = conn
        self.path = path

    def check_for_file(self, name: str) -> bool:
        """Checks if a file is present in the EEUT's install status directory."""
        with self.conn.cd(self.path):
            result = self.conn.run(f"test -f {name}", warn=True)
            return result.ok
    
    def which_status_file(self) -> str:
        """Returns the name of the status file if it exists, or None if it doesn't."""
        with self.conn.cd(self.path):
            if self.check_for_file("installing"):
                return "installing"
            if self.check_for_file("success"):
            return "success"
        if self.check_for_file("failed"):
            return "failed"
        return None

    def wait_for_any_status(self, wait_minutes: int = 10) -> str:
        """Waits for the EEUT to begin setup.  This is a brand new sleepy server
        rubbing its eyes and waking up.  Give it a bit to start doing something.
        """
        start_time = time.time()
        while time.time() - start_time < 60 * wait_minutes:
            try:
                status_file = self.which_status_file()
                if status_file:
                return status_file
            else:
                print("No status file found yet.")
            except Exception as e:
                print(f"Still unable to check status file: {e}")
            time.sleep(2)
        raise RuntimeError(f"No status file found after {wait_minutes} minutes.")

    def wait_for_success(self, wait_minutes: int = 10) -> bool:
        """Waits for the EEUT to finish setup.  If it fails, prints the log."""
        start_time = time.time()
        while time.time() - start_time < 60 * wait_minutes:
            if self.check_for_file("success"):
                return True
            if self.check_for_file("failed"):
                print("EE installation failed.  Printing complete log...")
                self.conn.run("cat /var/log/cloud-init-output.log")
                raise RuntimeError("EE installation failed.")
            time.sleep(2)
        raise RuntimeError(f"EE installation check timed out after {wait_minutes} minutes.")

@task
def wait_for_ee_setup(c, wait_minutes: int = 10):
    """Waits for the EEUT to finish setup.  If it fails, prints the log."""
    conn = connect_server()
    checker = StatusFileChecker(conn, "/opt/groundlight/ee-install-status")
    checker.wait_for_any_status(wait_minutes=wait_minutes/2)
    checker.wait_for_success(wait_minutes=wait_minutes)


def wait_for_condition(conn: Connection, condition: Callable[[Connection], bool], wait_minutes: int = 10) -> bool:
    """Waits for a condition to be true.  Returns True if the condition is true, False otherwise."""
    start_time = time.time()
    name = condition.__name__
    while time.time() - start_time < 60 * wait_minutes:
        try:
            if condition(conn):
                print(f"Condition {name} is true.  Moving on.")
                return True
            else:
                print(f"Condition {name} is false.  Still waiting...")
        except Exception as e:
            print(f"Condition {name} failed: {e}.  Will retry...")
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
        out = conn.run("kubectl get deployments", hide=True)
        # Need to see the edge-endpoint deployment  
        return "edge-endpoint" in out.stdout
    if not wait_for_condition(conn, see_deployments):
        conn.run("kubectl get all -A", hide=True)
        raise RuntimeError("Failed to see edge-endpoint deployment.")
    def edge_endpoint_ready(conn: Connection) -> bool:
        out = conn.run("kubectl get deployments edge-endpoint", hide=True)
        return "1/1" in out.stdout
    if not wait_for_condition(conn, edge_endpoint_ready):
        conn.run("kubectl get deployments edge-endpoint -o yaml")
        conn.run("kubectl describe deployments edge-endpoint")
        conn.run("kubectl logs deployment/edge-endpoint")
        raise RuntimeError("Failed to see edge-endpoint deployment ready.")




