"""
UI-TARS Computer Use tool for automating GUI interactions using UI-TARS-1.5 model.

This tool implements computer control using ByteDance's UI-TARS-1.5 model which allows the model to:
- Control a web browser or desktop environment
- Analyze screenshots and decide actions with reasoning
- Perform multi-step workflows with thought process
- Handle desktop operations (click, type, scroll, keyboard shortcuts)
"""

import asyncio
import base64
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from massgen.logger_config import logger
from massgen.tool._result import ExecutionResult, TextContent

# Optional dependencies with graceful fallback
try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = None

try:
    import docker

    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    docker = None

try:
    from ui_tars.action_parser import (
        parse_action_to_structure_output,
        parsing_response_to_pyautogui_code,
    )

    UI_TARS_PARSER_AVAILABLE = True
except ImportError:
    UI_TARS_PARSER_AVAILABLE = False
    parse_action_to_structure_output = None
    parsing_response_to_pyautogui_code = None


# Default screen dimensions
SCREEN_WIDTH = 1440
SCREEN_HEIGHT = 900

# UI-TARS prompt templates (from official repo)
COMPUTER_USE_PROMPT = """You are a GUI agent. You are asked to complete a task by interacting with a computer interface.

You will be presented with a task and an image of the current screen state.
Your goal is to complete the task step by step through GUI interactions.

For each step:
1. First provide your reasoning in "Thought: <your reasoning>"
2. Then provide an action in "Action: <action_command>"

Available actions:
- click(start_box='(x,y)'): Click at coordinates
- double_click(start_box='(x,y)'): Double-click at coordinates
- right_click(start_box='(x,y)'): Right-click at coordinates
- type(text='<text>'): Type text
- key(text='<key>'): Press keyboard key (e.g., 'Return', 'ctrl+c', 'Tab')
- scroll(direction='<dir>'): Scroll (up/down/left/right)
- drag(start_box='(x1,y1)', end_box='(x2,y2)'): Drag from start to end
- WAIT: Wait for page to load
- DONE: Task is completed
- FAIL: Task cannot be completed

Coordinate system: (0,0) is top-left, coordinates are in pixels.
Screen resolution: {width}x{height}

Task: {task}
"""


def encode_image_base64(image_bytes: bytes) -> str:
    """Encode image bytes to base64 string for API calls."""
    return base64.b64encode(image_bytes).decode("utf-8")


def add_box_token(input_string: str) -> str:
    """Add box tokens to coordinates in UI-TARS format (required by model).

    Converts: start_box='(100,200)' -> start_box='<|box_start|>(100,200)<|box_end|>'
    """
    if "Action: " in input_string and "start_box=" in input_string:
        suffix = input_string.split("Action: ")[0] + "Action: "
        actions = input_string.split("Action: ")[1:]
        processed_actions = []
        for action in actions:
            action = action.strip()
            # Extract coordinates using regex
            coordinates = re.findall(r"(start_box|end_box)='\((\d+),\s*(\d+)\)'", action)

            updated_action = action
            for coord_type, x, y in coordinates:
                # Add box tokens
                updated_action = updated_action.replace(
                    f"{coord_type}='({x},{y})'",
                    f"{coord_type}='<|box_start|>({x},{y})<|box_end|>'",
                )
            processed_actions.append(updated_action)

        final_string = suffix + "\n\n".join(processed_actions)
    else:
        final_string = input_string
    return final_string


def parse_ui_tars_response(response: str, screen_width: int, screen_height: int) -> dict[str, Any]:
    """Parse UI-TARS model response into structured action.

    Args:
        response: Raw model response with Thought and Action
        screen_width: Screen width in pixels
        screen_height: Screen height in pixels

    Returns:
        Dictionary with 'thought', 'action', and parsed action details
    """
    result = {"thought": "", "action": "", "parsed_action": None}

    # Extract thought and action
    thought_match = re.search(r"Thought:\s*(.+?)(?=\nAction:|$)", response, re.DOTALL)
    action_match = re.search(r"Action:\s*(.+)", response, re.DOTALL)

    if thought_match:
        result["thought"] = thought_match.group(1).strip()
    if action_match:
        result["action"] = action_match.group(1).strip()

    # Parse action into structured format
    action_text = result["action"]

    # Check for completion/failure
    if "DONE" in action_text.upper() or "finished()" in action_text.lower():
        result["parsed_action"] = {"type": "done"}
        return result
    if "FAIL" in action_text.upper():
        result["parsed_action"] = {"type": "fail"}
        return result
    if "WAIT" in action_text.upper():
        result["parsed_action"] = {"type": "wait", "duration": 2}
        return result

    # Parse coordinate-based actions
    if "click(" in action_text or "double_click(" in action_text or "right_click(" in action_text:
        # Extract action type
        if "double_click(" in action_text:
            action_type = "double_click"
        elif "right_click(" in action_text:
            action_type = "right_click"
        else:
            action_type = "click"

        # Extract coordinates
        coord_match = re.search(r"start_box=['\"]?\(?(\d+),\s*(\d+)\)?['\"]?", action_text)
        if coord_match:
            x, y = int(coord_match.group(1)), int(coord_match.group(2))
            result["parsed_action"] = {"type": action_type, "x": x, "y": y}

    elif "drag(" in action_text:
        # Extract start and end coordinates
        start_match = re.search(r"start_box=['\"]?\(?(\d+),\s*(\d+)\)?['\"]?", action_text)
        end_match = re.search(r"end_box=['\"]?\(?(\d+),\s*(\d+)\)?['\"]?", action_text)
        if start_match and end_match:
            x1, y1 = int(start_match.group(1)), int(start_match.group(2))
            x2, y2 = int(end_match.group(1)), int(end_match.group(2))
            result["parsed_action"] = {"type": "drag", "x1": x1, "y1": y1, "x2": x2, "y2": y2}

    elif "type(" in action_text:
        # Extract text to type - support both 'text=' and 'content=' parameters
        text_match = re.search(r"(?:text|content)=['\"]([^'\"]+)['\"]", action_text)
        if text_match:
            text = text_match.group(1)
            result["parsed_action"] = {"type": "type", "text": text}

    elif "key(" in action_text:
        # Extract key to press - support 'text=', 'content=', and 'key=' parameters
        key_match = re.search(r"(?:text|content|key)=['\"]([^'\"]+)['\"]", action_text)
        if key_match:
            key = key_match.group(1)
            result["parsed_action"] = {"type": "key", "key": key}

    elif "scroll(" in action_text:
        # Extract scroll direction
        dir_match = re.search(r"direction=['\"]([^'\"]+)['\"]", action_text)
        direction = dir_match.group(1) if dir_match else "down"
        result["parsed_action"] = {"type": "scroll", "direction": direction}

    return result


def take_screenshot_docker(container, display: str = ":99") -> bytes:
    """Take a screenshot from Docker container using scrot.

    Args:
        container: Docker container instance
        display: X11 display number

    Returns:
        Screenshot as bytes
    """
    import time

    # Remove old screenshot if exists
    container.exec_run("rm -f /tmp/screenshot.png")

    # Take screenshot with scrot
    result = container.exec_run(
        "scrot /tmp/screenshot.png",
        environment={"DISPLAY": display},
    )

    if result.exit_code != 0:
        logger.error(f"Screenshot command failed: {result.output}")
        # Try alternative method with import
        result = container.exec_run(
            "import -window root /tmp/screenshot.png",
            environment={"DISPLAY": display},
        )
        if result.exit_code != 0:
            logger.error(f"Alternative screenshot also failed: {result.output}")
            return b""

    # Small delay to ensure file is written
    time.sleep(0.2)

    # Read the screenshot
    read_result = container.exec_run("cat /tmp/screenshot.png", stdout=True)
    if read_result.exit_code != 0:
        logger.error(f"Failed to read screenshot: {read_result.output}")
        return b""

    screenshot_bytes = read_result.output

    # Verify we got actual image data
    if len(screenshot_bytes) < 1000:
        logger.error(f"Screenshot too small ({len(screenshot_bytes)} bytes), likely invalid")
        return b""

    if not screenshot_bytes.startswith(b"\x89PNG"):
        logger.error("Screenshot does not have valid PNG header")
        return b""

    logger.info(f"Successfully captured screenshot: {len(screenshot_bytes)} bytes")
    return screenshot_bytes


async def execute_browser_action(page, action: dict[str, Any], screen_width: int, screen_height: int) -> dict[str, Any]:
    """Execute a browser action using Playwright.

    Args:
        page: Playwright page instance
        action: Action dictionary with type and parameters
        screen_width: Screen width in pixels
        screen_height: Screen height in pixels

    Returns:
        Result dictionary
    """
    try:
        action_type = action.get("type")
        logger.info(f"     Executing action: {action_type}")

        if action_type == "click":
            x = action.get("x", 0)
            y = action.get("y", 0)
            await page.mouse.click(x, y)
            logger.info(f"     Clicked at ({x}, {y})")

        elif action_type == "double_click":
            x = action.get("x", 0)
            y = action.get("y", 0)
            await page.mouse.dblclick(x, y)
            logger.info(f"     Double-clicked at ({x}, {y})")

        elif action_type == "right_click":
            x = action.get("x", 0)
            y = action.get("y", 0)
            await page.mouse.click(x, y, button="right")
            logger.info(f"     Right-clicked at ({x}, {y})")

        elif action_type == "type":
            text = action.get("text", "")
            await page.keyboard.type(text)
            logger.info(f"     Typed: {text}")

        elif action_type == "key":
            key = action.get("key", "")
            await page.keyboard.press(key)
            logger.info(f"     Pressed key: {key}")

        elif action_type == "scroll":
            direction = action.get("direction", "down")
            amount = action.get("amount", 300)
            if direction == "down":
                await page.evaluate(f"window.scrollBy(0, {amount})")
            elif direction == "up":
                await page.evaluate(f"window.scrollBy(0, -{amount})")
            elif direction == "left":
                await page.evaluate(f"window.scrollBy(-{amount}, 0)")
            elif direction == "right":
                await page.evaluate(f"window.scrollBy({amount}, 0)")
            logger.info(f"     Scrolled {direction} by {amount}px")

        elif action_type == "drag":
            x1 = action.get("x1", 0)
            y1 = action.get("y1", 0)
            x2 = action.get("x2", 0)
            y2 = action.get("y2", 0)
            await page.mouse.move(x1, y1)
            await page.mouse.down()
            await page.mouse.move(x2, y2)
            await page.mouse.up()
            logger.info(f"     Dragged from ({x1}, {y1}) to ({x2}, {y2})")

        elif action_type == "wait":
            duration = action.get("duration", 1)
            await asyncio.sleep(duration)
            logger.info(f"     Waited {duration} seconds")

        elif action_type in ["done", "fail"]:
            logger.info(f"     Task {action_type}")
            return {"success": True, "completed": True, "status": action_type}

        else:
            logger.warning(f"     Unknown action type: {action_type}")
            return {"error": f"Unknown action type: {action_type}"}

        # Wait for potential navigations/renders
        try:
            await page.wait_for_load_state(timeout=2000)
        except Exception:
            pass

        await asyncio.sleep(0.5)

        return {"success": True}

    except Exception as e:
        logger.error(f"Error executing action {action.get('type')}: {e}")
        return {"error": str(e)}


def execute_docker_action(container, action: dict[str, Any], screen_width: int, screen_height: int, display: str = ":99") -> dict[str, Any]:
    """Execute an action in Docker using xdotool.

    Args:
        container: Docker container instance
        action: Action dictionary with type and parameters
        screen_width: Screen width in pixels
        screen_height: Screen height in pixels
        display: X11 display number

    Returns:
        Result dictionary
    """
    import time

    try:
        action_type = action.get("type")
        logger.info(f"     Docker executing action: {action_type}")

        if action_type == "click":
            x = action.get("x", 0)
            y = action.get("y", 0)
            container.exec_run(
                f"xdotool mousemove {x} {y} click 1",
                environment={"DISPLAY": display},
            )
            logger.info(f"     Docker clicked at ({x}, {y})")

        elif action_type == "double_click":
            x = action.get("x", 0)
            y = action.get("y", 0)
            container.exec_run(
                f"xdotool mousemove {x} {y} click --repeat 2 1",
                environment={"DISPLAY": display},
            )
            logger.info(f"     Docker double-clicked at ({x}, {y})")

        elif action_type == "right_click":
            x = action.get("x", 0)
            y = action.get("y", 0)
            container.exec_run(
                f"xdotool mousemove {x} {y} click 3",
                environment={"DISPLAY": display},
            )
            logger.info(f"     Docker right-clicked at ({x}, {y})")

        elif action_type == "type":
            text = action.get("text", "")
            escaped_text = text.replace("'", "'\\''")
            container.exec_run(
                f"xdotool type '{escaped_text}'",
                environment={"DISPLAY": display},
            )
            logger.info(f"     Docker typed: {text}")

        elif action_type == "key":
            key = action.get("key", "")
            if not key:
                logger.error("     Docker key action missing key parameter")
                return
            # Convert key format
            xdotool_key = key.replace("Control", "ctrl").replace("Shift", "shift").replace("Alt", "alt")
            container.exec_run(
                f"xdotool key {xdotool_key}",
                environment={"DISPLAY": display},
            )
            logger.info(f"     Docker pressed key: {key}")

        elif action_type == "scroll":
            direction = action.get("direction", "down")
            if direction == "down":
                cmd = "xdotool key Page_Down"
            elif direction == "up":
                cmd = "xdotool key Page_Up"
            elif direction == "left":
                cmd = "xdotool key Left Left Left"
            elif direction == "right":
                cmd = "xdotool key Right Right Right"
            else:
                cmd = "xdotool key Page_Down"
            container.exec_run(cmd, environment={"DISPLAY": display})
            logger.info(f"     Docker scrolled {direction}")

        elif action_type == "drag":
            x1 = action.get("x1", 0)
            y1 = action.get("y1", 0)
            x2 = action.get("x2", 0)
            y2 = action.get("y2", 0)
            container.exec_run(
                f"xdotool mousemove {x1} {y1} mousedown 1 mousemove {x2} {y2} mouseup 1",
                environment={"DISPLAY": display},
            )
            logger.info(f"     Docker dragged from ({x1}, {y1}) to ({x2}, {y2})")

        elif action_type == "wait":
            duration = action.get("duration", 1)
            time.sleep(duration)
            logger.info(f"     Docker waited {duration} seconds")

        elif action_type in ["done", "fail"]:
            logger.info(f"     Task {action_type}")
            return {"success": True, "completed": True, "status": action_type}

        else:
            logger.warning(f"     Unknown action type: {action_type}")
            return {"error": f"Unknown action type: {action_type}"}

        time.sleep(0.5)
        return {"success": True}

    except Exception as e:
        logger.error(f"Error executing Docker action {action.get('type')}: {e}")
        return {"error": str(e)}


async def ui_tars_computer_use(
    task: str,
    environment: str = "browser",
    display_width: int = 1440,
    display_height: int = 900,
    max_iterations: int = 25,
    initial_url: str | None = None,
    environment_config: dict[str, Any] | None = None,
    agent_cwd: str | None = None,
    model: str = "ui-tars-1.5",
    huggingface_endpoint: str | None = None,
) -> ExecutionResult:
    """
    Execute a computer automation task using ByteDance's UI-TARS-1.5 model.

    This tool implements GUI control using UI-TARS-1.5 model which analyzes screenshots
    and generates actions with reasoning to autonomously control a browser or Linux desktop.

    Args:
        task: Description of the task to perform
        environment: Environment type - "browser" or "linux" (Docker)
        display_width: Display width in pixels (default: 1440)
        display_height: Display height in pixels (default: 900)
        max_iterations: Maximum number of action iterations (default: 25)
        initial_url: Initial URL to navigate to (browser only)
        environment_config: Additional configuration (browser: headless/browser_type, docker: container_name/display)
        agent_cwd: Agent's current working directory
        model: Model name (default: ui-tars-1.5)
        huggingface_endpoint: HuggingFace Inference Endpoint URL (required)

    Returns:
        ExecutionResult containing success status, action log with thoughts, and results

    Examples:
        # Browser task
        ui_tars_computer_use(
            "Search for Python documentation on Google",
            environment="browser",
            huggingface_endpoint="https://xxx.endpoints.huggingface.cloud"
        )

        # Docker task
        ui_tars_computer_use(
            "Open Firefox and browse to GitHub",
            environment="linux",
            environment_config={"container_name": "cua-container", "display": ":99"},
            huggingface_endpoint="https://xxx.endpoints.huggingface.cloud"
        )

    Prerequisites:
        - UI_TARS_API_KEY environment variable (HuggingFace API token)
        - UI_TARS_ENDPOINT environment variable or huggingface_endpoint parameter
        - For browser: pip install playwright && playwright install
        - For Docker: Docker container with X11 and xdotool installed
        - Optional: pip install ui-tars (for advanced parsing)
    """
    import time

    # Check environment-specific dependencies
    if environment == "linux":
        if not DOCKER_AVAILABLE:
            result = {
                "success": False,
                "operation": "ui_tars_computer_use",
                "error": "Docker not installed. Install with: pip install docker",
            }
            return ExecutionResult(output_blocks=[TextContent(data=json.dumps(result, indent=2))])
    else:  # browser
        if not PLAYWRIGHT_AVAILABLE:
            result = {
                "success": False,
                "operation": "ui_tars_computer_use",
                "error": "Playwright not installed. Install with: pip install playwright && playwright install",
            }
            return ExecutionResult(output_blocks=[TextContent(data=json.dumps(result, indent=2))])

    if not OPENAI_AVAILABLE:
        result = {
            "success": False,
            "operation": "ui_tars_computer_use",
            "error": "OpenAI SDK not installed. Install with: pip install openai",
        }
        return ExecutionResult(output_blocks=[TextContent(data=json.dumps(result, indent=2))])

    environment_config = environment_config or {}

    try:
        # Load environment variables
        script_dir = Path(__file__).parent.parent.parent.parent
        env_path = script_dir / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        else:
            load_dotenv()

        # Get API credentials
        api_key = os.getenv("UI_TARS_API_KEY")
        if not api_key:
            result = {
                "success": False,
                "operation": "ui_tars_computer_use",
                "error": "UI-TARS API key not found. Please set UI_TARS_API_KEY (HuggingFace token) in .env or environment.",
            }
            return ExecutionResult(output_blocks=[TextContent(data=json.dumps(result, indent=2))])

        # Get endpoint URL
        endpoint = huggingface_endpoint or os.getenv("UI_TARS_ENDPOINT")
        if not endpoint:
            result = {
                "success": False,
                "operation": "ui_tars_computer_use",
                "error": "UI-TARS endpoint not found. Set UI_TARS_ENDPOINT in .env or pass huggingface_endpoint parameter.",
            }
            return ExecutionResult(output_blocks=[TextContent(data=json.dumps(result, indent=2))])

        # Initialize UI-TARS client (OpenAI-compatible)
        # Ensure endpoint has /v1 suffix for OpenAI API compatibility
        if not endpoint.endswith("/v1"):
            endpoint = endpoint.rstrip("/") + "/v1"

        client = OpenAI(
            api_key=api_key,
            base_url=endpoint,
        )

        # Initialize environment (browser or Docker)
        container = None
        display = None
        page = None
        playwright_instance = None
        browser = None

        if environment == "linux":
            # Docker environment
            logger.info("Initializing Docker environment...")
            container_name = environment_config.get("container_name", "cua-container")
            display = environment_config.get("display", ":99")

            docker_client = docker.from_env()
            try:
                container = docker_client.containers.get(container_name)
                if container.status != "running":
                    logger.info(f"Starting container {container_name}...")
                    container.start()
                logger.info(f"Using Docker container: {container_name} (display {display})")
            except docker.errors.NotFound:
                result = {
                    "success": False,
                    "operation": "ui_tars_computer_use",
                    "error": f"Docker container '{container_name}' not found. Please create it first.",
                }
                return ExecutionResult(output_blocks=[TextContent(data=json.dumps(result, indent=2))])

            # Take initial screenshot from Docker
            initial_screenshot = take_screenshot_docker(container, display)

            if not initial_screenshot or len(initial_screenshot) < 1000:
                result = {
                    "success": False,
                    "operation": "ui_tars_computer_use",
                    "error": f"Failed to capture screenshot from Docker. Check X11 display {display} is running.",
                }
                return ExecutionResult(output_blocks=[TextContent(data=json.dumps(result, indent=2))])

            # Navigate to initial URL if provided (for Docker environment)
            if initial_url:
                logger.info(f"Navigating Docker Firefox to: {initial_url}")
                try:
                    # Start Firefox if not running
                    container.exec_run("firefox &", environment={"DISPLAY": display}, detach=True)
                    time.sleep(3)  # Wait for Firefox to start

                    # Navigate to URL: Ctrl+L to focus address bar, type URL, press Enter
                    container.exec_run("xdotool key ctrl+l", environment={"DISPLAY": display})
                    time.sleep(0.5)
                    escaped_url = initial_url.replace("'", "'\\''")
                    container.exec_run(f"xdotool type '{escaped_url}'", environment={"DISPLAY": display})
                    time.sleep(0.5)
                    container.exec_run("xdotool key Return", environment={"DISPLAY": display})
                    time.sleep(3)  # Wait for page to load
                    logger.info("Initial URL navigation complete")
                except Exception as e:
                    logger.warning(f"Failed to navigate to initial URL: {e}")

        else:  # browser
            # Browser environment
            logger.info("Initializing browser environment...")
            playwright_instance = await async_playwright().start()

            browser_type_name = environment_config.get("browser_type", "chromium")
            headless = environment_config.get("headless", False)

            if browser_type_name == "firefox":
                browser = await playwright_instance.firefox.launch(headless=headless)
            elif browser_type_name == "webkit":
                browser = await playwright_instance.webkit.launch(headless=headless)
            else:
                browser = await playwright_instance.chromium.launch(headless=headless)

            context = await browser.new_context(
                viewport={"width": display_width, "height": display_height},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            )
            page = await context.new_page()

            # Navigate to initial URL
            if initial_url:
                await page.goto(initial_url, wait_until="networkidle", timeout=30000)
            else:
                await page.goto("about:blank")

            await asyncio.sleep(1)
            initial_screenshot = await page.screenshot()

        # Build system prompt
        system_prompt = COMPUTER_USE_PROMPT.format(
            width=display_width,
            height=display_height,
            task=task,
        )

        # Initialize conversation history
        messages = []
        action_log = []
        iteration = 0

        logger.info(f"Starting UI-TARS automation: {task}")
        logger.info(f"Environment: {environment}, Resolution: {display_width}x{display_height}")

        # Main interaction loop
        while iteration < max_iterations:
            iteration += 1
            logger.info(f"\n=== Iteration {iteration}/{max_iterations} ===")

            # Take screenshot
            if environment == "linux":
                screenshot_bytes = take_screenshot_docker(container, display)
            else:
                screenshot_bytes = await page.screenshot()

            if not screenshot_bytes:
                logger.error("Failed to capture screenshot")
                break

            # Encode screenshot
            screenshot_base64 = encode_image_base64(screenshot_bytes)

            # Build message
            if iteration == 1:
                # First message includes task
                user_message = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": system_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"},
                        },
                    ],
                }
            else:
                # Subsequent messages just have screenshot
                user_message = {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"},
                        },
                    ],
                }

            messages.append(user_message)

            # Call UI-TARS API
            try:
                logger.info("Calling UI-TARS API...")

                # Add box tokens to previous assistant messages
                for msg in messages:
                    if msg.get("role") == "assistant":
                        msg["content"] = add_box_token(msg["content"])

                response = client.chat.completions.create(
                    model="ByteDance-Seed/UI-TARS-1.5-7B",  # Full model ID from HuggingFace endpoint
                    messages=messages,
                    temperature=0.0,
                    top_p=None,
                    max_tokens=400,
                    stream=False,
                )

                response_text = response.choices[0].message.content
                logger.info(f"UI-TARS response:\n{response_text}")

                # Add assistant response to history
                messages.append({"role": "assistant", "content": response_text})

                # Parse response
                parsed = parse_ui_tars_response(response_text, display_width, display_height)

                thought = parsed.get("thought", "")
                action_text = parsed.get("action", "")
                parsed_action = parsed.get("parsed_action")

                action_log.append(
                    {
                        "iteration": iteration,
                        "thought": thought,
                        "action": action_text,
                        "parsed_action": parsed_action,
                    },
                )

                logger.info(f"Thought: {thought}")
                logger.info(f"Action: {action_text}")

                # Check if task is completed or failed
                if parsed_action and parsed_action.get("type") in ["done", "fail"]:
                    status = parsed_action["type"]
                    logger.info(f"Task {status}!")

                    result = {
                        "success": status == "done",
                        "operation": "ui_tars_computer_use",
                        "task": task,
                        "environment": environment,
                        "iterations": iteration,
                        "status": status,
                        "action_log": action_log,
                    }

                    # Clean up
                    if browser:
                        await browser.close()
                    if playwright_instance:
                        await playwright_instance.stop()

                    return ExecutionResult(output_blocks=[TextContent(data=json.dumps(result, indent=2))])

                # Execute action
                if parsed_action:
                    if environment == "linux":
                        exec_result = execute_docker_action(
                            container,
                            parsed_action,
                            display_width,
                            display_height,
                            display,
                        )
                    else:
                        exec_result = await execute_browser_action(
                            page,
                            parsed_action,
                            display_width,
                            display_height,
                        )

                    if exec_result.get("error"):
                        logger.error(f"Action execution error: {exec_result['error']}")
                    elif exec_result.get("completed"):
                        # Task completed
                        result = {
                            "success": True,
                            "operation": "ui_tars_computer_use",
                            "task": task,
                            "environment": environment,
                            "iterations": iteration,
                            "status": exec_result.get("status", "done"),
                            "action_log": action_log,
                        }

                        # Clean up
                        if browser:
                            await browser.close()
                        if playwright_instance:
                            await playwright_instance.stop()

                        return ExecutionResult(output_blocks=[TextContent(data=json.dumps(result, indent=2))])
                else:
                    logger.warning("No valid action parsed from response")

            except Exception as e:
                logger.error(f"Error in iteration {iteration}: {e}")
                action_log.append(
                    {
                        "iteration": iteration,
                        "error": str(e),
                    },
                )

        # Max iterations reached
        logger.info("Max iterations reached")
        result = {
            "success": False,
            "operation": "ui_tars_computer_use",
            "task": task,
            "environment": environment,
            "iterations": iteration,
            "status": "max_iterations_reached",
            "action_log": action_log,
        }

        # Clean up
        if browser:
            await browser.close()
        if playwright_instance:
            await playwright_instance.stop()

        return ExecutionResult(output_blocks=[TextContent(data=json.dumps(result, indent=2))])

    except Exception as e:
        error_msg = f"UI-TARS computer use failed: {e}"
        logger.error(error_msg)
        result = {
            "success": False,
            "operation": "ui_tars_computer_use",
            "error": error_msg,
            "task": task,
            "environment": environment,
        }

        # Clean up on error
        try:
            if browser:
                await browser.close()
            if playwright_instance:
                await playwright_instance.stop()
        except Exception:
            pass

        return ExecutionResult(output_blocks=[TextContent(data=json.dumps(result, indent=2))])
