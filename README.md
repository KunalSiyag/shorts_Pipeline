# Shorts Pipeline — Cheapest Possible Automatic Short Video Creation

**Goal**: Fully automatic generation of vertical short videos (YouTube Shorts / TikTok / Reels) from a topic/prompt, at the lowest possible cost per video (ideally near $0 or a few cents).

You specified three core agents/components:
- **Scripting agent**: Turns a high-level idea/topic into a timed script + detailed per-scene visual prompts.
- **Scene image generation agent**: Turns scene descriptions into consistent, high-quality vertical images.
- **Video generation / assembly**: Turns images (+ audio + captions) into final polished short video.

## Cost Philosophy (2026 reality)

True "free unlimited high-quality generative video" does not exist yet for production. Every real motion model (Wan 2.2, Seedance, Kling, etc.) has either:
- Hardware cost (your electricity + GPU depreciation)
- API cost (even "cheap" ones add up at scale)

**Cheapest viable strategies (ranked for marginal cost per 30-45s short)**:

1. **Ultra-cheap (~$0.01–0.10/video or less)**: Local Ollama scripting + **cheap image API** (Runware, fal.ai, or the lowest Chinese providers ~$0.02–0.04 per image) + **FFmpeg cinematic motion** (Ken Burns slow zoom/pan + crossfades) on the images + edge-tts (free) + FFmpeg assembly + free stock music. **No heavy I2V**.

   This produces very watchable, professional-looking shorts (many successful channels use exactly this or stock footage variants). Strong captions are more important for retention than fancy motion.

2. **Near-zero marginal (if you have decent GPU)**: Everything local.
   - Scripting: Ollama (you already have it).
   - Images: ComfyUI + fast local model (Flux.1 schnell, SDXL Lightning, or quantized models). On your 4GB RTX 3050 this will be slow or require very light/quantized models + --lowvram tricks. Consider a cheap API for images only.
   - Video motion: FFmpeg (as above) **or** local Wan 2.2 5B / GGUF I2V in ComfyUI (challenging on 4GB VRAM — expect slow or use lighter distilled versions).
   - TTS + captions: Local (edge-tts or Kokoro + Whisper).

3. **Low-cost cloud hybrid (great for scale, still cheap)**: Same as #1 but swap image gen to the absolute cheapest provider you can find (monitor Runware/fal/SiliconFlow etc.). For real motion, use the cheapest I2V like Seedance 2.0 Fast or Wan I2V on fal/SiliconFlow (~$0.1–0.3 per 5-8s clip). A 6-scene short can still land under $1–2 easily.

4. **Prototyping here**: Use the Grok `image_gen` + `image_to_video` tools (via the imagine skill) to generate real scene images and short clips, then assemble with FFmpeg. Excellent for validating prompts and flow before locking in a cheap backend.

**Key insight for maximum cheapness + quality**: Invest heavily in **script quality**, **consistent character/style**, **excellent voice**, and **big, well-timed captions**. Visual motion can be relatively simple.

## Hardware note for this machine
- Ollama: installed ✓
- GPU: RTX 3050 Laptop 4GB VRAM → limited for 14B video models. Plan around this (FFmpeg motion first, light local image models or cheap API).

## High-level Architecture

```
Topic / Niche / Prompt
        │
        ▼
┌────────────────────┐
│  Scripting Agent   │  (Ollama local by default, swappable)
│  - Hook + structure│
│  - Scene list      │
│  - Narration text  │
│  - Image prompts   │  (with consistency instructions)
│  - Suggested timings│
└────────────────────┘
        │
        ▼  (parallel possible)
┌────────────────────┐
│  Image Agent       │  (pluggable: mock, ComfyUI local, fal/Runware API, or this env's image_gen)
│  - Consistent style│
│  - 9:16 vertical   │
│  - Character reuse │
└────────────────────┘
        │
        ▼
┌────────────────────┐
│  TTS (edge-tts)    │  Full voiceover or per-scene clips
└────────────────────┘
        │
        ▼
┌────────────────────┐
│  Video Assembly    │  (ffmpeg-based)
│  - Per-scene clips │    with slow zoom/pan (Ken Burns)
│  - Audio sync      │
│  - Captions (SRT/ASS or overlay) │
│  - Music ducking   │
│  - Final concat + export 9:16 │
└────────────────────┘
        │
        ▼
   outputs/final_*.mp4
```

## Project Structure (current)

```
shorts_Pipeline/
├── README.md
├── requirements.txt
├── config.example.yaml
├── pipeline.py                 # main entrypoint / orchestrator
├── agents/
│   ├── script_agent.py         # LLM → structured Script
│   ├── image_agent.py          # Scene prompts → images (pluggable backends)
│   └── video_agent.py          # Images + script → final video
├── utils/
│   ├── tts.py
│   └── ffmpeg_utils.py
├── prompts/
│   └── script_system.txt
├── outputs/                    # generated content (gitignored)
└── .gitignore
```

## Getting Started (Cheap Path)

1. Install Ollama (already present) and pull a good model:
   ```bash
   ollama pull qwen2.5:7b-instruct   # or qwen3, gemma3:12b, llama3.2 etc. Test what fits your RAM
   # For structured output quality, 7B–14B class is usually excellent
   ```

2. Install deps:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy config:
   ```bash
   cp config.example.yaml config.yaml
   # edit as needed (model name, output dirs, etc.)
   ```

4. Run a test (uses mock images first so zero cost):
   ```bash
   python pipeline.py --topic "5 mind-blowing facts about black holes" --output outputs/test1.mp4
   ```

5. Later: Swap in real image generation (see below).

## Image Generation Options (plug into image_agent)

- **Mock** (default for testing pipeline): Colored vertical images with scene text. Lets you validate the full flow instantly and for free.
- **Local ComfyUI**: Run ComfyUI separately (with Flux schnell or your favorite fast model). Image agent calls its API. Best for privacy + eventual zero marginal.
- **Cheap APIs** (recommended for speed + your 4GB GPU):
  - Runware.ai (frequently cited as one of the absolute cheapest)
  - fal.ai (excellent for Flux + Wan models)
  - Together.ai, Replicate, SiliconFlow, or direct provider endpoints for Z-Image / WAN image models.
  - Cost target: aim for <$0.05 per high-quality 9:16 image.
- **This environment (for prototyping)**: You can manually use `image_gen` tool calls (aspect_ratio `9:16`) to create real scene images while developing prompts. Copy results into `outputs/images/` to test downstream video assembly.

**Consistency trick (critical for good shorts)**: In the scripting agent, designate a "hero character / style" or first scene as reference. Image agent generates a base image first, then uses it as reference (img2img / IP-Adapter / edit) for subsequent scenes. Or bake style/character description into every prompt + use seed or consistent negative prompts.

## Video / Motion Options

**Cheapest & recommended starting point**: `ffmpeg` + `zoompan` filter (or `crop` animated) for slow cinematic moves on still images. Add subtle parallax if you generate foreground/background layers. Crossfades between scenes. This is what the `video_agent` implements first.

**Real AI motion when you want it**:
- Local: ComfyUI + Wan 2.2 I2V workflows (templates are built-in now). There are 5B and GGUF options for lower VRAM. On 4GB expect compromises (lower res, shorter clips, slower).
- Cloud: Seedance 2.0 Fast, Wan I2V endpoints, etc. Use the cheapest per-second you can validate for quality.

The video agent is designed to be swappable: `motion_mode: ffmpeg_kenburns | comfyui_i2v | api_i2v`.

Final assembly always uses `ffmpeg -f concat -c copy` (or stream copy where possible) for max quality and speed.

## Captions (very high ROI)

Retention on shorts lives and dies by captions. Plan:
- Generate accurate timings (from per-scene audio duration or full audio + alignment).
- Big, bold, high-contrast text (often 2 lines max, centered or bottom-safe).
- Word-by-word or line highlight (karaoke style) is gold but more work.
- MVP: Scene-level or sentence-level captions using FFmpeg `subtitles` filter + `.srt`/`.ass`.
- Advanced: Integrate Remotion (see gyoridavid/short-video-maker for a great reference implementation using Remotion + Kokoro + Whisper + Pexels).

## Audio

- Voice: `edge-tts` (Microsoft voices, free, unlimited, surprisingly good quality, zero install beyond pip). Alternatives: Piper (local, fast, offline), Kokoro.
- Music: Drop royalty-free tracks into a `music/` folder (or implement Pexels/Pixabay audio search). Lower volume and duck under voice.
- Sound effects: Optional, cheap via free libraries or simple generation.

## Scripting Agent Details

Outputs strict JSON (validated):
```json
{
  "title": "...",
  "hook": "...",
  "scenes": [
    {
      "id": 1,
      "narration": "The exact words the voice will say...",
      "image_prompt": "Detailed visual description for image gen, vertical 9:16, cinematic lighting...",
      "duration_hint_sec": 4.5,
      "notes": "any camera or style guidance"
    }
  ],
  "overall_style": "dark cinematic sci-fi, consistent character: young female astronaut with short hair...",
  "music_suggestion": "subtle tense electronic or epic orchestral"
}
```

System prompt lives in `prompts/script_system.txt` — tune it heavily for your niches. Good scripting is 70% of success.

## Running at Scale (keep it cheap)

- Batch many topics.
- Cache images/scripts when iterating.
- Monitor real cost per video (add simple logging).
- Reuse character references across many videos (build a "universe").
- For fact/list/quote niches: Use heavy templating + small LLM calls so most work is deterministic.
- Add a "repurpose" mode later (take long script → multiple shorts).

## Next Steps & Roadmap (in this repo)

- [x] This README + architecture
- [ ] Core skeleton + script agent (Ollama-first)
- [ ] TTS + basic FFmpeg video assembly with motion + captions (mock images)
- [ ] Real image agent backends (start with mock + local ComfyUI example)
- [ ] Swappable video motion backends
- [ ] Consistency features (reference images)
- [ ] CLI / config improvements, batch mode, cost tracking
- [ ] Optional: Whisper alignment for better caption timing
- [ ] Optional: Remotion captions integration
- [ ] Upload / scheduling helpers (later)

## References & Inspiration (open source cheap pipelines)

- gyoridavid/short-video-maker — excellent Remotion + Kokoro + Pexels + Whisper approach (stock video instead of gen images — adapt ideas).
- SamurAIGPT/AI-Youtube-Shorts-Generator — clipping long form (different use case).
- Binary-Bytes/Auto-YouTube-Shorts-Maker — simple script + gTTS + MoviePy + stock gameplay.
- ShortGPT and OpenShorts for more ideas.

## Contributing / Usage

This is intended as a practical, hackable, low-cost toolkit you own completely.

Tune the prompts for your niche. The cheapest pipeline that produces *watchable and retainable* shorts that actually get views wins — not the one with the fanciest 10-second motion model.

Start with the mock pipeline, generate 10 videos, watch them critically (especially retention hooks and caption timing), then upgrade the image quality and/or motion.

Questions or specific niche? Provide examples of the style/length/voice you want and we can refine the agents and prompts.

Let's build something that scales without destroying your wallet.
