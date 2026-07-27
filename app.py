"""
Shorts Pipeline - Streamlit GUI
A clean web interface to control the entire automatic short video creation pipeline.

Run with:
    streamlit run app.py

Features:
- Topic → Script generation (Ollama first)
- Script preview + basic editing
- Scene image generation (mock by default, extensible)
- Video assembly with ffmpeg (Ken Burns + captions + TTS)
- Live previews of images and final video
- History of previous runs
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st
import yaml
import os
from pathlib import Path
import json

# Project imports
from agents import ScriptAgent, ImageAgent, VideoAgent
from agents.script_agent import VideoScript

# ------------------------------
# Page config & Modern Styling (inspired by OpenArt, Seedance, etc.)
# ------------------------------
st.set_page_config(
    page_title="ShortsForge • AI Short Video Studio",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Polished modern dark UI CSS (close to OpenArt/Seedance vibe)
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600&display=swap');
    
    :root {
        --bg: #0a0a0f;
        --card: #111114;
        --accent: #6366f1;
    }
    
    .stApp {
        background: linear-gradient(180deg, #0a0a0f 0%, #0f0f14 100%);
        color: #e2e8f0;
        font-family: 'Inter', system_ui, sans-serif;
    }
    
    .main .block-container {
        padding-top: 1rem;
        max-width: 1280px;
    }
    
    h1, h2, h3 {
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 600;
        letter-spacing: -0.02em;
    }
    
    .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 1rem 0 1.5rem;
        border-bottom: 1px solid #1f2937;
        margin-bottom: 1.5rem;
    }
    
    .logo {
        font-size: 1.75rem;
        font-weight: 700;
        background: linear-gradient(90deg, #6366f1, #a855f7);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    .modern-card {
        background: #111114;
        border: 1px solid #1f2937;
        border-radius: 16px;
        padding: 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        transition: transform 0.2s, box-shadow 0.2s;
    }
    
    .modern-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1);
    }
    
    .scene-card {
        background: #1a1c23;
        border: 1px solid #2a2d38;
        border-radius: 12px;
        padding: 1rem;
        margin-bottom: 0.75rem;
    }
    
    .stButton>button {
        background: linear-gradient(90deg, #6366f1, #4f46e5);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.5rem 1.25rem;
        font-weight: 600;
        transition: all 0.2s;
    }
    
    .stButton>button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgb(99 102 241 / 0.3);
    }
    
    .stSelectbox, .stTextInput, .stTextArea {
        background: #1a1c23 !important;
        border: 1px solid #374151 !important;
        border-radius: 10px !important;
    }
    
    .gallery img {
        border-radius: 12px;
        border: 1px solid #374151;
    }
    
    .metric-card {
        background: #111114;
        border-radius: 12px;
        padding: 1rem;
        text-align: center;
        border: 1px solid #1f2937;
    }
    
    .status-pill {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    
    .step-header {
        font-size: 1.1rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
        color: #a5b4fc;
    }
    
    .small-muted {
        font-size: 0.8rem;
        color: #64748b;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Session state init
if "script" not in st.session_state:
    st.session_state.script = None
if "image_paths" not in st.session_state:
    st.session_state.image_paths = []
if "final_video" not in st.session_state:
    st.session_state.final_video = None
if "providers" not in st.session_state:
    st.session_state.providers = {
        "script": {"provider": "ollama", "model": "qwen2.5:3b", "api_key": ""},
        "image": {"provider": "comfyui", "model": "", "api_key": ""},
    }

# ------------------------------
# Helpers
# ------------------------------
ROOT = Path(__file__).parent
OUTPUTS = ROOT / "outputs"
SCRIPTS_DIR = OUTPUTS / "scripts"
IMAGES_DIR = OUTPUTS / "images"
FINALS_DIR = OUTPUTS / "finals"

for d in (SCRIPTS_DIR, IMAGES_DIR, FINALS_DIR):
    d.mkdir(parents=True, exist_ok=True)

def slugify(text: str) -> str:
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "short"

def save_script(script: VideoScript, topic: str) -> Path:
    path = SCRIPTS_DIR / f"{slugify(topic)}.json"
    path.write_text(json.dumps(script.model_dump(), indent=2))
    return path

def load_previous_scripts() -> list[dict]:
    scripts = []
    for p in sorted(SCRIPTS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(p.read_text())
            scripts.append({"path": str(p), "title": data.get("title", p.stem), "data": data})
        except Exception:
            pass
    return scripts

def list_previous_videos() -> list[Path]:
    return sorted(FINALS_DIR.glob("*.mp4"), reverse=True)


def load_visual_styles() -> dict:
    path = ROOT / "prompts" / "visual_styles.yaml"
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def check_comfyui_status() -> dict:
    """Return status info about local ComfyUI."""
    import requests
    try:
        resp = requests.get("http://127.0.0.1:8188/system_stats", timeout=3)
        if resp.status_code == 200:
            return {"running": True}
        return {"running": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"running": False, "error": str(e)}


def check_ollama_status() -> dict:
    """Return status info about Ollama."""
    import requests
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            return {
                "running": True,
                "models": [m.get("name") for m in models],
                "count": len(models)
            }
        return {"running": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"running": False, "error": str(e)}

# ------------------------------
# Helper functions
# ------------------------------
def reset_pipeline():
    st.session_state.script = None
    st.session_state.image_paths = []
    st.session_state.final_video = None


def configure_image_agent(
    image_agent: ImageAgent, backend: str, api_key: str = "", visual_style: str = "cinematic"
) -> ImageAgent:
    """Apply sidebar-selected image backend and API keys."""
    image_agent.backend = backend
    st.session_state.providers["image"]["provider"] = backend
    if backend == "explainer":
        draw_style = "stick_figure" if visual_style == "stick_figure" else "whiteboard"
        if "explainer" not in image_agent.cfg.setdefault("image_generation", {}):
            image_agent.cfg["image_generation"]["explainer"] = {}
        image_agent.cfg["image_generation"]["explainer"]["style"] = draw_style
    if api_key:
        if backend == "fal":
            os.environ["FAL_KEY"] = api_key
        elif backend == "runware":
            os.environ["RUNWARE_API_KEY"] = api_key
    return image_agent

def get_agent_with_overrides(agent_class, provider_key):
    """Create agent with UI-selected backend overrides (no yaml editing needed)."""
    prov = st.session_state.providers[provider_key]
    
    # Temporarily override env for keys
    if prov.get("api_key"):
        if provider_key == "script":
            os.environ["OPENAI_API_KEY"] = prov["api_key"]
        elif provider_key == "image":
            if prov["provider"] == "fal":
                os.environ["FAL_KEY"] = prov["api_key"]
            elif prov["provider"] == "runware":
                os.environ["RUNWARE_API_KEY"] = prov["api_key"]
    
    cfg = {"image_generation": {"backend": prov["provider"]}}
    if provider_key == "script":
        # For script, we use the existing logic with openai_compat or ollama
        pass
    
    return agent_class("config.yaml")  # still loads base, overrides happen via env / params

# ------------------------------
# Sidebar - Settings
# ------------------------------
st.sidebar.title("⚙️ Settings")

with st.sidebar:
    st.markdown("**Visual Style**")
    visual_style = st.selectbox(
        "Visual style",
        ["cinematic", "whiteboard", "stick_figure"],
        index=0,
        help="Cinematic = AI images + smooth AI video motion. Whiteboard/stick = drawn stills."
    )
    style_cfg = load_visual_styles().get(visual_style, {})

    st.markdown("**LLM / Scripting**")
    llm_model = st.text_input("Ollama model", value="qwen2.5:3b", help="Must be pulled with `ollama pull`. Use small models (3b or less) on 4-6GB VRAM.")
    provider = st.selectbox("Provider", ["ollama", "openai_compatible"], index=0)

    st.markdown("**Image Generation**")
    comfy_status = check_comfyui_status()
    if not comfy_status["running"]:
        st.caption("ComfyUI not running. Start: `bash scripts/start_comfyui.sh`")
    else:
        st.caption("ComfyUI running — open http://127.0.0.1:8188 (use 127.0.0.1, not localhost)")
    default_backend = "explainer" if visual_style in ("whiteboard", "stick_figure") else "comfyui"
    backend_options = ["explainer", "comfyui", "pollinations", "fal", "runware", "mock"]
    backend_index = backend_options.index(default_backend) if default_backend in backend_options else 0
    image_backend = st.selectbox(
        "Backend",
        backend_options,
        index=backend_index,
        help="explainer = drawn whiteboard/stick figures (free, unique per scene). comfyui = AI photos."
    )
    if visual_style in ("whiteboard", "stick_figure") and image_backend != "explainer":
        st.info("Tip: use **explainer** backend for whiteboard/stick-figure styles.")
    if image_backend == "mock":
        st.warning("Mock mode draws text placeholders, not real images. Switch to comfyui or pollinations.")
    image_api_key = st.text_input(
        "Image API key (fal/runware only)",
        type="password",
        help="fal.ai → FAL_KEY. Runware → RUNWARE_API_KEY. Leave empty for pollinations/mock/comfyui."
    )

    st.markdown("**Video Motion**")
    default_motion = style_cfg.get("motion", "smooth_i2v")
    motion_options = ["smooth_i2v", "ffmpeg_kenburns", "draw_reveal", "hybrid"]
    motion_index = motion_options.index(default_motion) if default_motion in motion_options else 0
    motion_mode = st.selectbox(
        "Motion mode",
        motion_options,
        index=motion_index,
        help="smooth_i2v = real AI video motion (fal Wan, ~$0.05/scene). kenburns/draw = static image effects."
    )
    fal_key = st.text_input(
        "fal API key (required for smooth AI video)",
        type="password",
        help="Get one free at fal.ai → API Keys. ~$0.30–0.90 per full 6-scene short at 480p."
    )
    if motion_mode == "smooth_i2v" and not fal_key and not os.environ.get("FAL_KEY"):
        st.error("Smooth AI video needs a fal API key. Sign up at fal.ai (free credits available).")

    st.markdown("**Video & Audio**")
    tts_voice = st.selectbox(
        "TTS Voice",
        ["en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural", "en-AU-NatashaNeural"],
        index=0
    )
    add_music = st.checkbox("Add background music (if available)", value=False)

    st.markdown("**Captions**")
    caption_fontsize = st.slider("Caption font size", 24, 48, 32)
    caption_style = st.selectbox("Caption style", ["clean_outline", "box"], index=0)

    if st.button("🔄 Reset Current Run", use_container_width=True):
        reset_pipeline()
        st.rerun()

    st.divider()
    st.caption("Run the CLI version anytime with `python pipeline.py`")

# Load config (we will patch some values on the fly)
config_path = ROOT / "config.yaml"
if not config_path.exists():
    config_path = ROOT / "config.example.yaml"

# ------------------------------
# Polished Main Workflow UI
# ------------------------------
st.markdown("**Create a Short — All in one modern interface**")

# Topic
topic = st.text_input("Topic", value="5 mind-blowing facts about black holes", key="topic_main")

c1, c2 = st.columns(2)
with c1:
    if st.button("1. Generate / Edit Script", use_container_width=True):
        if topic:
            try:
                sa = ScriptAgent("config.yaml")
                sc = sa.generate(topic, visual_style=visual_style)
                st.session_state.script = sc
                st.success("Script ready!")
            except Exception as e:
                st.error(str(e)[:200])
with c2:
    if st.button("2. Generate Images (current provider)", use_container_width=True):
        if st.session_state.script:
            try:
                ia = configure_image_agent(ImageAgent(config_path), image_backend, image_api_key, visual_style)
                idir = IMAGES_DIR / slugify(st.session_state.script.title)
                with st.spinner(f"Generating images via {image_backend}..."):
                    paths = ia.generate_all_scenes(
                        st.session_state.script.scenes,
                        st.session_state.script.overall_style,
                        idir,
                    )
                st.session_state.image_paths = [str(p) for p in paths]
                st.success(f"Generated {len(paths)} images via {image_backend}")
            except Exception as e:
                st.error(str(e)[:500])

# Scene & Image Gallery (modern)
if st.session_state.script:
    st.markdown("### Scenes & Images")
    for i, scene in enumerate(st.session_state.script.scenes):
        with st.container(border=True):
            cols = st.columns([1, 2.5, 1.5])
            cols[0].markdown(f"**Scene {i+1}**")
            cols[1].write(scene.narration)
            if i < len(st.session_state.get("image_paths", [])):
                cols[2].image(st.session_state.image_paths[i], use_container_width=True)

# Video Assembly
st.markdown("### 3. Assemble & Preview")
if st.button("Assemble Video", type="primary", use_container_width=True):
    if st.session_state.script and st.session_state.image_paths:
        try:
            va = VideoAgent("config.yaml")
            outp = FINALS_DIR / f"{slugify(topic)}.mp4"
            final = va.assemble(st.session_state.script, [Path(p) for p in st.session_state.image_paths], outp)
            st.session_state.final_video = str(final)
        except Exception as e:
            st.error(str(e))

if st.session_state.final_video:
    st.video(st.session_state.final_video)
    with open(st.session_state.final_video, "rb") as f:
        st.download_button("⬇️ Download Final Short", f, file_name=Path(st.session_state.final_video).name)

# Load previous
st.divider()
with st.expander("📂 Load previous script or video", expanded=False):
    prev_scripts = load_previous_scripts()
    if prev_scripts:
        choices = {f"{s['title']} ({Path(s['path']).stem})": s for s in prev_scripts}
        selected = st.selectbox("Previous scripts", list(choices.keys()))
        if st.button("Load this script"):
            s = choices[selected]
            st.session_state.script = VideoScript.model_validate(s["data"])
            st.session_state.script_path = s["path"]
            st.session_state.image_paths = []  # user can re-generate
            st.session_state.final_video = None
            st.rerun()
    else:
        st.info("No previous scripts found yet.")

    prev_videos = list_previous_videos()
    if prev_videos:
        vid_choice = st.selectbox("Previous final videos", [v.name for v in prev_videos])
        if st.button("Load & preview this video"):
            st.session_state.final_video = str(FINALS_DIR / vid_choice)
            st.rerun()

# ------------------------------
# STEP 1: SCRIPT
# ------------------------------
st.header("1. Script Generation")

script = st.session_state.script

if not script:
    # Show Ollama status
    ollama_status = check_ollama_status()
    if not ollama_status["running"]:
        st.warning(f"⚠️ Ollama server not reachable: {ollama_status.get('error')}")
        st.info("Start it with: `ollama serve`\nThen pull a small model, e.g.:\n`ollama pull qwen2.5:3b`")
    elif ollama_status["count"] == 0:
        st.warning("⚠️ Ollama is running but **no models are installed**.")
        st.info("Run this in your terminal:\n`ollama pull qwen2.5:3b`  (small & good for 4GB VRAM)\nThen refresh this page.")

    col_g, col_demo = st.columns([2, 1])
    with col_g:
        if st.button("📝 Generate Script", type="primary", disabled=not topic):
            with st.spinner(f"Generating script with {llm_model}..."):
                try:
                    script_agent = ScriptAgent(config_path)
                    # Temporarily override the model from sidebar
                    scripting_cfg = script_agent._get_scripting_cfg()
                    if "ollama" not in scripting_cfg:
                        scripting_cfg["ollama"] = {}
                    scripting_cfg["ollama"]["model"] = llm_model
                    new_script = script_agent.generate(topic, visual_style=visual_style)
                    st.session_state.script = new_script
                    st.session_state.script_path = save_script(new_script, topic)
                    st.session_state.image_paths = []
                    st.session_state.final_video = None
                    st.success(f"Script generated: **{new_script.title}**")
                except Exception as e:
                    err_msg = str(e)
                    st.error("Failed to generate script")
                    if "404" in err_msg or "Not Found" in err_msg or "connection" in err_msg.lower():
                        st.warning("**Common cause:** Ollama server not running or required model not pulled.")
                        st.code(f"ollama serve\nollama pull {llm_model}", language="bash")
                    else:
                        st.code(err_msg)
                    if st.checkbox("Show full traceback"):
                        st.exception(e)

    with col_demo:
        if st.button("🧪 Load Demo Script (no LLM)"):
            demo_path = SCRIPTS_DIR / "sample_blackhole.json"
            if demo_path.exists():
                with open(demo_path) as f:
                    data = json.load(f)
                st.session_state.script = VideoScript.model_validate(data)
                st.session_state.script_path = str(demo_path)
                st.session_state.image_paths = []
                st.session_state.final_video = None
                st.success("Loaded demo black hole script")
                st.rerun()
            else:
                st.warning("Demo script not found")
else:
    st.success(f"✅ Script ready: **{script.title}**")

# Script preview + editing
if script:
    with st.container(border=True):
        st.subheader("Script Details")
        st.write(f"**Hook:** {script.hook}")
        st.write(f"**Style hint:** {script.overall_style[:140]}...")

        st.markdown("### Scenes")
        edited_scenes = []

        for i, scene in enumerate(script.scenes):
            with st.expander(f"Scene {scene.id} — {scene.narration[:60]}...", expanded=(i == 0)):
                new_narration = st.text_area(
                    "Narration (spoken text)",
                    value=scene.narration,
                    key=f"narration_{i}",
                    height=70
                )
                new_prompt = st.text_area(
                    "Image prompt",
                    value=scene.image_prompt,
                    key=f"prompt_{i}",
                    height=90
                )
                edited_scenes.append({
                    "id": scene.id,
                    "narration": new_narration,
                    "image_prompt": new_prompt,
                    "duration_hint_sec": scene.duration_hint_sec,
                    "notes": scene.notes,
                })

        if st.button("💾 Save Edits to Script"):
            # Rebuild script object
            new_data = script.model_dump()
            new_data["scenes"] = edited_scenes
            st.session_state.script = VideoScript.model_validate(new_data)
            if st.session_state.script_path:
                Path(st.session_state.script_path).write_text(
                    json.dumps(st.session_state.script.model_dump(), indent=2)
                )
            st.success("Edits saved!")
            st.rerun()

        col_regen, col_clear = st.columns(2)
        if col_regen.button("🔁 Regenerate Script from Topic"):
            reset_pipeline()
            st.rerun()

# ------------------------------
# STEP 2: IMAGES
# ------------------------------
st.header("2. Scene Images")

if not script:
    st.info("Generate or load a script first.")
else:
    img_col1, img_col2 = st.columns([1, 3])

    with img_col1:
        if st.button("🖼️ Generate / Refresh Images", disabled=not script):
            with st.spinner("Generating scene images..."):
                try:
                    image_agent = configure_image_agent(ImageAgent(config_path), image_backend, image_api_key, visual_style)

                    slug = slugify(script.title)
                    out_dir = IMAGES_DIR / slug
                    out_dir.mkdir(parents=True, exist_ok=True)

                    paths = image_agent.generate_all_scenes(
                        script.scenes,
                        style=script.overall_style,
                        images_dir=out_dir,
                    )
                    st.session_state.image_paths = [str(p) for p in paths]
                    st.success(f"Generated {len(paths)} images")
                except Exception as e:
                    st.error(f"Image generation failed: {e}")

    with img_col2:
        if st.button("🧹 Clear Images"):
            st.session_state.image_paths = []

    # Display images
    image_paths = st.session_state.get("image_paths", [])
    if image_paths:
        st.markdown("**Current images**")
        cols = st.columns(min(5, len(image_paths)))
        for idx, path in enumerate(image_paths):
            with cols[idx % len(cols)]:
                try:
                    st.image(path, caption=f"Scene {idx+1}", use_container_width=True)
                except Exception:
                    st.warning(f"Could not display {Path(path).name}")

        if len(image_paths) != len(script.scenes):
            st.warning("Number of images doesn't match number of scenes. Regenerate images.")
    else:
        st.caption("No images generated yet for this script.")

# ------------------------------
# STEP 3: VIDEO ASSEMBLY
# ------------------------------
st.header("3. Assemble Video")

if not script or not st.session_state.get("image_paths"):
    st.info("You need both a script and generated images before assembling video.")
else:
    assemble_cols = st.columns([1, 1, 1])
    with assemble_cols[0]:
        if st.button("🎥 Assemble Video", type="primary"):
            with st.spinner("Generating audio + creating motion clips + burning captions... This can take a minute."):
                try:
                    video_agent = VideoAgent(config_path)
                    video_agent.motion_mode = motion_mode
                    if fal_key:
                        os.environ["FAL_KEY"] = fal_key
                    video_agent.captions_cfg = {
                        "fontsize": caption_fontsize,
                        "style": caption_style,
                        "margin_v": 200,
                        "margin_lr": 70,
                    }

                    slug = slugify(script.title)
                    out_path = FINALS_DIR / f"{slug}_{datetime.now().strftime('%H%M%S')}.mp4"

                    # Convert string paths back to Path
                    img_paths = [Path(p) for p in st.session_state.image_paths]

                    final = video_agent.assemble(
                        script=script,
                        image_paths=img_paths,
                        output_video=out_path,
                        voice=tts_voice,
                        add_music=add_music,
                    )
                    st.session_state.final_video = str(final)
                    st.success("Video assembled successfully!")
                except Exception as e:
                    st.error(f"Video assembly failed: {e}")
                    st.exception(e)

    # Show final video if available
    if st.session_state.get("final_video"):
        video_path = st.session_state.final_video
        st.subheader("Final Video")
        try:
            st.video(video_path)
        except Exception:
            st.warning("Could not preview video. File might still be usable.")

        col_dl, col_open = st.columns(2)
        with col_dl:
            with open(video_path, "rb") as f:
                st.download_button(
                    "⬇️ Download MP4",
                    data=f,
                    file_name=Path(video_path).name,
                    mime="video/mp4",
                    use_container_width=True
                )
        with col_open:
            st.caption(f"Saved at: `{video_path}`")

# ------------------------------
# Full pipeline helper
# ------------------------------
# ------------------------------
# Footer & Tips
# ------------------------------
st.divider()
with st.expander("📜 Tips for pro results"):
    st.markdown("""
    - **Scripting**: ollama (free/local) or groq (fast & cheap).
    - **Images**: pollinations (free) • fal.ai / runware (cheap paid) • ComfyUI (local open-source).
    - **All control in UI** — no need to edit yaml for providers/keys/models.
    - **Local images**: ComfyUI is installed at `~/ComfyUI`. Start with `bash scripts/start_comfyui.sh`.
    - **Smooth AI video**: Motion → `smooth_i2v` + fal API key (~$0.05/scene at 480p).
    """)

st.caption("ShortsForge — Polished multi-backend AI short video studio. Local-first or cheap APIs.")