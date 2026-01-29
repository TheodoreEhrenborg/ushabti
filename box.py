#!/usr/bin/env python3
"""
Secure Docker sandbox runner.
Runs commands in an Ubuntu container with pre-configured volume mounts only.
"""
import subprocess
import sys
import json
from pathlib import Path


CONTAINER_NAME = "box-sandbox"
IMAGE_NAME = "ubuntu:latest"
CONFIG_DIR = Path.home() / ".config" / "box"
ALLOWED_DIRS_FILE = CONFIG_DIR / "allowed_dirs"


def read_allowed_dirs():
    """Read allowed directories from config file."""
    if not ALLOWED_DIRS_FILE.exists():
        print(f"Error: Config file not found: {ALLOWED_DIRS_FILE}", file=sys.stderr)
        print("Create it with one directory path per line.", file=sys.stderr)
        sys.exit(1)

    dirs = []
    with open(ALLOWED_DIRS_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                path = Path(line).resolve()
                if not path.exists():
                    print(f"Warning: Directory does not exist: {path}", file=sys.stderr)
                dirs.append(str(path))

    return dirs


def get_container_status():
    """Check if container exists and its status."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format={{.State.Status}}", CONTAINER_NAME],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            return result.stdout.strip()  # running, exited, etc.
        return None  # Container doesn't exist
    except Exception as e:
        print(f"Error checking container status: {e}", file=sys.stderr)
        sys.exit(1)


def get_container_mounts():
    """Get current mounts of the container to verify they match config."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format={{json .Mounts}}", CONTAINER_NAME],
            capture_output=True,
            text=True,
            check=True
        )
        mounts = json.loads(result.stdout)
        return {m["Source"]: m["Destination"] for m in mounts if m.get("Type") == "bind"}
    except Exception:
        return {}


def create_container(allowed_dirs):
    """Create a new container with the specified volume mounts."""
    print(f"Creating container '{CONTAINER_NAME}'...")

    # Build volume arguments - each dir mounted to same path in container
    volume_args = []
    for dir_path in allowed_dirs:
        volume_args.extend(["-v", f"{dir_path}:{dir_path}:rw"])

    cmd = [
        "docker", "run",
        "-d",  # Detached
        "--name", CONTAINER_NAME,
        "--network", "none",  # No network access for security
        "--security-opt", "no-new-privileges",  # Prevent privilege escalation
        "--cap-drop", "ALL",  # Drop all capabilities
        "--cap-add", "CHOWN",  # Add back minimal necessary capabilities
        "--cap-add", "DAC_OVERRIDE",
        "--cap-add", "FOWNER",
        "--cap-add", "SETGID",
        "--cap-add", "SETUID",
        *volume_args,
        IMAGE_NAME,
        "sleep", "infinity"  # Keep container running
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"Container '{CONTAINER_NAME}' created successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error creating container: {e.stderr.decode()}", file=sys.stderr)
        sys.exit(1)


def start_container():
    """Start an existing stopped container."""
    print(f"Starting container '{CONTAINER_NAME}'...")
    try:
        subprocess.run(["docker", "start", CONTAINER_NAME], check=True, capture_output=True)
        print(f"Container '{CONTAINER_NAME}' started.")
    except subprocess.CalledProcessError as e:
        print(f"Error starting container: {e.stderr.decode()}", file=sys.stderr)
        sys.exit(1)


def verify_container_config(allowed_dirs):
    """Verify that container mounts match the current config."""
    current_mounts = get_container_mounts()
    expected_mounts = {d: d for d in allowed_dirs}

    if current_mounts != expected_mounts:
        print("Error: Container mounts don't match current config.", file=sys.stderr)
        print(f"Expected: {expected_mounts}", file=sys.stderr)
        print(f"Current: {current_mounts}", file=sys.stderr)
        print(f"Delete the container to recreate: docker rm -f {CONTAINER_NAME}", file=sys.stderr)
        sys.exit(1)


def run_command_in_container(command_args):
    """Execute command in the container."""
    if not command_args:
        print("Error: No command specified", file=sys.stderr)
        sys.exit(1)

    # Use docker exec with the command args directly (no shell interpretation)
    cmd = ["docker", "exec", "-i", CONTAINER_NAME] + command_args

    try:
        result = subprocess.run(cmd, check=False)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"Error executing command: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Usage: box.py <command> [args...]", file=sys.stderr)
        print(f"Example: box.py ls -la", file=sys.stderr)
        sys.exit(1)

    # Read configuration
    allowed_dirs = read_allowed_dirs()
    if not allowed_dirs:
        print("Error: No directories configured in allowed_dirs", file=sys.stderr)
        sys.exit(1)

    print(f"Allowed directories: {', '.join(allowed_dirs)}")

    # Check container status
    status = get_container_status()

    if status is None:
        # Container doesn't exist - create it
        create_container(allowed_dirs)
    elif status == "exited":
        # Container exists but is stopped - verify config and start
        verify_container_config(allowed_dirs)
        start_container()
    elif status == "running":
        # Container is running - verify config
        verify_container_config(allowed_dirs)
        print(f"Using existing container '{CONTAINER_NAME}'")
    else:
        print(f"Error: Container in unexpected state: {status}", file=sys.stderr)
        sys.exit(1)

    # Run the command
    command_args = sys.argv[1:]
    print(f"Running: {' '.join(command_args)}")
    run_command_in_container(command_args)


if __name__ == "__main__":
    main()
