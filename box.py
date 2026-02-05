#!/usr/bin/env python3
"""
Secure Docker sandbox runner.
Runs commands in an Ubuntu container with pre-configured volume mounts only.
"""

import subprocess
import sys
import json
import hashlib
import yaml
from pathlib import Path


CONFIG_DIR = Path.home() / ".config" / "box"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def read_config():
    """Read configuration from YAML file."""
    if not CONFIG_FILE.exists():
        print(f"Error: Config file not found: {CONFIG_FILE}", file=sys.stderr)
        print("Create a YAML file with format:", file=sys.stderr)
        print("- dir: /path/to/dir", file=sys.stderr)
        print("  image: ubuntu:latest", file=sys.stderr)
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f)

    if not config or not isinstance(config, list):
        print(f"Error: Config must be a list of entries", file=sys.stderr)
        sys.exit(1)

    # Normalize and validate
    entries = []
    for entry in config:
        if not isinstance(entry, dict) or "dir" not in entry:
            print(f"Error: Each entry must have 'dir' field: {entry}", file=sys.stderr)
            sys.exit(1)

        dir_path = Path(entry["dir"]).resolve()
        image = entry.get("image", "ubuntu:latest")

        if not dir_path.exists():
            print(f"Warning: Directory does not exist: {dir_path}", file=sys.stderr)

        entries.append({"dir": str(dir_path), "image": image})

    return entries


def get_container_name(dir_path):
    """Generate a unique container name based on directory path."""
    # Use hash of path for unique container name
    path_hash = hashlib.sha256(dir_path.encode()).hexdigest()[:12]
    return f"box-{path_hash}"


def get_container_status(container_name):
    """Check if container exists and its status."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format={{.State.Status}}", container_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()  # running, exited, etc.
        return None  # Container doesn't exist
    except Exception as e:
        print(f"Error checking container status: {e}", file=sys.stderr)
        sys.exit(1)


def get_container_info(container_name):
    """Get container mounts and image."""
    try:
        result = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            text=True,
            check=True,
        )
        info = json.loads(result.stdout)[0]
        mounts = {
            m["Source"]: m["Destination"]
            for m in info.get("Mounts", [])
            if m.get("Type") == "bind"
        }
        image = info.get("Config", {}).get("Image", "")
        return {"mounts": mounts, "image": image}
    except Exception:
        return {"mounts": {}, "image": ""}


def create_container(container_name, dir_path, image):
    """Create a new container with the specified volume mount."""
    print(f"Creating container '{container_name}'...")

    cmd = [
        "docker",
        "run",
        "-d",  # Detached
        "--name",
        container_name,
        "-v",
        f"{dir_path}:{dir_path}:rw",
        image,
        "sleep",
        "infinity",  # Keep container running
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"Container '{container_name}' created successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error creating container: {e.stderr.decode()}", file=sys.stderr)
        sys.exit(1)


def start_container(container_name):
    """Start an existing stopped container."""
    print(f"Starting container '{container_name}'...")
    try:
        subprocess.run(
            ["docker", "start", container_name], check=True, capture_output=True
        )
        print(f"Container '{container_name}' started.")
    except subprocess.CalledProcessError as e:
        print(f"Error starting container: {e.stderr.decode()}", file=sys.stderr)
        sys.exit(1)


def verify_container_config(container_name, dir_path, image):
    """Verify that container matches the current config. Returns True if valid."""
    info = get_container_info(container_name)
    expected_mounts = {dir_path: dir_path}

    if info["mounts"] != expected_mounts or info["image"] != image:
        print("Container config doesn't match current config.")
        print(f"Expected mounts: {expected_mounts}, image: {image}")
        print(f"Current mounts: {info['mounts']}, image: {info['image']}")
        print(f"Recreating container...")
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name], check=True, capture_output=True
            )
        except subprocess.CalledProcessError as e:
            print(f"Error removing container: {e.stderr.decode()}", file=sys.stderr)
            sys.exit(1)
        return False
    return True


def run_command_in_container(container_name, command_args, workdir=None):
    """Execute command in the container."""
    if not command_args:
        print("Error: No command specified", file=sys.stderr)
        sys.exit(1)

    # Build docker exec command
    # Use -it to allocate pseudo-TTY so Ctrl+C kills the process inside container
    # Wrap command in bash -c to support pipes, redirects, etc.
    cmd = ["docker", "exec", "-it"]
    if workdir:
        cmd.extend(["-w", workdir])
        print(f"Working directory: {workdir}")
    cmd.extend([container_name, "bash", "-c", " ".join(command_args)])

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
    config_entries = read_config()
    if not config_entries:
        print("Error: No directories configured", file=sys.stderr)
        sys.exit(1)

    # Find which config entry matches current directory
    cwd = Path.cwd().resolve()
    matched_entry = None
    workdir = None

    for entry in config_entries:
        entry_path = Path(entry["dir"]).resolve()
        try:
            # Check if cwd is inside or equal to this directory
            cwd.relative_to(entry_path)
            matched_entry = entry
            workdir = str(cwd)
            break
        except ValueError:
            # cwd is not inside this directory
            continue

    if not matched_entry:
        print(f"Error: Current directory {cwd} is not in any configured directory", file=sys.stderr)
        print("Configured directories:", file=sys.stderr)
        for entry in config_entries:
            print(f"  - {entry['dir']} (image: {entry['image']})", file=sys.stderr)
        sys.exit(1)

    dir_path = matched_entry["dir"]
    image = matched_entry["image"]
    container_name = get_container_name(dir_path)

    # Handle special "kill" command to remove container
    if sys.argv[1] == "kill":
        print(f"Killing container '{container_name}' for directory: {dir_path}")
        status = get_container_status(container_name)
        if status is not None:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", container_name], check=True, capture_output=True
                )
                print(f"Container '{container_name}' removed.")
            except subprocess.CalledProcessError as e:
                print(f"Error removing container: {e.stderr.decode()}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Container '{container_name}' does not exist.")
        sys.exit(0)

    print(f"Using directory: {dir_path}")
    print(f"Using image: {image}")
    print(f"Container: {container_name}")

    # Check container status
    status = get_container_status(container_name)

    if status is None:
        # Container doesn't exist - create it
        create_container(container_name, dir_path, image)
    elif status == "exited":
        # Container exists but is stopped - verify config and start
        if verify_container_config(container_name, dir_path, image):
            start_container(container_name)
        else:
            # Config didn't match, container was deleted - recreate
            create_container(container_name, dir_path, image)
    elif status == "running":
        # Container is running - verify config
        if verify_container_config(container_name, dir_path, image):
            print(f"Using existing container '{container_name}'")
        else:
            # Config didn't match, container was deleted - recreate
            create_container(container_name, dir_path, image)
    else:
        print(f"Error: Container in unexpected state: {status}", file=sys.stderr)
        sys.exit(1)

    # Run the command
    command_args = sys.argv[1:]
    print(f"Running: {' '.join(command_args)}")
    run_command_in_container(container_name, command_args, workdir)


if __name__ == "__main__":
    main()
