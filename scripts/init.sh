#!/bin/bash
# MassGen Initialization Script
# Complete setup for MassGen including dependencies, skills, and Docker images

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Default flags
SKIP_DOCKER=false
SKIP_SKILLS=false
SKIP_NPM=false
VERBOSE=false

# Show help
show_help() {
    echo "MassGen Initialization Script"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help          Show this help message"
    echo "  --skip-docker       Skip Docker image builds (saves time)"
    echo "  --skip-skills       Skip skills installation"
    echo "  --skip-npm          Skip npm package installation"
    echo "  -v, --verbose       Verbose output"
    echo ""
    echo "This script will:"
    echo "  1. Check system requirements (Python, Node.js, Docker)"
    echo "  2. Install uv (Python package manager)"
    echo "  3. Install Python dependencies"
    echo "  4. Install npm global packages (openskills, semtools, etc.)"
    echo "  5. Install skills (Anthropic + Crawl4AI)"
    echo "  6. Build Docker runtime images"
    echo "  7. Setup environment (.env file)"
    echo "  8. Verify installation"
    echo ""
    echo "Examples:"
    echo "  $0                  # Full setup"
    echo "  $0 --skip-docker    # Setup without building Docker images"
    echo "  $0 --skip-skills    # Setup without installing skills"
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            ;;
        --skip-docker)
            SKIP_DOCKER=true
            shift
            ;;
        --skip-skills)
            SKIP_SKILLS=true
            shift
            ;;
        --skip-npm)
            SKIP_NPM=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# Helper function for verbose output
log_verbose() {
    if [ "$VERBOSE" = true ]; then
        echo -e "${BLUE}  $1${NC}"
    fi
}

# Detect platform
detect_platform() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "macos"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "linux"
    else
        echo "unknown"
    fi
}

PLATFORM=$(detect_platform)

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   MassGen Initialization${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}Platform: ${PLATFORM}${NC}"
echo ""

# ============================================================================
# 1. System Requirements Check
# ============================================================================
echo -e "${BLUE}[1/8] Checking system requirements...${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Error: Python 3 is not installed${NC}"
    echo "Please install Python 3.12 or higher"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 12 ]); then
    echo -e "${RED}✗ Error: Python 3.12+ required (found $PYTHON_VERSION)${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python: $PYTHON_VERSION${NC}"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo -e "${YELLOW}⚠ Warning: Node.js is not installed${NC}"
    echo -e "${YELLOW}  Some features require Node.js (skills, MCP tools)${NC}"
    if [ "$PLATFORM" = "macos" ]; then
        echo -e "${YELLOW}  Install with: brew install node${NC}"
    else
        echo -e "${YELLOW}  Install with: sudo apt-get install nodejs npm${NC}"
    fi
    NODE_AVAILABLE=false
else
    NODE_VERSION=$(node --version)
    echo -e "${GREEN}✓ Node.js: $NODE_VERSION${NC}"
    NODE_AVAILABLE=true
fi

# Check npm
if ! command -v npm &> /dev/null; then
    if [ "$NODE_AVAILABLE" = true ]; then
        echo -e "${YELLOW}⚠ Warning: npm not found (but Node.js is installed)${NC}"
    fi
    NPM_AVAILABLE=false
else
    NPM_VERSION=$(npm --version)
    echo -e "${GREEN}✓ npm: $NPM_VERSION${NC}"
    NPM_AVAILABLE=true
fi

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}⚠ Warning: Docker is not installed${NC}"
    echo -e "${YELLOW}  Docker is required for secure code execution${NC}"
    echo -e "${YELLOW}  Install from: https://docs.docker.com/get-docker/${NC}"
    DOCKER_AVAILABLE=false
else
    if docker info &> /dev/null; then
        DOCKER_VERSION=$(docker --version | cut -d' ' -f3 | tr -d ',')
        echo -e "${GREEN}✓ Docker: $DOCKER_VERSION${NC}"
        DOCKER_AVAILABLE=true
    else
        echo -e "${YELLOW}⚠ Warning: Docker installed but daemon not running${NC}"
        echo -e "${YELLOW}  Please start Docker and run this script again${NC}"
        DOCKER_AVAILABLE=false
    fi
fi

echo ""

# ============================================================================
# 2. Install uv (Python package manager)
# ============================================================================
echo -e "${BLUE}[2/8] Installing uv...${NC}"

if command -v uv &> /dev/null; then
    UV_VERSION=$(uv --version | cut -d' ' -f2)
    echo -e "${YELLOW}⊙ uv already installed: $UV_VERSION${NC}"
else
    echo "Installing uv..."
    log_verbose "Downloading from https://astral.sh/uv/install.sh"
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Source uv in current shell
    export PATH="$HOME/.local/bin:$PATH"

    if command -v uv &> /dev/null; then
        echo -e "${GREEN}✓ uv installed successfully${NC}"
    else
        echo -e "${RED}✗ Error: uv installation failed${NC}"
        echo -e "${YELLOW}  Please install manually: https://docs.astral.sh/uv/${NC}"
        exit 1
    fi
fi

echo ""

# ============================================================================
# 3. Install Python dependencies
# ============================================================================
echo -e "${BLUE}[3/8] Installing Python dependencies...${NC}"

if [ -f "pyproject.toml" ]; then
    echo "Running uv sync..."
    log_verbose "This will install all dependencies from pyproject.toml"
    uv sync
    echo -e "${GREEN}✓ Python dependencies installed${NC}"
else
    echo -e "${RED}✗ Error: pyproject.toml not found${NC}"
    echo "Please run this script from the MassGen repository root"
    exit 1
fi

echo ""

# ============================================================================
# 4. Install npm global packages
# ============================================================================
if [ "$SKIP_NPM" = false ] && [ "$NPM_AVAILABLE" = true ]; then
    echo -e "${BLUE}[4/8] Installing npm global packages...${NC}"

    # List of packages to install
    NPM_PACKAGES=(
        "openskills"
        "@llamaindex/semtools"
        "@anthropic-ai/claude-code"
        "@google/gemini-cli"
    )

    for package in "${NPM_PACKAGES[@]}"; do
        # Extract package name (handle scoped packages)
        if [[ $package == @* ]]; then
            package_name=$(echo $package | cut -d'/' -f2)
        else
            package_name=$package
        fi

        if npm list -g "$package" &> /dev/null; then
            echo -e "${YELLOW}⊙ $package already installed${NC}"
        else
            echo "Installing $package..."
            log_verbose "npm install -g $package"
            npm install -g "$package"
            echo -e "${GREEN}✓ $package installed${NC}"
        fi
    done

    echo ""
else
    if [ "$SKIP_NPM" = true ]; then
        echo -e "${YELLOW}⊙ [4/8] Skipping npm package installation${NC}"
    else
        echo -e "${YELLOW}⊙ [4/8] Skipping npm packages (npm not available)${NC}"
    fi
    echo ""
fi

# ============================================================================
# 5. Install skills
# ============================================================================
if [ "$SKIP_SKILLS" = false ]; then
    echo -e "${BLUE}[5/8] Installing skills...${NC}"

    if [ -f "scripts/init_skills.sh" ]; then
        chmod +x scripts/init_skills.sh
        ./scripts/init_skills.sh
    else
        echo -e "${YELLOW}⚠ Warning: scripts/init_skills.sh not found${NC}"
        echo -e "${YELLOW}  Skipping skills installation${NC}"
    fi
else
    echo -e "${YELLOW}⊙ [5/8] Skipping skills installation${NC}"
    echo ""
fi

# ============================================================================
# 6. Build Docker images
# ============================================================================
if [ "$SKIP_DOCKER" = false ] && [ "$DOCKER_AVAILABLE" = true ]; then
    echo -e "${BLUE}[6/8] Building Docker runtime images...${NC}"
    echo -e "${YELLOW}  This may take 5-10 minutes on first run...${NC}"
    echo ""

    if [ -f "massgen/docker/build.sh" ]; then
        # Build standard image
        echo -e "${BLUE}Building standard runtime image...${NC}"
        chmod +x massgen/docker/build.sh
        ./massgen/docker/build.sh
        echo ""

        # Build sudo variant
        echo -e "${BLUE}Building sudo runtime image...${NC}"
        ./massgen/docker/build.sh --sudo
        echo ""

        echo -e "${GREEN}✓ Docker images built successfully${NC}"
    else
        echo -e "${YELLOW}⚠ Warning: massgen/docker/build.sh not found${NC}"
        echo -e "${YELLOW}  Skipping Docker image build${NC}"
    fi

    echo ""
else
    if [ "$SKIP_DOCKER" = true ]; then
        echo -e "${YELLOW}⊙ [6/8] Skipping Docker image builds${NC}"
    else
        echo -e "${YELLOW}⊙ [6/8] Skipping Docker builds (Docker not available)${NC}"
    fi
    echo ""
fi

# ============================================================================
# 7. Setup environment
# ============================================================================
echo -e "${BLUE}[7/8] Setting up environment...${NC}"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "Creating .env from .env.example..."
        cp .env.example .env
        echo -e "${GREEN}✓ .env file created${NC}"
        echo -e "${YELLOW}  ⚠ Please edit .env and add your API keys${NC}"
    else
        echo -e "${YELLOW}⚠ Warning: .env.example not found${NC}"
    fi
else
    echo -e "${YELLOW}⊙ .env file already exists${NC}"
fi

echo ""

# ============================================================================
# 8. Verification
# ============================================================================
echo -e "${BLUE}[8/8] Verifying installation...${NC}"

VERIFICATION_PASSED=true

# Check uv
if command -v uv &> /dev/null; then
    echo -e "${GREEN}✓ uv: $(uv --version)${NC}"
else
    echo -e "${RED}✗ uv not found${NC}"
    VERIFICATION_PASSED=false
fi

# Check openskills
if command -v openskills &> /dev/null; then
    echo -e "${GREEN}✓ openskills: installed${NC}"
else
    if [ "$SKIP_NPM" = false ]; then
        echo -e "${YELLOW}⚠ openskills not found${NC}"
    fi
fi

# Check skills directory
if [ -d ".agent/skills" ]; then
    SKILL_COUNT=$(find .agent/skills -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
    echo -e "${GREEN}✓ Skills: ${SKILL_COUNT} installed${NC}"
else
    if [ "$SKIP_SKILLS" = false ]; then
        echo -e "${YELLOW}⚠ Skills directory not found${NC}"
    fi
fi

# Check Docker images
if [ "$DOCKER_AVAILABLE" = true ] && [ "$SKIP_DOCKER" = false ]; then
    if docker images massgen/mcp-runtime:latest -q | grep -q .; then
        echo -e "${GREEN}✓ Docker image: massgen/mcp-runtime:latest${NC}"
    else
        echo -e "${YELLOW}⚠ Docker image not found: massgen/mcp-runtime:latest${NC}"
    fi

    if docker images massgen/mcp-runtime-sudo:latest -q | grep -q .; then
        echo -e "${GREEN}✓ Docker image: massgen/mcp-runtime-sudo:latest${NC}"
    else
        echo -e "${YELLOW}⚠ Docker image not found: massgen/mcp-runtime-sudo:latest${NC}"
    fi
fi

# Check .env
if [ -f ".env" ]; then
    echo -e "${GREEN}✓ Environment: .env file exists${NC}"
else
    echo -e "${YELLOW}⚠ .env file not found${NC}"
fi

echo ""

# ============================================================================
# Summary
# ============================================================================
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
if [ "$VERIFICATION_PASSED" = true ]; then
    echo -e "${GREEN}✓ MassGen initialization complete!${NC}"
else
    echo -e "${YELLOW}⚠ MassGen initialization completed with warnings${NC}"
fi
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""

echo -e "${BLUE}Next steps:${NC}"
echo ""
echo "1. Configure API keys:"
echo "   • Edit .env file and add your API keys"
echo "   • See .env.example for available options"
echo ""
echo "2. Quick test:"
echo "   • uv run massgen --config @examples/basic/multi/three_agents_default.yaml"
echo ""
echo "3. Documentation:"
echo "   • Full docs: https://docs.massgen.ai"
echo "   • AI usage guide: AI_USAGE.md"
echo "   • Quickstart: docs/source/quickstart/"
echo ""
echo "4. Build documentation locally (optional):"
echo "   • cd docs && make livehtml"
echo ""

if [ "$NODE_AVAILABLE" = false ] || [ "$NPM_AVAILABLE" = false ]; then
    echo -e "${YELLOW}⚠ Note: Install Node.js and npm for full functionality${NC}"
    echo ""
fi

if [ "$DOCKER_AVAILABLE" = false ]; then
    echo -e "${YELLOW}⚠ Note: Install Docker for secure code execution${NC}"
    echo ""
fi

echo -e "${GREEN}Happy coding with MassGen! 🚀${NC}"
echo ""
