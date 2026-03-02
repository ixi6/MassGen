---
name: multimedia-backend-integrator
description: Reference guide for adding new media generation backends to MassGen's unified generate_media tool.
---

# Multimedia Backend Integrator

Reference guide for adding new media generation backends to MassGen's unified `generate_media` tool.

## Architecture Overview

```
_base.py          -- Registration: API keys, default models, priority lists
_selector.py      -- Auto-selection logic: picks best backend by key + priority
_image.py         -- Image backends: OpenAI, Google (Gemini/Imagen), Grok, OpenRouter
_video.py         -- Video backends: Grok, Google Veo, OpenAI Sora
_audio.py         -- Audio backends: ElevenLabs, OpenAI TTS
generate_media.py -- Entry point: routing, validation, batch mode, image-to-image
```

## Complete Checklist: Adding a New Backend

### 1. Registration (`_base.py`)

- [ ] Add to `BACKEND_API_KEYS`: map backend name to env var(s)
- [ ] Add to `DEFAULT_MODELS`: map backend name to `{MediaType: model_name}` for each supported type
- [ ] Add to `BACKEND_PRIORITY`: insert at correct position per media type

### 2. Implementation (`_image.py` / `_video.py` / `_audio.py`)

- [ ] Add `import` for SDK at module top
- [ ] Implement `_generate_{media}_{backend}(config) -> GenerationResult`
- [ ] Check API key first, return error result if missing
- [ ] Create SDK client with API key
- [ ] Map `config.*` fields to SDK parameters
- [ ] Handle continuation (if applicable) — see Continuation Store Patterns
- [ ] Write output bytes to `config.output_path`
- [ ] Return `GenerationResult` with metadata
- [ ] Wrap in try/except, log errors

### 3. Dispatcher Update

- [ ] Add `elif backend == "new_backend":` in the media type's `generate_{media}()` function

### 4. Image-to-Image Support (`generate_media.py`)

- [ ] Add backend name to the `selected_backend not in (...)` check in `_generate_single_with_input_images`
- [ ] Add fallback: `elif has_api_key("new_backend"):` in the auto-selection chain
- [ ] Update error message to mention new backend + env var

### 5. Documentation

- [ ] `TOOL.md`: Add env var to frontmatter, backend to tables, keywords
- [ ] `generate_media.py` docstring: Update `backend_type` list and `Supported Backends`

### 6. Tests

- [ ] Backend registration tests (API keys, default models, priority order)
- [ ] Auto-selection tests (with only this backend's key, with multiple keys)
- [ ] SDK call verification (correct params passed through)
- [ ] Output file written correctly
- [ ] Continuation flow (if applicable)
- [ ] Error handling (missing key, API errors)
- [ ] Parameter mapping (aspect_ratio, size, duration)
- [ ] Update existing tests that assert priority list length/contents

## Continuation Store Patterns

Each backend that supports iterative editing needs a continuation mechanism:

| Backend | Store Type | Key Format | What's Stored | How Continuation Works |
|---------|-----------|------------|---------------|----------------------|
| **OpenAI** | Stateless (server-side) | `response.id` | Nothing locally | Pass `previous_response_id` to next call |
| **Gemini** | `_GeminiChatStore` (in-memory) | `gemini_chat_{uuid12}` | (client, chat) tuples | Reuse chat object for `send_message()`; client kept alive to prevent HTTP connection GC |
| **Grok** | `_GrokImageStore` (in-memory) | `grok_img_{uuid12}` | Base64 strings | Pass stored base64 as `image_url` data URI |

### Store Pattern Template

```python
class _NewBackendStore:
    def __init__(self, max_items: int = 50):
        self._store: OrderedDict[str, Any] = OrderedDict()
        self._max = max_items

    def save(self, data: Any) -> str:
        store_id = f"prefix_{uuid.uuid4().hex[:12]}"
        if len(self._store) >= self._max:
            self._store.popitem(last=False)  # LRU eviction
        self._store[store_id] = data
        return store_id

    def get(self, store_id: str) -> Any | None:
        return self._store.get(store_id)

_store = _NewBackendStore()
```

## Common Pitfalls

1. **Missing from priority list** — Backend works when explicitly specified but never auto-selected
2. **Sync vs async** — Some SDKs are sync-only; wrap in `asyncio.to_thread()` if needed
3. **Ephemeral URLs** — Some APIs return temporary URLs; always prefer base64 or download immediately
4. **Falsy duration** — `duration or default` treats `0` as falsy; use `if duration is not None`
5. **Existing test breakage** — Adding to priority list changes auto-selection; update existing tests that clear env vars
6. **Image-to-image gating** — The `_generate_single_with_input_images` function has a backend allowlist

## Reference Files

| File | Purpose |
|------|---------|
| `massgen/tool/_multimodal_tools/generation/_base.py` | API keys, default models, priorities |
| `massgen/tool/_multimodal_tools/generation/_selector.py` | Backend auto-selection logic |
| `massgen/tool/_multimodal_tools/generation/_image.py` | Image generation backends |
| `massgen/tool/_multimodal_tools/generation/_video.py` | Video generation backends |
| `massgen/tool/_multimodal_tools/generation/_audio.py` | Audio generation backends |
| `massgen/tool/_multimodal_tools/generation/generate_media.py` | Entry point and routing |
| `massgen/tool/_multimodal_tools/TOOL.md` | User-facing documentation |
| `massgen/tests/test_grok_multimedia_generation.py` | Reference: Grok backend tests |
| `massgen/tests/test_grok_multimedia_backend_selection.py` | Reference: Grok selection tests |
| `massgen/tests/test_multimodal_image_backend_selection.py` | Reference: image selection tests |
