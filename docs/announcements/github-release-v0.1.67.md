# 🚀 Release Highlights — v0.1.67 (2026-03-23)

### 🖥️ [Modernized WebUI](https://docs.massgen.ai/en/latest/user_guide/webui.html)
- **Inline final answers**: Final answers render inline in AgentChannel — no more modal overlays
- **Keyboard shortcuts**: Responsive navigation via `useV2KeyboardShortcuts`
- **Modernized architecture**: Zustand stores (message, mode, tile, agent, theme) replace ad-hoc state management

### 💰 RoundBudgetGuardHook
- **Per-round cost enforcement**: Tracks cumulative and per-round API costs in real-time, blocks execution when budgets are exceeded
- **Configurable warnings**: Default thresholds at 50%, 75%, 90% of budget with graceful termination on overrun

### 🎭 Unified Pre-Collab Phases
- **Parallel execution**: Persona generation, evaluation criteria, and prompt improvement now run simultaneously
- **Unified batch display**: Single TUI screen shows all pre-collab phases together
- **Persona diversity modes**: Three modes — perspective, implementation, methodology

### 🛡️ Regression Guard
- **Blind A/B verification**: Specialized subagent compares current vs previous answer without revealing which is which
- **Criteria-based evaluation**: Evaluates against full criteria list (E1..EN) to catch silent regressions

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.67
  # Try the modernized WebUI
  uv run massgen --web
  ```
