#!/usr/bin/env python3
"""
MCP Filesystem Server wrapper that IGNORES the roots protocol.

This wrapper spawns the standard @modelcontextprotocol/server-filesystem
but intercepts and discards any roots-related messages from the client,
forcing the server to use only the command-line allowed directories.

This is needed because Claude Code SDK sends roots that override our args.

Usage:
    python filesystem_no_roots.py /path/to/dir1 /path/to/dir2
"""

import asyncio
import json
import sys


async def main():
    # Get allowed directories from command line args
    allowed_dirs = sys.argv[1:] if len(sys.argv) > 1 else []

    if not allowed_dirs:
        print("Error: No allowed directories specified", file=sys.stderr)
        sys.exit(1)

    print(f"[filesystem_no_roots] Starting with dirs: {allowed_dirs}", file=sys.stderr)
    print("[filesystem_no_roots] Roots protocol will be IGNORED", file=sys.stderr)

    # Build command to spawn the real filesystem server
    cmd = ["npx", "-y", "@modelcontextprotocol/server-filesystem"] + allowed_dirs

    # Start the real filesystem server
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def forward_stderr():
        """Forward stderr from real server."""
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            print(f"[fs-server] {line.decode().rstrip()}", file=sys.stderr)

    async def forward_stdin():
        """Forward stdin to server, filtering out roots-related messages."""
        # Read from our stdin
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line = await reader.readline()
            if not line:
                print("[filesystem_no_roots] EOF on stdin", file=sys.stderr)
                process.stdin.close()
                break

            try:
                msg = json.loads(line.decode())
                method = msg.get("method", "")

                # Filter out roots-related messages
                if method == "notifications/roots/list_changed":
                    print(f"[filesystem_no_roots] BLOCKED: {method}", file=sys.stderr)
                    continue  # Don't forward this message

                if method == "roots/list":
                    print(f"[filesystem_no_roots] BLOCKED: {method}", file=sys.stderr)
                    # Send empty response to indicate no roots support
                    msg_id = msg.get("id")
                    if msg_id is not None:
                        response = {"jsonrpc": "2.0", "id": msg_id, "result": {"roots": []}}
                        sys.stdout.buffer.write((json.dumps(response) + "\n").encode())
                        sys.stdout.buffer.flush()
                    continue

                # CRITICAL: Remove roots capability from client's initialize request
                # This prevents the server from expecting/using roots protocol
                if method == "initialize":
                    params = msg.get("params", {})
                    caps = params.get("capabilities", {})
                    if "roots" in caps:
                        print("[filesystem_no_roots] REMOVING roots from client capabilities", file=sys.stderr)
                        del caps["roots"]
                        # Update the message with modified capabilities
                        line = (json.dumps(msg) + "\n").encode()

            except json.JSONDecodeError:
                pass  # Forward non-JSON lines as-is

            # Forward the message to the real server
            process.stdin.write(line)
            await process.stdin.drain()

    async def forward_stdout():
        """Forward stdout from server, modifying capabilities to remove roots support."""
        while True:
            line = await process.stdout.readline()
            if not line:
                print("[filesystem_no_roots] EOF on stdout", file=sys.stderr)
                break

            try:
                msg = json.loads(line.decode())

                # Modify initialize response to REMOVE roots capability from server
                # This prevents the client from sending roots which would override our args
                if "result" in msg and "capabilities" in msg.get("result", {}):
                    caps = msg["result"]["capabilities"]
                    print(f"[filesystem_no_roots] Original server caps: {list(caps.keys())}", file=sys.stderr)

                    # Remove roots capability so client won't try to use it
                    if "roots" in caps:
                        del caps["roots"]
                        print("[filesystem_no_roots] REMOVED roots capability from server response", file=sys.stderr)

                    # Reserialize the modified message
                    line = (json.dumps(msg) + "\n").encode()
                    print(f"[filesystem_no_roots] Modified server caps: {list(caps.keys())}", file=sys.stderr)

                # Check for errors related to roots
                if "error" in msg:
                    print(f"[filesystem_no_roots] Server error: {msg['error']}", file=sys.stderr)

            except json.JSONDecodeError:
                pass

            # Forward to client (possibly modified)
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()

    # Run all tasks
    try:
        await asyncio.gather(
            forward_stderr(),
            forward_stdin(),
            forward_stdout(),
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"[filesystem_no_roots] Error: {e}", file=sys.stderr)
        raise
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()


if __name__ == "__main__":
    asyncio.run(main())
