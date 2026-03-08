# Producing Longer Videos

## The Core Limitation

Current video generation APIs produce short clips — **at most 15 seconds** per call (Grok), with most backends capping at 8-12 seconds. There is no API that generates a continuous 30-second or 60-second video in one shot.

**This is not a bug — it's a fundamental constraint of the current generation of video models.** Plan around it.

## Multi-Shot Decomposition

The proven approach: **split your video into discrete sections, generate each independently, then assemble.**

### 1. Plan the Shot List First

Before generating anything, write a shot-by-shot breakdown with:
- **Shot number and timing** (e.g., "Shot 3: 12-18s")
- **Subject/action** (what happens in this segment)
- **Camera language** (wide, close-up, tracking, dolly, pan, pullback)
- **Visual continuity notes** (lighting, color palette, atmosphere)

Example for a 30-second nature documentary:
```
Shot 1 (0-6s):   Wide establishing shot — hydrothermal vents, bioluminescent plankton, slow camera glide
Shot 2 (6-12s):  Close-medium tracking — comb jelly, rainbow cilia, soft bioluminescent light
Shot 3 (12-18s): Medium dolly — dumbo octopus flapping fins over seafloor
Shot 4 (18-24s): Dramatic reveal — anglerfish lure emerging from darkness
Shot 5 (24-30s): Wide pullback — multiple bioluminescent organisms, awe-inspiring closing
```

### 2. Craft Cinematic Prompts

Each clip prompt should be self-contained but share a consistent visual language:

**Always include:**
- Specific camera movement ("slow cinematic dolly", "gentle camera pullback", "close-medium tracking shot")
- Lighting and atmosphere descriptions ("soft bioluminescent light", "dramatic but natural lighting")
- Style anchors ("BBC-style cinematography", "nature documentary footage", "realistic underwater motion")
- Exclusion constraints ("no text", "no logos", "no fantasy elements")

**For visual continuity across clips:**
- Maintain consistent color palette descriptions across all prompts
- Use the same style anchor phrase in every prompt (e.g., "ultra-realistic nature documentary")
- Keep lighting descriptions compatible (don't go from "dark abyss" to "bright daylight" without reason)

### 3. Generate Clips in Parallel

Generate all clips concurrently using background mode — there's no reason to wait for one clip before starting the next:

```python
# Launch all clips in parallel (background mode)
clip1 = generate_media(prompt="Wide establishing shot...", mode="video", duration=6, background=True)
clip2 = generate_media(prompt="Close tracking shot...", mode="video", duration=6, background=True)
clip3 = generate_media(prompt="Medium dolly shot...", mode="video", duration=6, background=True)
clip4 = generate_media(prompt="Dramatic reveal...", mode="video", duration=6, background=True)
clip5 = generate_media(prompt="Wide pullback...", mode="video", duration=6, background=True)
# Collect results as they complete
```

### 4. Assemble with Transitions

After collecting all clips, concatenate them using ffmpeg. For professional results:

**Simple hard cut** (sufficient when shots are well-planned):
```bash
# Create file list
echo "file 'clip1.mp4'" > concat_list.txt
echo "file 'clip2.mp4'" >> concat_list.txt
# ...
ffmpeg -f concat -safe 0 -i concat_list.txt -c copy output.mp4
```

**Crossfade transitions** (smoother, more cinematic):
```bash
# 0.5s crossfade between clips
ffmpeg -i clip1.mp4 -i clip2.mp4 \
  -filter_complex "[0][1]xfade=transition=fade:duration=0.5:offset=5.5" \
  -c:v libx264 output.mp4
```

**Available ffmpeg xfade transitions** (professional options):
- `fade` — classic dissolve, works for most scene changes
- `wipeleft` / `wiperight` — directional wipe, good for spatial progression
- `slideup` / `slidedown` — vertical slide, good for revealing new environments
- `smoothleft` / `smoothright` — softer directional transition
- `circlecrop` — iris effect, dramatic reveals
- `diagtl` / `diagbr` — diagonal wipes

**Choose transitions based on narrative intent:**
- **Same scene, different angle**: use `fade` (0.3-0.5s)
- **New location or time**: use `fade` with longer duration (0.7-1.0s) or `wipeleft`
- **Dramatic reveal**: use `circlecrop` or hard cut
- **Continuous journey**: use `smoothleft`/`smoothright`

### 5. Add Audio as a Continuity Bridge

A unified audio track is the single most effective way to smooth over visual cuts between independently generated clips:

- **Narration**: Generate a single voiceover covering the full timeline, then overlay it on the assembled video
- **Music**: A continuous background track unifies disparate visual segments
- **Ambient sound**: Consistent ambient audio (e.g., underwater sounds) masks transitions

```python
# Generate narration for the full video
narration = generate_media(
    prompt="Far below sunlight, the deep ocean breathes in darkness...",
    mode="audio",
    voice="coral"  # or preferred voice
)
```

Then mix with ffmpeg:
```bash
ffmpeg -i assembled_video.mp4 -i narration.mp3 \
  -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 \
  final_output.mp4
```

## Alternative: Veo Extension Chain

Google Veo supports true timeline extension via `continue_from`, which can produce longer continuous video without manual assembly:

```python
# Initial clip
r1 = generate_media(prompt="Opening shot...", mode="video", backend_type="google", duration=8)
# Extend the timeline
r2 = generate_media(prompt="Next scene...", mode="video", continue_from=r1['continuation_id'])
r3 = generate_media(prompt="Closing shot...", mode="video", continue_from=r2['continuation_id'])
```

**Trade-offs vs. parallel decomposition:**
- **Pro**: True continuity — each extension sees the previous frames
- **Con**: Sequential (can't parallelize), limited to 720p, max 20 extensions
- **Con**: 2-day expiry on generated videos — long projects risk losing intermediate state
- **Con**: Only 16:9 and 9:16 aspect ratios

**Use Veo extensions when** visual continuity between shots is critical (e.g., continuous camera movement). **Use parallel decomposition when** you want maximum quality, resolution flexibility, and faster generation.

## Prompt Crafting Tips

### Use Cinematic Vocabulary

Models respond well to specific filmmaking language:

| Term | Effect |
|------|--------|
| "wide establishing shot" | Sets the scene, shows environment |
| "close-up" / "extreme close-up" | Intimate detail, emotional emphasis |
| "tracking shot" | Camera follows subject movement |
| "dolly in/out" | Camera physically moves toward/away |
| "pan left/right" | Camera rotates horizontally |
| "tilt up/down" | Camera rotates vertically |
| "crane shot" | Elevated sweeping movement |
| "slow motion" | Emphasizes dramatic moments |
| "handheld" | Documentary/realistic feel |
| "steadicam" | Smooth movement following action |

### Negative Constraints Matter

Always specify what you **don't** want. Common exclusions:
- "no text, no titles, no watermarks, no logos"
- "no fantasy elements, no unrealistic effects" (for documentary style)
- "no blurry, no low quality, no artifacts"
- "no sudden camera jumps, no jarring transitions"

### Style Anchors for Consistency

Pick one style phrase and repeat it across all clip prompts:
- "BBC Earth documentary cinematography"
- "cinematic film grain, anamorphic lens"
- "professional corporate video, clean modern aesthetic"
- "indie film aesthetic, natural lighting"

## Duration Strategy

| Goal | Recommended Approach |
|------|---------------------|
| < 8s | Single clip, any backend |
| 8-15s | Single clip (Grok or Sora 12s) |
| 15-30s | 3-5 parallel clips + assembly |
| 30-60s | 5-10 parallel clips + audio bridge |
| 60s+ | 10+ clips, or Veo extension chain (up to ~141s) |

For clips within a multi-shot video, **6-8 seconds per segment** is the sweet spot — long enough to establish a scene, short enough to keep pacing dynamic.

## Professional Post-Production with Remotion

For results beyond what raw ffmpeg can achieve — styled captions, cinematic transitions, title cards, motion graphics, light leak effects — use **Remotion** (React-based programmatic video framework).

**Remotion skill location:**
- Local (if installed via quickstart): `.agent/skills/remotion/SKILL.md`
- Remote: https://github.com/remotion-dev/skills

### When to Use Remotion vs. FFmpeg

| Need | FFmpeg | Remotion |
|------|--------|----------|
| Simple concatenation / hard cuts | Good | Overkill |
| Basic crossfade transitions | Good | Better (more options) |
| Styled animated captions | Painful (`drawtext` escaping) | Excellent (CSS-styled, word-level) |
| Title cards / lower thirds | Manual | Native (React components) |
| Motion graphics / text animations | Not possible | Native (full React/CSS/Three.js) |
| Light leak / overlay effects | Complex filter chains | Built-in (`@remotion/light-leaks`) |
| AI footage with programmatic overlays | Not feasible at quality | Native — `<Video>` + React layers |
| Color grading via LUTs | Good (`lut3d` filter) | Use ffmpeg for this |
| Audio mixing / ducking | Good | Use ffmpeg or Pydub for this |

**Rule of thumb**: Use ffmpeg for raw clip assembly and audio mixing. Use Remotion when the output needs to look professionally edited — captions, titles, transitions with timing curves, motion graphics overlays.

### Hybrid Composition: AI Footage + Remotion Animation

The highest-quality videos combine AI-generated footage (photorealistic, cinematic) with Remotion's programmatic animation (precise typography, motion graphics, overlays). Neither alone produces the best result.

**Composition structure for each shot:**
```
Layer 3 (top):    Text overlays, captions, motion graphics (Remotion React components)
Layer 2 (middle): Light leaks, color overlays, vignettes (Remotion effects)
Layer 1 (bottom): AI-generated video clip (<Video> or <OffthreadVideo>)
```

**Shot types in a typical video:**
- **AI-backed shots**: Generated footage as background, Remotion elements composited on top (e.g., product demo with animated text overlay)
- **Pure animation shots**: Title cards, data visualizations, logo reveals — no AI footage needed, 100% Remotion
- **Transition shots**: Animated motion graphics bridging between AI-backed segments

**Handling imperfect AI clips**: Generated clips may have minor artifacts (slight distortion, repeated patterns). Do NOT discard them — instead, mask issues with overlays, motion graphics, or light leaks in Remotion. The cinematic quality of AI footage underneath still elevates the result above pure programmatic rendering.

### Recommended Workflow

1. **Plan which shots need AI footage** — not every shot does. Title cards, logo reveals, and motion-graphics-heavy segments are better as pure Remotion animation.
2. **Generate only the clips you need** with `generate_media` (parallel, background mode). Each generation costs money — don't speculatively over-generate.
3. **Review generated clips** with `read_media` — assess quality and plan your composition around what you actually have.
4. **Generate audio** (narration, music) with `generate_media(mode="audio")`
5. **Assemble and composite in Remotion**:
   - Import AI clips as `<Video>` or `<OffthreadVideo>` background layers
   - Add `<Sequence>` blocks for timeline composition
   - Layer typography, motion graphics, and captions on top of footage
   - Apply transitions between scenes (`rules/transitions.md`)
   - Overlay styled captions (`rules/subtitles.md`, `rules/display-captions.md`)
   - Add pure-animation segments for title cards (`rules/text-animations.md`)
   - Apply light leak effects for cinematic feel (`rules/light-leaks.md`)
6. **Render** via Remotion's headless renderer (works in Docker)

Load the Remotion skill's individual rule files for detailed code examples and API usage.
