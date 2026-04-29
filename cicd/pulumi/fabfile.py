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

def get_eeut_ip() -> str:
    """Gets the EEUT's IP address from Pulumi."""
    return local("pulumi stack output eeut_private_ip", hide=True).stdout.strip()

def connect_server() -> Connection:
    """Connects to the EEUT, using the private key stored in AWS Secrets Manager."""
    ip = get_eeut_ip()
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


class InfrequentUpdater:
    """Displays messages as they happen, but don't repeat the same message too often."""

    def __init__(self, how_often: float = 30):
        self.how_often = how_often
        self.last_update = 0
        self.last_msg = ""

    def maybe_update(self, msg: str):
        """Displays a message if it's been long enough since the last message, and the same.
        New messages are always displayed."""
        if msg == self.last_msg:
            if time.time() - self.last_update < self.how_often:
                return
        print(msg)
        self.last_msg = msg
        self.last_update = time.time()

@task
def connect(c, patience: int = 30):
    """Just connect to a server to validate connection is working.

    Args:
        patience (int): Number of seconds to keep retrying for.
    """
    print("Fab/fabric is working.  Connecting to server...")
    updater = InfrequentUpdater()
    start_time = time.time()
    while time.time() - start_time < patience:
        try:
            connect_server()
            print("Successfully connected to server.")
            return
        except Exception as e:
            updater.maybe_update(f"Failed to connect to server: {e}")
            time.sleep(3)
    raise RuntimeError(f"Failed to connect to server after {patience} seconds.")


class StatusFileChecker(InfrequentUpdater):
    """Encapsulates all the logic for checking status files."""

    def __init__(self, conn: Connection, path: str):
        super().__init__()
        self.conn = conn
        self.path = path
        self.last_update = 0
        self.last_msg = ""

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
                self.maybe_update(f"Found status file: {status_file}")
                if status_file:
                    return status_file
            except Exception as e:
                self.maybe_update(f"Unable to check status file: {e}")
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
            self.maybe_update(f"Waiting for success or failed status file to appear...")
            time.sleep(2)
        raise RuntimeError(f"EE installation check timed out after {wait_minutes} minutes.")

@task
def wait_for_ee_setup(c, wait_minutes: int = 10):
    """Waits for the EEUT to finish setup.  If it fails, prints the log."""
    conn = connect_server()
    checker = StatusFileChecker(conn, "/opt/groundlight/ee-install-status")
    print("Waiting for any status file to appear...")
    checker.wait_for_any_status(wait_minutes=wait_minutes/2)
    print("Waiting for success status file to appear...")
    checker.wait_for_success(wait_minutes=wait_minutes)
    print("EE installation complete.")


def wait_for_condition(conn: Connection, condition: Callable[[Connection], bool], wait_minutes: int = 10) -> bool:
    """Waits for a condition to be true.  Returns True if the condition is true, False otherwise."""
    updater = InfrequentUpdater()
    start_time = time.time()
    name = condition.__name__
    while time.time() - start_time < 60 * wait_minutes:
        try:
            if condition(conn):
                print(f"Condition {name} is true.  Moving on.")
                return True
            else:
                updater.maybe_update(f"Condition {name} is false.  Still waiting...")
        except Exception as e:
            updater.maybe_update(f"Condition {name} failed: {e}.  Will retry...")
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

@task 
def check_server_port(c):
    """Checks that the server is listening on the service ports."""
    # First check that it's visible from the EEUT's localhost
    conn = connect_server()
    for port in [30101, 30143]:
        print(f"Checking that the server is listening on port {port} from the EEUT's localhost...")
        conn.run(f"nc -zv localhost {port}")

    print(f"Checking that HTTP (30101) is reachable from here...")
    eeut_ip = get_eeut_ip()
    local(f"nc -zv {eeut_ip} 30101")

    # We don't check 30143 from outside because the CICD runner might not have
    # permissions to open that port in the AWS security group.
    # Instead, we verify HTTPS internally on the host.
    print(f"Verifying HTTPS endpoint internally...")
    conn.run("curl -vk https://localhost:30143/health/live")

    print("Server port check complete.")


@task
def diagnose_inference(c):
    """Dump everything an oncall would need to triage why an inference pod
    isn't becoming Ready. Safe to call even if no detector is configured.
    """
    conn = connect_server()
    print("=== nodes ===")
    conn.run("kubectl get nodes -o wide", warn=True)
    print("=== all pods in edge namespace ===")
    conn.run("kubectl get pods -n edge -o wide", warn=True)
    print("=== all deployments in edge namespace ===")
    conn.run("kubectl get deployments -n edge", warn=True)
    print("=== events in edge namespace (last 30) ===")
    conn.run("kubectl get events -n edge --sort-by=.lastTimestamp | tail -n 30", warn=True)
    print("=== inferencemodel deployments (describe) ===")
    conn.run("kubectl describe deployments -n edge -l app.kubernetes.io/component=inferencemodel "
             "2>/dev/null || kubectl get deployments -n edge -o name | grep inferencemodel "
             "| xargs -I{} kubectl describe {} -n edge", warn=True)
    print("=== inferencemodel pods (describe) ===")
    conn.run("kubectl get pods -n edge -o name | grep inferencemodel "
             "| xargs -I{} kubectl describe {} -n edge", warn=True)
    print("=== edge-endpoint model_updater logs (last 200) ===")
    conn.run("kubectl logs deployment/edge-endpoint -c inference-model-updater "
             "-n edge --tail=200", warn=True)
    print("=== edge-endpoint logs (last 200) ===")
    conn.run("kubectl logs deployment/edge-endpoint -c edge-endpoint -n edge --tail=200", warn=True)


@task
def check_gpu(c, detector_id):
    """Verify nvidia-smi works on the host AND the primary inference pod for
    `detector_id` has a GPU resource allocated and visible inside the container.
    Catches the case where everything else is fine but inference silently
    fell back to CPU.
    """
    conn = connect_server()
    print("Checking host-level NVIDIA driver...")
    conn.run("nvidia-smi --query-gpu=name,driver_version --format=csv")

    # Inference pods are labeled `app=inference-server,instance=instance-<detector_id>-primary`.
    # Per app/core/kubernetes_management.py:91, the instance label preserves the original
    # detector ID (case + underscores intact) — unlike the deployment name which lowercases
    # and dashifies it.
    instance = f"instance-{detector_id}-primary"
    pod_label = f"app=inference-server,instance={instance}"
    print(f"Looking up inference pod with label {pod_label}...")
    pod = conn.run(
        f"kubectl get pod -l '{pod_label}' -n edge "
        "-o jsonpath='{.items[0].metadata.name}'", hide=True,
    ).stdout.strip()
    if not pod:
        raise RuntimeError(f"No pod found with label {pod_label}")
    print(f"Found inference pod: {pod}")

    # The chart relies on `runtimeClassName: nvidia` (set when inferenceFlavor=gpu) for GPU
    # access, not on a `nvidia.com/gpu` resource limit. Verify the runtime class first, then
    # that the GPU is actually visible inside the running container.
    print("Verifying pod uses the nvidia runtime class...")
    runtime = conn.run(
        f"kubectl get pod {pod} -n edge -o jsonpath='{{.spec.runtimeClassName}}'",
        hide=True,
    ).stdout.strip()
    if runtime != "nvidia":
        conn.run(f"kubectl describe pod {pod} -n edge")
        raise RuntimeError(
            f"Inference pod {pod} runtimeClassName is '{runtime}', expected 'nvidia'. "
            "Inference will run on CPU!"
        )
    print(f"Pod {pod} runtimeClassName=nvidia.")

    print("Verifying GPU is visible inside the container (nvidia-smi -L)...")
    conn.run(f"kubectl exec -n edge {pod} -- nvidia-smi -L")
    print("GPU check passed.")


@task
def full_check(c):
    """Runs all the checks in order."""
    connect(c)
    wait_for_ee_setup(c)
    check_k8_deployments(c)
    check_server_port(c)


@task
def shutdown_instance(c):
    """Shuts down the EEUT instance."""
    conn = connect_server()
    # Tell it to shutdown in 2 minutes, so it doesn't die while we're still connected.
    conn.run("sudo shutdown +2")
    print("Instance will shutdown in 2 minutes.  Disconnecting...")