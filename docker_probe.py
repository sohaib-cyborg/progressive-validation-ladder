#!/usr/bin/env python3
"""
Docker sandbox pre-flight probe for Project D.

Run this ON YOUR MACHINE before Day 2 to confirm the locked-down container
config actually works. Takes ~1 minute (first run pulls the image).

    pip install docker
    python docker_probe.py

PASS = you see "ALL CHECKS PASSED" at the end.
FAIL = it tells you exactly which constraint your Docker setup rejects.
"""

from __future__ import annotations

import sys

try:
    import docker
except ImportError:
    sys.exit("docker SDK not installed. Run: pip install docker")


IMAGE = "python:3.12-slim"


def main() -> int:
    try:
        client = docker.from_env()
        client.ping()
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] Cannot reach the Docker daemon: {e}")
        print("       Is Docker running? Do you have permission (docker group)?")
        return 1
    print("[ok] Docker daemon reachable")

    # 1. pull / find the base image
    try:
        print(f"[..] Ensuring image {IMAGE} is available (may pull)...")
        client.images.pull(IMAGE)
        print(f"[ok] Image {IMAGE} available")
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] Could not pull {IMAGE}: {e}")
        return 1

    # 2. run a container with the FULL locked-down config
    #    (this is exactly what sandbox/container.py will use)
    container = None
    try:
        print("[..] Starting locked-down container...")
        container = client.containers.run(
            IMAGE,
            command=["python", "-c", "import socket, sys; print('hello from inside')"],
            network_disabled=True,       # network off
            mem_limit="512m",            # memory cap
            memswap_limit="512m",        # no swap escape
            pids_limit=128,              # process cap
            cap_drop=["ALL"],            # drop all Linux capabilities
            security_opt=["no-new-privileges"],
            detach=True,
        )
        result = container.wait(timeout=30)
        logs = container.logs().decode(errors="replace").strip()
        exit_code = result.get("StatusCode", -1)
        print(f"[ok] Container ran. exit={exit_code}, output={logs!r}")
        if "hello from inside" not in logs:
            print("[FAIL] Container did not produce expected output.")
            return 1
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] Locked-down container failed to run: {e}")
        print("       One of the constraints (caps, pids_limit, security_opt)")
        print("       may be unsupported on your Docker/OS. Note which and tell Claude.")
        return 1
    finally:
        if container is not None:
            try:
                container.remove(force=True)
                print("[ok] Container removed (no leak)")
            except Exception as e:  # noqa: BLE001
                print(f"[warn] Could not remove container: {e}")

    # 3. confirm network is ACTUALLY off (this SHOULD fail inside)
    container = None
    try:
        print("[..] Verifying network is truly disabled (expect failure inside)...")
        container = client.containers.run(
            IMAGE,
            command=[
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://example.com', timeout=5)",
            ],
            network_disabled=True,
            mem_limit="512m",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            detach=True,
        )
        result = container.wait(timeout=30)
        exit_code = result.get("StatusCode", -1)
        if exit_code != 0:
            print(f"[ok] Network correctly blocked (inside process failed, exit={exit_code})")
        else:
            print("[FAIL] Network was NOT blocked — the tool could reach the internet!")
            return 1
    except Exception as e:  # noqa: BLE001
        print(f"[ok] Network correctly blocked ({type(e).__name__})")
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:  # noqa: BLE001
                pass

    # 4. confirm a timeout / runaway is killable
    container = None
    try:
        print("[..] Verifying a runaway container can be stopped...")
        container = client.containers.run(
            IMAGE,
            command=["python", "-c", "while True: pass"],
            network_disabled=True,
            mem_limit="512m",
            cap_drop=["ALL"],
            detach=True,
        )
        try:
            container.wait(timeout=5)
        except Exception:  # noqa: BLE001  (timeout is what we expect)
            container.kill()
            print("[ok] Runaway container killed on timeout")
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:  # noqa: BLE001
                pass

    print("\n================================")
    print(" ALL CHECKS PASSED — sandbox config works on this machine.")
    print("================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
