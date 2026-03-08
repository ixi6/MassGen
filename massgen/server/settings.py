"""
Server settings for MassGen HTTP server.
"""

from __future__ import annotations

from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class ServerSettings:
    """Settings for the MassGen HTTP server."""

    host: str = "0.0.0.0"
    port: int = 4000
    default_config: str | None = None
    debug: bool = False

    @classmethod
    def from_env(cls) -> ServerSettings:
        """Load settings from environment variables."""

        def _get_bool(name: str, default: bool = False) -> bool:
            v = getenv(name)
            if v is None:
                return default
            return v.strip().lower() in {"1", "true", "yes", "y", "on"}

        host = getenv("MASSGEN_SERVER_HOST", cls.host)
        port_s = getenv("MASSGEN_SERVER_PORT")
        port = int(port_s) if port_s else cls.port
        default_config = getenv("MASSGEN_SERVER_DEFAULT_CONFIG", cls.default_config or "")

        return cls(
            host=host,
            port=port,
            default_config=default_config or None,
            debug=_get_bool("MASSGEN_SERVER_DEBUG", cls.debug),
        )
