"""
Tool Code Writer

Writes generated MCP tool wrapper code and custom tools to workspace filesystem.
Creates the directory structure that agents discover via filesystem operations.

Directory Structure Created:
    workspace/
    ├── servers/              # MCP tool wrappers (auto-generated)
    │   ├── __init__.py      # Tool registry
    │   ├── weather/
    │   └── github/
    ├── custom_tools/         # Full Python implementations (user-provided)
    ├── utils/               # Agent-created helper scripts
    └── .mcp/                # Hidden MCP runtime
        ├── client.py
        └── servers.json
"""

import json
import shutil
from pathlib import Path
from typing import Any

from ..logger_config import logger
from ..mcp_tools.code_generator import MCPToolCodeGenerator


class ToolCodeWriter:
    """Writes MCP tool code and custom tools to workspace filesystem.

    This class handles:
    - Creating servers/ directory with MCP tool wrappers
    - Copying custom_tools/ if provided
    - Creating empty utils/ for agent scripts
    - Setting up hidden .mcp/ directory for MCP client
    """

    def __init__(self):
        """Initialize the tool code writer."""
        self.generator = MCPToolCodeGenerator()

    def setup_code_based_tools(
        self,
        workspace_path: Path,
        mcp_servers: list[dict[str, Any]],
        custom_tools_path: Path | None = None,
        exclude_custom_tools: list[str] | None = None,
    ) -> None:
        """Set up complete code-based tools directory structure.

        Args:
            workspace_path: Path to agent workspace
            mcp_servers: List of MCP server configurations
            custom_tools_path: Optional path to custom tools directory to copy
            exclude_custom_tools: Optional list of directory names to exclude when copying custom tools

        Example:
            >>> writer = ToolCodeWriter()
            >>> writer.setup_code_based_tools(
            ...     Path("workspace"),
            ...     [{"name": "weather", "tools": [...]}],
            ...     Path("my_custom_tools"),
            ...     exclude_custom_tools=["_claude_computer_use"]
            ... )
        """
        workspace_path = Path(workspace_path)

        logger.info(f"[ToolCodeWriter] Setting up code-based tools in {workspace_path}")

        # Create servers/ directory with MCP wrappers
        self.write_mcp_tools(workspace_path, mcp_servers)

        # Copy custom_tools/ if provided
        if custom_tools_path:
            self.copy_custom_tools(workspace_path, custom_tools_path, exclude_custom_tools)
        else:
            # Create empty custom_tools/ with __init__.py
            self.create_empty_custom_tools(workspace_path)

        # Note: utils/ is NOT pre-created - agents create it in their workspace as needed

        # Create hidden .mcp/ directory with client
        self.create_mcp_client(workspace_path, mcp_servers)

        logger.info("[ToolCodeWriter] Code-based tools setup complete")

    def write_mcp_tools(
        self,
        workspace_path: Path,
        mcp_servers: list[dict[str, Any]],
    ) -> None:
        """Write MCP tool wrappers to servers/ directory.

        Args:
            workspace_path: Path to agent workspace
            mcp_servers: List of MCP server configurations with tool schemas
        """
        servers_path = workspace_path / "servers"
        servers_path.mkdir(parents=True, exist_ok=True)

        server_names = []

        for server_config in mcp_servers:
            server_name = server_config.get("name")
            if not server_name:
                logger.warning("[ToolCodeWriter] Skipping MCP server without name")
                continue

            tools = server_config.get("tools", [])
            if not tools:
                logger.warning(f"[ToolCodeWriter] No tools found for server '{server_name}'")
                continue

            # Create server directory
            server_dir = servers_path / server_name
            server_dir.mkdir(exist_ok=True)

            # Generate wrapper for each tool
            tool_names = []
            for tool in tools:
                tool_name = tool.get("name")
                if not tool_name:
                    continue

                # Generate wrapper code
                wrapper_code = self.generator.generate_tool_wrapper(
                    server_name,
                    tool_name,
                    tool,
                )

                # Sanitize tool name for valid Python filename
                sanitized_name = self.generator.sanitize_tool_name(tool_name)

                # Write to file (using sanitized name)
                tool_file = server_dir / f"{sanitized_name}.py"
                tool_file.write_text(wrapper_code)

                # Store original name for __init__.py generation
                tool_names.append(tool_name)

            # Generate __init__.py for server
            if tool_names:
                init_code = self.generator.generate_server_init(server_name, tool_names)
                (server_dir / "__init__.py").write_text(init_code)
                server_names.append(server_name)

                logger.info(f"[ToolCodeWriter] Generated {len(tool_names)} tools for '{server_name}' server")

        # Generate servers/__init__.py
        if server_names:
            servers_init_code = self.generator.generate_tools_init(server_names)
            (servers_path / "__init__.py").write_text(servers_init_code)

        logger.info(f"[ToolCodeWriter] Created {len(server_names)} MCP server modules in servers/")

    def copy_custom_tools(
        self,
        workspace_path: Path,
        custom_tools_path: Path,
        exclude_custom_tools: list[str] | None = None,
    ) -> None:
        """Copy custom tools directory to workspace.

        Args:
            workspace_path: Path to agent workspace
            custom_tools_path: Path to source custom tools directory
            exclude_custom_tools: Optional list of directory names to exclude (in addition to defaults)
        """
        if not custom_tools_path.exists():
            logger.warning(f"[ToolCodeWriter] Custom tools path does not exist: {custom_tools_path}")
            return

        dest_path = workspace_path / "custom_tools"

        # Remove existing if present
        if dest_path.exists():
            shutil.rmtree(dest_path)

        # Default directories to exclude (internal/example/orchestration tools)
        default_excluded_dirs = {
            "workflow_toolkits",  # Orchestration tools (new_answer, vote, post_evaluation)
            "_code_based_example",  # Example tools
            "_basic",  # Basic/deprecated tools
            "_file_handlers",  # Internal file handling utilities
            "_web_tools",  # Prefer using crawl4ai directly
            "docs",  # Documentation
            "__pycache__",  # Python cache
        }

        # Combine default exclusions with user-specified ones
        excluded_dirs = default_excluded_dirs.copy()
        if exclude_custom_tools:
            excluded_dirs.update(exclude_custom_tools)

        def ignore_patterns(_directory, contents):
            """Filter out excluded directories and files."""
            return [name for name in contents if name in excluded_dirs]

        # Copy directory with filtering
        shutil.copytree(custom_tools_path, dest_path, ignore=ignore_patterns)

        # Replace ALL __init__.py files with minimal versions
        # The original __init__.py files auto-import tools, triggering imports before dependencies are ready
        self._replace_init_files(dest_path)

        # Copy required dependencies that tools import
        self._copy_tool_dependencies(custom_tools_path, dest_path)

        logger.info(f"[ToolCodeWriter] Copied custom tools from {custom_tools_path} (excluded: {', '.join(sorted(excluded_dirs))})")

    def _replace_init_files(self, dest_path: Path) -> None:
        """Replace all __init__.py files with minimal versions.

        The original __init__.py files from massgen/tool/ auto-import all tools,
        which triggers imports before massgen dependencies are available.
        This replaces them with minimal versions that don't auto-import.

        Args:
            dest_path: Destination custom_tools path
        """
        # Replace top-level __init__.py
        init_file = dest_path / "__init__.py"
        init_file.write_text('"""Custom tools provided by user."""\n')

        # Replace all subdirectory __init__.py files recursively
        for init_file in dest_path.rglob("__init__.py"):
            if init_file != dest_path / "__init__.py":  # Skip top-level (already done)
                # Get the directory name for the docstring
                dir_name = init_file.parent.name
                init_file.write_text(f'"""Tools from {dir_name}."""\n')

        logger.debug("[ToolCodeWriter] Replaced all __init__.py files with minimal versions")

    def _copy_tool_dependencies(self, source_path: Path, dest_path: Path) -> None:
        """Copy required tool dependencies (_result.py, logger stub).

        Tools in massgen/tool/ import from massgen.tool._result and massgen.logger_config.
        This copies those dependencies so tools can run standalone.

        Args:
            source_path: Source custom_tools_path (e.g., massgen/tool)
            dest_path: Destination custom_tools path in workspace
        """
        # Copy _result.py if it exists
        result_file = source_path / "_result.py"
        if result_file.exists():
            shutil.copy2(result_file, dest_path / "_result.py")
            logger.debug("[ToolCodeWriter] Copied _result.py dependency")

        # Copy _decorators.py if it exists (some tools use @context_params)
        decorators_file = source_path / "_decorators.py"
        if decorators_file.exists():
            shutil.copy2(decorators_file, dest_path / "_decorators.py")
            logger.debug("[ToolCodeWriter] Copied _decorators.py dependency")

        # Create a minimal logger stub for tools that import from massgen.logger_config
        # This creates a massgen/ directory with logger_config.py
        massgen_dir = dest_path.parent / "massgen"
        massgen_dir.mkdir(exist_ok=True)

        # Create __init__.py
        (massgen_dir / "__init__.py").write_text("")

        # Create logger_config.py with a simple logger
        logger_stub = '''"""Minimal logger for standalone custom tools."""
import logging
import sys

# Create simple logger
logger = logging.getLogger("custom_tools")
logger.setLevel(logging.INFO)

# Add console handler if not already present
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    logger.addHandler(handler)
'''
        (massgen_dir / "logger_config.py").write_text(logger_stub)

        # Create tool/ directory with __init__.py so "from massgen.tool._result" works
        tool_dir = massgen_dir / "tool"
        tool_dir.mkdir(exist_ok=True)
        (tool_dir / "__init__.py").write_text("")

        # Symlink _result.py and _decorators.py into massgen/tool/
        if result_file.exists():
            (tool_dir / "_result.py").write_text(result_file.read_text())
        if decorators_file.exists():
            (tool_dir / "_decorators.py").write_text(decorators_file.read_text())

        logger.debug("[ToolCodeWriter] Created massgen/ stub directory for imports")

    def create_empty_custom_tools(self, workspace_path: Path) -> None:
        """Create empty custom_tools/ directory with __init__.py.

        Args:
            workspace_path: Path to agent workspace
        """
        custom_tools_path = workspace_path / "custom_tools"
        custom_tools_path.mkdir(exist_ok=True)

        init_file = custom_tools_path / "__init__.py"
        if not init_file.exists():
            init_content = '''"""
Custom Tools Directory

Add your custom Python tools here. Each tool should be a .py file with functions
that agents can import and use.

Example:
    # custom_tools/analyze_data.py
    def analyze_sales(csv_path: str) -> dict:
        """Analyze sales data from CSV file."""
        import pandas as pd
        df = pd.read_csv(csv_path)
        return {
            "total": df["amount"].sum(),
            "average": df["amount"].mean()
        }

Usage:
    from custom_tools.analyze_data import analyze_sales
    result = analyze_sales("sales.csv")
"""
'''
            init_file.write_text(init_content)

        logger.info("[ToolCodeWriter] Created empty custom_tools/ directory")

    def create_utils_directory(self, workspace_path: Path) -> None:
        """Create empty utils/ directory for agent-written scripts.

        Args:
            workspace_path: Path to agent workspace
        """
        utils_path = workspace_path / "utils"
        utils_path.mkdir(exist_ok=True)

        readme_file = utils_path / "README.md"
        if not readme_file.exists():
            readme_content = """# Utils Directory

This directory is for **your scripts** - helper functions and workflows you create.

## Purpose

Use utils/ to:
- Combine multiple tools into workflows
- Write async operations for parallel tool calls
- Filter large datasets before returning results
- Create reusable helper functions

## Examples

### Simple Tool Composition
```python
# utils/weather_report.py
from servers.weather import get_forecast, get_current

def daily_report(city: str) -> str:
    current = get_current(city)
    forecast = get_forecast(city, days=3)

    report = f"Current: {current['temp']}°F\\n"
    report += f"3-day forecast: {forecast['summary']}"
    return report
```

### Async Operations
```python
# utils/multi_city_weather.py
import asyncio
from servers.weather import get_forecast

async def get_forecasts(cities: list) -> dict:
    tasks = [get_forecast(city) for city in cities]
    results = await asyncio.gather(*tasks)
    return dict(zip(cities, results))
```

### Data Filtering
```python
# utils/qualified_leads.py
from servers.salesforce import get_records

def get_top_leads(limit: int = 50) -> list:
    # Fetch 10k records
    all_records = get_records(object="Lead", limit=10000)

    # Filter in execution environment (not sent to LLM)
    qualified = [r for r in all_records if r["score"] > 80]

    # Return only top results
    return sorted(qualified, key=lambda x: x["score"], reverse=True)[:limit]
```

## Running Utils

Call from Python:
```python
from utils.weather_report import daily_report
report = daily_report("San Francisco")
print(report)
```

Or execute via command line:
```bash
python utils/weather_report.py "San Francisco"
```
"""
            readme_file.write_text(readme_content)

        logger.info("[ToolCodeWriter] Created utils/ directory for agent scripts")

    def create_mcp_client(
        self,
        workspace_path: Path,
        mcp_servers: list[dict[str, Any]],
    ) -> None:
        """Create hidden .mcp/ directory with client code and server configs.

        Args:
            workspace_path: Path to agent workspace
            mcp_servers: List of MCP server configurations
        """
        mcp_path = workspace_path / ".mcp"
        mcp_path.mkdir(exist_ok=True)

        # Generate MCP client code
        client_code = self.generator.generate_mcp_client()
        (mcp_path / "client.py").write_text(client_code)

        # Write server configurations (filtered to only include necessary info)
        server_configs = {}
        for server in mcp_servers:
            server_name = server.get("name")
            if server_name:
                # Only include connection info, not tool schemas
                server_configs[server_name] = {
                    "type": server.get("type"),
                    "command": server.get("command"),
                    "args": server.get("args"),
                    "env": server.get("env", {}),
                    "url": server.get("url"),
                }

        with open(mcp_path / "servers.json", "w") as f:
            json.dump(server_configs, f, indent=2)

        logger.info(f"[ToolCodeWriter] Created .mcp/ directory with client and {len(server_configs)} server configs")
