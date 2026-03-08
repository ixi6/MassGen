"""Tests for MCP registry client."""

from unittest.mock import MagicMock, patch

from massgen.mcp_tools.registry_client import (
    MCPRegistryClient,
    extract_package_info_from_config,
    get_mcp_server_descriptions,
)


class TestExtractPackageInfo:
    """Tests for extract_package_info_from_config function."""

    def test_npx_package(self):
        """Test extracting package from npx command."""
        config = {"command": "npx", "args": ["-y", "@upstash/context7-mcp"]}
        result = extract_package_info_from_config(config)
        assert result == ("@upstash/context7-mcp", "npm")

    def test_npx_without_y_flag(self):
        """Test extracting package from npx without -y flag."""
        config = {"command": "npx", "args": ["@brave/brave-search-mcp-server"]}
        result = extract_package_info_from_config(config)
        assert result == ("@brave/brave-search-mcp-server", "npm")

    def test_uv_package(self):
        """Test extracting package from uv command."""
        config = {"command": "uv", "args": ["tool", "run", "mcp-package"]}
        result = extract_package_info_from_config(config)
        assert result == ("mcp-package", "pypi")

    def test_uv_run_package(self):
        """Test extracting package from uv run command."""
        config = {"command": "uv", "args": ["run", "some-package"]}
        result = extract_package_info_from_config(config)
        assert result == ("some-package", "pypi")

    def test_docker_image(self):
        """Test extracting image from docker command."""
        config = {"command": "docker", "args": ["run", "mcp/server:latest"]}
        result = extract_package_info_from_config(config)
        assert result == ("mcp/server:latest", "docker")

    def test_docker_with_flags(self):
        """Test extracting image from docker command with flags."""
        config = {"command": "docker", "args": ["run", "-it", "--rm", "mcp/server"]}
        result = extract_package_info_from_config(config)
        assert result == ("mcp/server", "docker")

    def test_python_module(self):
        """Test extracting module from python -m command."""
        config = {"command": "python", "args": ["-m", "mcp_server"]}
        result = extract_package_info_from_config(config)
        assert result == ("mcp_server", "pypi")

    def test_empty_config(self):
        """Test handling empty config."""
        config = {}
        result = extract_package_info_from_config(config)
        assert result is None

    def test_no_args(self):
        """Test handling config without args."""
        config = {"command": "npx"}
        result = extract_package_info_from_config(config)
        assert result is None

    def test_unknown_command(self):
        """Test handling unknown command."""
        config = {"command": "unknown", "args": ["something"]}
        result = extract_package_info_from_config(config)
        assert result is None


class TestGetMCPServerDescriptions:
    """Tests for get_mcp_server_descriptions function."""

    def test_uses_inline_description_fallback(self):
        """Test that inline description from config is used as fallback."""
        servers = [
            {
                "name": "my-server",
                "command": "unknown",
                "args": ["something"],
                "description": "My custom server description",
            },
        ]
        result = get_mcp_server_descriptions(servers)
        assert result["my-server"] == "My custom server description"

    def test_uses_fallback_descriptions(self):
        """Test that fallback descriptions dict is used."""
        servers = [{"name": "my-server", "command": "unknown", "args": ["something"]}]
        fallbacks = {"my-server": "Fallback description"}
        result = get_mcp_server_descriptions(servers, fallback_descriptions=fallbacks)
        assert result["my-server"] == "Fallback description"

    def test_generates_generic_description(self):
        """Test that generic description is generated as last resort."""
        servers = [{"name": "my-server", "command": "unknown", "args": ["something"]}]
        result = get_mcp_server_descriptions(servers)
        assert result["my-server"] == "MCP server 'my-server'"

    @patch.object(MCPRegistryClient, "find_server_by_package")
    def test_fetches_from_registry(self, mock_find):
        """Test that descriptions are fetched from registry."""
        mock_find.return_value = {"description": "Registry description"}

        servers = [
            {"name": "context7", "command": "npx", "args": ["-y", "@upstash/context7-mcp"]},
        ]
        result = get_mcp_server_descriptions(servers)

        assert result["context7"] == "Registry description"
        mock_find.assert_called_once_with("@upstash/context7-mcp", "npm", use_cache=True)


class TestMCPRegistryClient:
    """Tests for MCPRegistryClient class."""

    def test_cache_key_generation(self):
        """Test that cache keys are consistent."""
        client = MCPRegistryClient()
        key1 = client._get_cache_key("@test/package", "npm")
        key2 = client._get_cache_key("@test/package", "npm")
        assert key1 == key2

    def test_different_packages_different_keys(self):
        """Test that different packages have different cache keys."""
        client = MCPRegistryClient()
        key1 = client._get_cache_key("@test/package1", "npm")
        key2 = client._get_cache_key("@test/package2", "npm")
        assert key1 != key2

    @patch("requests.get")
    def test_find_server_by_package_match(self, mock_get):
        """Test finding server by package identifier."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "servers": [
                {
                    "server": {
                        "name": "io.github.upstash/context7",
                        "description": "Context7 MCP server",
                        "packages": [
                            {"registryType": "npm", "identifier": "@upstash/context7-mcp"},
                        ],
                    },
                },
            ],
            "metadata": {"nextCursor": None},
        }
        mock_get.return_value = mock_response

        client = MCPRegistryClient()
        result = client.find_server_by_package(
            "@upstash/context7-mcp",
            "npm",
            use_cache=False,
        )

        assert result is not None
        assert result["description"] == "Context7 MCP server"

    @patch("requests.get")
    def test_find_server_not_found(self, mock_get):
        """Test handling server not found."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "servers": [],
            "metadata": {"nextCursor": None},
        }
        mock_get.return_value = mock_response

        client = MCPRegistryClient()
        result = client.find_server_by_package(
            "@nonexistent/package",
            "npm",
            use_cache=False,
        )

        assert result is None
