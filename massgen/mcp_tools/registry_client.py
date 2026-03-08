"""
MCP Registry Client

Fetches server metadata (descriptions, versions) from the official
MCP registry at https://registry.modelcontextprotocol.io/v0/servers.

This client is used to enhance the system prompt with descriptions of
MCP servers, helping agents understand what tools are available.
"""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# In-memory cache for registry lookups within a session
# This prevents repeated HTTP requests when building system messages for multiple agents
_SESSION_CACHE: dict[str, Any] = {}

# Flag to track if warmup is in progress (prevent duplicate warmups)
_WARMUP_IN_PROGRESS: bool = False

# NPM packages that are NOT in the public MCP registry.
# Without this skip list, each package triggers a full registry scan (~18 seconds)
# before returning "not found". Maps package name -> fallback description.
_PACKAGES_NOT_IN_REGISTRY: dict[str, str] = {
    # MCP reference implementations (official but not in public registry)
    "@modelcontextprotocol/server-filesystem": "Secure file operations with configurable access controls",
    # Tool wrappers used by MassGen
    "mcpwrapped@1.0.4": "MCP tool wrapper for filtering visible tools",
}


def _description_cache_key(server: dict[str, Any]) -> str:
    """Create a stable cache key for server description lookups.

    Using only server name is too coarse: different configurations can reuse
    the same name and legitimately resolve to different descriptions.
    """
    try:
        payload = json.dumps(server, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        payload = repr(server)
    digest = hashlib.md5(payload.encode("utf-8")).hexdigest()
    return f"desc:{digest}"


def warmup_mcp_registry_cache(config: dict[str, Any] | None = None) -> None:
    """
    Pre-warm the MCP registry cache by fetching descriptions for all servers.

    This function is designed to be called in a background thread when the TUI starts,
    before the user types their first question. By pre-fetching server descriptions,
    the first agent's system message build will be fast (cache hit instead of HTTP lookup).

    The function warms up:
    1. Auto-discovered servers from MCP_SERVER_REGISTRY (context7, brave_search, etc.)
    2. Servers defined in the config's mcp_servers sections

    Args:
        config: Optional MassGen config dict for additional servers.
                If None, only warms up the standard auto-discovery servers.

    Example:
        >>> import threading
        >>> warmup_thread = threading.Thread(target=warmup_mcp_registry_cache, daemon=True)
        >>> warmup_thread.start()
    """
    global _WARMUP_IN_PROGRESS

    if _WARMUP_IN_PROGRESS:
        logger.debug("[MCP Warmup] Warmup already in progress, skipping")
        return

    _WARMUP_IN_PROGRESS = True
    try:
        # Collect all unique MCP servers to warm up
        all_mcp_servers: list[dict[str, Any]] = []
        seen_servers: set = set()

        # 1. Add auto-discovery servers from MCP_SERVER_REGISTRY
        # These are the most common (context7 is always added when auto_discover_custom_tools=True)
        try:
            from massgen.mcp_tools.server_registry import get_auto_discovery_servers

            for server in get_auto_discovery_servers():
                server_name = server.get("name", "")
                if server_name and server_name not in seen_servers:
                    seen_servers.add(server_name)
                    all_mcp_servers.append(server)
        except ImportError:
            logger.debug("[MCP Warmup] Could not import server_registry, skipping auto-discovery servers")

        # 2. Add servers from config (if provided)
        if config:
            agent_configs = config.get("agents", [])
            if not agent_configs and "agent" in config:
                agent_configs = [config["agent"]]

            for agent_data in agent_configs:
                backend_cfg = agent_data.get("backend", {})
                mcp_servers = backend_cfg.get("mcp_servers", [])

                for server in mcp_servers:
                    server_name = server.get("name", "")
                    if server_name and server_name not in seen_servers:
                        seen_servers.add(server_name)
                        all_mcp_servers.append(server)

        if not all_mcp_servers:
            logger.debug("[MCP Warmup] No MCP servers to warm up")
            return

        logger.info(f"[MCP Warmup] Pre-warming cache for {len(all_mcp_servers)} MCP server(s): {list(seen_servers)}")

        # Fetch descriptions (this populates both file cache and session cache)
        descriptions = get_mcp_server_descriptions(all_mcp_servers, use_cache=True)

        logger.info(f"[MCP Warmup] Cache warmed for {len(descriptions)} server(s)")

    except Exception as e:
        logger.warning(f"[MCP Warmup] Background warmup failed: {e}")
    finally:
        _WARMUP_IN_PROGRESS = False


def extract_package_info_from_config(mcp_config: dict[str, Any]) -> tuple[str, str] | None:
    """
    Extract package name and registry type from MCP server config.

    Parses common MCP server launch patterns to identify the package.

    Args:
        mcp_config: MCP server configuration dict with 'command' and 'args'

    Returns:
        Tuple of (package_name, registry_type) or None if cannot determine

    Example:
        >>> config = {"command": "npx", "args": ["-y", "@upstash/context7-mcp"]}
        >>> extract_package_info_from_config(config)
        ('@upstash/context7-mcp', 'npm')
    """
    command = mcp_config.get("command", "")
    args = mcp_config.get("args", [])

    if not command or not args:
        return None

    # npx: "npx -y @package/name" or "npx @package/name"
    if command in ("npx", "npx.cmd"):
        for i, arg in enumerate(args):
            # Skip flags
            if arg.startswith("-"):
                continue
            # First non-flag argument is the package
            return (arg, "npm")

    # uv: "uv tool run package-name" or "uv run package-name"
    if command == "uv":
        # Find package after "tool run" or "run"
        for i, arg in enumerate(args):
            if arg == "run" and i + 1 < len(args):
                return (args[i + 1], "pypi")

    # docker/podman: "docker run image:tag"
    if command in ("docker", "podman"):
        for i, arg in enumerate(args):
            if arg == "run":
                # Find image (skip flags after run)
                for j in range(i + 1, len(args)):
                    if not args[j].startswith("-"):
                        # Docker image format
                        image = args[j]
                        return (image, "docker")

    # node: "node path/to/script.js" - can't determine package
    # python: "python -m package" - try to extract
    if command in ("python", "python3"):
        for i, arg in enumerate(args):
            if arg == "-m" and i + 1 < len(args):
                return (args[i + 1], "pypi")

    return None


def get_mcp_server_descriptions(
    mcp_servers: list[dict[str, Any]],
    fallback_descriptions: dict[str, str] | None = None,
    use_cache: bool = True,
) -> dict[str, str]:
    """
    Fetch descriptions for all MCP servers from the registry.

    Uses a session-level in-memory cache to prevent repeated HTTP requests
    when building system messages for multiple agents.

    Args:
        mcp_servers: List of MCP server configurations
        fallback_descriptions: Dict of server_name -> description to use
                              if registry lookup fails
        use_cache: Whether to use cached results

    Returns:
        Dict mapping server name to description

    Example:
        >>> servers = [
        ...     {"name": "context7", "command": "npx", "args": ["-y", "@upstash/context7-mcp"]},
        ...     {"name": "brave", "command": "npx", "args": ["-y", "@brave/brave-search-mcp-server"]}
        ... ]
        >>> descriptions = get_mcp_server_descriptions(servers)
        >>> print(descriptions)
        {'context7': 'Up-to-date documentation for libraries...', 'brave': 'Web search...'}
    """
    global _SESSION_CACHE

    if fallback_descriptions is None:
        fallback_descriptions = {}

    client = MCPRegistryClient()
    descriptions = {}

    for server in mcp_servers:
        server_name = server.get("name", "unknown")
        fallback_desc = fallback_descriptions.get(server_name)

        # Check session cache first (fast path for multi-agent scenarios)
        cache_key = _description_cache_key(
            {
                **server,
                "__fallback_description": fallback_desc,
            },
        )
        if cache_key in _SESSION_CACHE:
            descriptions[server_name] = _SESSION_CACHE[cache_key]
            logger.debug(f"Session cache hit for {server_name}")
            continue

        # First try to extract package info and query registry
        package_info = extract_package_info_from_config(server)

        if package_info:
            package_name, registry_type = package_info

            # Check skip list for packages known to not be in the registry
            # This avoids an 18-second full registry scan for each missing package
            if package_name in _PACKAGES_NOT_IN_REGISTRY:
                desc = _PACKAGES_NOT_IN_REGISTRY[package_name]
                descriptions[server_name] = desc
                _SESSION_CACHE[cache_key] = desc
                logger.debug(f"Using skip list description for {server_name} ({package_name})")
                continue

            logger.debug(f"Looking up {server_name} -> {package_name} ({registry_type})")

            server_info = client.find_server_by_package(
                package_name,
                registry_type,
                use_cache=use_cache,
            )

            if server_info and server_info.get("description"):
                descriptions[server_name] = server_info["description"]
                _SESSION_CACHE[cache_key] = server_info["description"]
                continue

        # Fall back to inline description from config
        if server.get("description"):
            descriptions[server_name] = server["description"]
            _SESSION_CACHE[cache_key] = server["description"]
            continue

        # Fall back to provided fallback descriptions
        if fallback_desc is not None:
            descriptions[server_name] = fallback_desc
            _SESSION_CACHE[cache_key] = fallback_desc
            continue

        # Last resort: generate generic description
        descriptions[server_name] = f"MCP server '{server_name}'"
        _SESSION_CACHE[cache_key] = descriptions[server_name]

    return descriptions


# Cache MCP registry lookups for 24 hours
CACHE_DURATION_SECONDS = 24 * 60 * 60


class MCPRegistryClient:
    """
    Client for querying the MCP registry.

    Fetches server metadata from the official MCP registry and caches
    results to minimize API calls.

    Example:
        >>> client = MCPRegistryClient()
        >>> info = client.find_server_by_package("@upstash/context7-mcp", "npm")
        >>> if info:
        ...     print(info['description'])
        'Up-to-date documentation for libraries and frameworks'
    """

    BASE_URL = "https://registry.modelcontextprotocol.io/v0"

    def __init__(self, cache_dir: Path | None = None):
        """
        Initialize MCP registry client.

        Args:
            cache_dir: Directory for caching registry responses.
                      Defaults to ~/.massgen/mcp_cache/
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".massgen" / "mcp_cache"
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, package_name: str, registry_type: str) -> str:
        """Generate cache key for a package lookup."""
        content = f"{package_name}:{registry_type}"
        return hashlib.md5(content.encode()).hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get path to cache file for a given key."""
        return self.cache_dir / f"{cache_key}.json"

    def _read_cache(self, package_name: str, registry_type: str) -> dict[Any, Any] | None:
        """
        Read cached server info if available and not expired.

        Args:
            package_name: Package identifier (e.g., "@upstash/context7-mcp")
            registry_type: Registry type ("npm", "pypi", "docker")

        Returns:
            Cached server info dict, or None if cache miss/expired
        """
        cache_key = self._get_cache_key(package_name, registry_type)
        cache_path = self._get_cache_path(cache_key)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path) as f:
                cached = json.load(f)

            # Check expiration
            if time.time() - cached.get("timestamp", 0) > CACHE_DURATION_SECONDS:
                logger.debug(f"Cache expired for {package_name}")
                return None

            logger.debug(f"Cache hit for {package_name}")
            return cached.get("data")

        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read cache for {package_name}: {e}")
            return None

    def _write_cache(self, package_name: str, registry_type: str, data: dict | None) -> None:
        """
        Write server info to cache.

        Args:
            package_name: Package identifier
            registry_type: Registry type
            data: Server info dict to cache (or None if not found)
        """
        cache_key = self._get_cache_key(package_name, registry_type)
        cache_path = self._get_cache_path(cache_key)

        try:
            with open(cache_path, "w") as f:
                json.dump(
                    {
                        "timestamp": time.time(),
                        "package": package_name,
                        "registry_type": registry_type,
                        "data": data,
                    },
                    f,
                    indent=2,
                )
            logger.debug(f"Cached result for {package_name}")
        except OSError as e:
            logger.warning(f"Failed to write cache for {package_name}: {e}")

    def find_server_by_package(
        self,
        package_name: str,
        registry_type: str = "npm",
        use_cache: bool = True,
    ) -> dict[Any, Any] | None:
        """
        Find a server in the MCP registry by its package name.

        Args:
            package_name: Package identifier (e.g., "@upstash/context7-mcp")
            registry_type: Registry type ("npm", "pypi", "docker", "oci")
            use_cache: Whether to use cached results (default: True)

        Returns:
            Server metadata dict including name, description, version, packages.
            Returns None if server not found or API error occurs.

        Example:
            >>> client = MCPRegistryClient()
            >>> server = client.find_server_by_package("@brave/brave-search-mcp-server", "npm")
            >>> print(server['description'])
            'Web search via Brave API'
        """
        # Check cache first
        if use_cache:
            cached = self._read_cache(package_name, registry_type)
            if cached is not None:
                return cached

        # Query registry
        try:
            result = self._find_in_listing(package_name, registry_type)
            # Cache the result (even if None)
            if use_cache:
                self._write_cache(package_name, registry_type, result)
            return result

        except Exception as e:
            logger.error(f"Failed to query MCP registry for {package_name}: {e}")
            return None

    def _find_in_listing(
        self,
        package_name: str,
        registry_type: str,
    ) -> dict | None:
        """
        List all servers and find by package identifier.

        Args:
            package_name: Package identifier to search for
            registry_type: Registry type to match

        Returns:
            Server dict if found, None otherwise
        """
        url = f"{self.BASE_URL}/servers"
        cursor = None
        total_checked = 0
        max_pages = 50  # Safety limit

        for page_num in range(max_pages):
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor

            try:
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError) as e:
                logger.error(f"Registry API error on page {page_num}: {e}")
                return None

            # API uses 'servers' not 'data'
            servers = data.get("servers", [])

            # Check each server's packages
            for server_entry in servers:
                server = server_entry.get("server", {})
                total_checked += 1

                # Check server name for match (case-insensitive)
                if package_name.lower() in server.get("name", "").lower():
                    logger.debug(f"Found by name match: {server.get('name')}")
                    return server

                # Check packages
                packages = server.get("packages", [])
                for pkg in packages:
                    if pkg.get("registryType") == registry_type and pkg.get("identifier") == package_name:
                        logger.debug(f"Found by package match: {server.get('name')}")
                        return server

            # Check for next page
            cursor = data.get("metadata", {}).get("nextCursor")
            if not cursor:
                logger.debug(f"Searched all pages, total servers: {total_checked}")
                break

        logger.debug(f"Server not found for {package_name} ({registry_type})")
        return None
