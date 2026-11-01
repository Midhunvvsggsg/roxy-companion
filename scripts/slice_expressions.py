#!/usr/bin/env python3
"""
Expression Slicer & Manifest Generator.
Diffs full-frame expression variants against base.png, detects changed regions within
facial bounding boxes, performs alignment checks, exports cropped transparent PNGs
with coordinate offsets, and writes characters/<name>/avatar/manifest.yaml.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image
import yaml


# Configurable Face Region Bounding Boxes on 1024x1024 canvas (xmin, ymin, xmax, ymax)
DEFAULT_FEATURE_BOXES = {
    "eyes": (370, 385, 654, 470),
    "brows": (380, 345, 644, 415),
    "mouth": (460, 495, 564, 565),
    "blush": (350, 420, 674, 505),
}

# Mapping of file prefixes to expected feature box
FEATURE_BOX_MAP = {
    "eyes": "eyes",
    "brows": "brows",
    "mouth": "mouth",
    "blush": "blush",
    "emotion": None, # Multi-feature composite
}


def check_misalignment(
    base_arr: np.ndarray,
    variant_arr: np.ndarray,
    allowed_box: tuple[int, int, int, int] | None,
    threshold: int = 15,
    max_outside_pixels: int = 80,
) -> tuple[bool, int]:
    """
    Check if pixels outside the expected bounding box shifted (indicating scaling/misalignment).
    Returns (is_misaligned, outside_diff_count).
    """
    diff = np.abs(variant_arr.astype(int) - base_arr.astype(int))
    # Pixel differs if any RGB channel diff exceeds threshold
    diff_mask = np.any(diff[:, :, :3] > threshold, axis=2)

    if allowed_box is None:
        # No strict box (e.g. emotion variant)
        return False, 0

    xmin, ymin, xmax, ymax = allowed_box
    outside_mask = np.ones_like(diff_mask, dtype=bool)
    outside_mask[ymin:ymax, xmin:xmax] = False

    outside_diff_count = int(np.sum(diff_mask & outside_mask))
    is_misaligned = outside_diff_count > max_outside_pixels
    return is_misaligned, outside_diff_count


def slice_variant(
    base_img: Image.Image,
    variant_img: Image.Image,
    feature_name: str,
    feature_box: tuple[int, int, int, int] | None,
    out_dir: Path,
    out_name: str,
) -> tuple[str, int, int, int, int]:
    """
    Detect the changed region between variant and base, extract transparent PNG,
    and return (filename, offset_x, offset_y, width, height).
    """
    base_arr = np.array(base_img.convert("RGBA"))
    var_arr = np.array(variant_img.convert("RGBA"))

    is_misaligned, outside_diffs = check_misalignment(base_arr, var_arr, feature_box)
    if is_misaligned:
        print(f"⚠️  [WARNING] Variant '{out_name}' may be shifted/rescaled! Detected {outside_diffs} pixel diffs outside {feature_box}")

    diff = np.abs(var_arr.astype(int) - base_arr.astype(int))
    diff_mask = np.any(diff[:, :, :3] > 8, axis=2)

    # Restrict to feature box if specified
    if feature_box is not None:
        xmin, ymin, xmax, ymax = feature_box
        box_mask = np.zeros_like(diff_mask, dtype=bool)
        box_mask[ymin:ymax, xmin:xmax] = True
        diff_mask = diff_mask & box_mask

    y_indices, x_indices = np.where(diff_mask)
    if len(x_indices) == 0:
        # Fallback to feature box if diff was minute
        if feature_box:
            xmin, ymin, xmax, ymax = feature_box
        else:
            xmin, ymin, xmax, ymax = 0, 0, base_img.width, base_img.height
    else:
        # Expand by 4px padding
        pad = 4
        xmin = max(0, int(np.min(x_indices)) - pad)
        ymin = max(0, int(np.min(y_indices)) - pad)
        xmax = min(base_img.width, int(np.max(x_indices)) + pad)
        ymax = min(base_img.height, int(np.max(y_indices)) + pad)

    # Extract cropped region from variant image
    cropped_patch = variant_img.crop((xmin, ymin, xmax, ymax)).convert("RGBA")
    
    # Save sliced transparent PNG
    filename = f"{out_name}.png"
    cropped_patch.save(out_dir / filename)

    width = xmax - xmin
    height = ymax - ymin
    return filename, xmin, ymin, width, height


def slice_directory(
    assets_dir: str | Path,
    output_avatar_dir: str | Path,
    character_name: str = "roxy",
) -> Path:
    assets_path = Path(assets_dir)
    avatar_path = Path(output_avatar_dir)
    layers_out = avatar_path / "layers"
    layers_out.mkdir(parents=True, exist_ok=True)

    base_file = assets_path / "base.png"
    if not base_file.exists():
        raise FileNotFoundError(f"Missing base.png in {assets_path}")

    base_img = Image.open(base_file).convert("RGBA")
    # Save base layer as background
    base_img.save(layers_out / "base.png")

    manifest = {
        "character": character_name,
        "canvas_size": [base_img.width, base_img.height],
        "layers": {
            "base": {
                "file": "layers/base.png",
                "z_index": 10,
                "offset": [0, 0],
                "size": [base_img.width, base_img.height],
                "group": "base",
            }
        },
        "eye_states": {},
        "brow_states": {},
        "mouth_states": {},
        "emotions": {
            "neutral": {"eyes": "open", "brows": "neutral", "mouth": "closed", "blush": False, "overlays": []},
            "happy": {"eyes": "closed", "brows": "neutral", "mouth": "i", "blush": True, "overlays": []},
            "embarrassed": {"eyes": "half", "brows": "neutral", "mouth": "u", "blush": True, "overlays": []},
            "blush": {"eyes": "half", "brows": "neutral", "mouth": "u", "blush": True, "overlays": []},
            "angry": {"eyes": "open", "brows": "angry", "mouth": "u", "blush": True, "overlays": []},
            "pout": {"eyes": "open", "brows": "angry", "mouth": "u", "blush": True, "overlays": []},
            "sad": {"eyes": "half", "brows": "sad", "mouth": "closed", "blush": False, "overlays": []},
            "surprised": {"eyes": "open", "brows": "surprised", "mouth": "o", "blush": True, "overlays": []},
            "thinking": {"eyes": "half", "brows": "neutral", "mouth": "closed", "blush": False, "overlays": ["sweat"]},
        },
        "animation": {
            "breathing_frequency": 0.25, # Hz
            "breathing_amplitude_px": 8.0,
            "blink_interval_min": 3.0,
            "blink_interval_max": 6.0,
            "blink_duration": 0.12,
            "head_sway_amplitude_px": 4.0,
        },
    }

    print(f"Slicing expressions from '{assets_path}' into '{layers_out}'...")

    for var_path in sorted(assets_path.glob("*.png")):
        if var_path.name == "base.png":
            continue

        var_name = var_path.stem
        var_img = Image.open(var_path).convert("RGBA")

        # Determine feature group
        feature_key = var_name.split("_")[0]
        box_type = FEATURE_BOX_MAP.get(feature_key, None)
        feature_box = DEFAULT_FEATURE_BOXES.get(box_type) if box_type else None

        filename, ox, oy, w, h = slice_variant(
            base_img=base_img,
            variant_img=var_img,
            feature_name=feature_key,
            feature_box=feature_box,
            out_dir=layers_out,
            out_name=var_name,
        )

        layer_info = {
            "file": f"layers/{filename}",
            "z_index": 20,
            "offset": [ox, oy],
            "size": [w, h],
            "group": feature_key,
        }

        if var_name.startswith("eyes_"):
            state = var_name[len("eyes_"):]
            manifest["eye_states"][state] = layer_info
        elif var_name.startswith("brows_"):
            state = var_name[len("brows_"):]
            manifest["brow_states"][state] = layer_info
        elif var_name.startswith("mouth_"):
            state = var_name[len("mouth_"):]
            manifest["mouth_states"][state] = layer_info
        else:
            manifest["layers"][var_name] = layer_info

    # If eyes_open not explicitly sliced, slice from base if layers exist
    if "open" not in manifest["eye_states"] and (layers_out / "eyes_open.png").exists():
        manifest["eye_states"]["open"] = {
            "file": "layers/eyes_open.png",
            "z_index": 20,
            "offset": [0, 0],
            "size": [1024, 1024],
            "group": "eyes",
        }
    if "neutral" not in manifest["brow_states"] and (layers_out / "brows_neutral.png").exists():
        manifest["brow_states"]["neutral"] = {
            "file": "layers/brows_neutral.png",
            "z_index": 21,
            "offset": [0, 0],
            "size": [1024, 1024],
            "group": "brows",
        }
    if "closed" not in manifest["mouth_states"] and (layers_out / "mouth_closed.png").exists():
        manifest["mouth_states"]["closed"] = {
            "file": "layers/mouth_closed.png",
            "z_index": 22,
            "offset": [0, 0],
            "size": [1024, 1024],
            "group": "mouth",
        }

    # Add overlays if present
    for overlay in ("blush", "sweat", "hair_front"):
        if (layers_out / f"{overlay}.png").exists():
            z = 40 if overlay == "hair_front" else 15
            manifest["layers"][overlay] = {
                "file": f"layers/{overlay}.png",
                "z_index": z,
                "offset": [0, 0],
                "size": [1024, 1024],
                "group": "overlay",
            }

    # Write manifest.yaml
    manifest_file = avatar_path / "manifest.yaml"
    with open(manifest_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)

    print(f"Generated manifest at: {manifest_file}")
    return manifest_file


def run_preview(manifest_path: str | Path) -> None:
    """Preview cycling through expressions and mouth shapes in terminal."""
    from kokoro_term.avatar.renderer import image_to_half_block
    from kokoro_term.avatar.sprites import SpritePack

    pack = SpritePack(Path(manifest_path).parent)
    print("\n--- Cycling Expressions Preview ---")
    emotions = ["neutral", "happy", "embarrassed", "angry", "sad", "surprised", "thinking"]
    for emo in emotions:
        frame = pack.get_composite_frame(emotion=emo, is_speaking=False, time_sec=time.time())
        if frame:
            print(f"\n[Emotion: {emo}]")
            ansi = image_to_half_block(frame, width=28, height=28)
            print(ansi)
        time.sleep(0.5)

    print("\n--- Cycling Mouth Shapes (Lip-Sync) ---")
    mouths = ["closed", "a", "i", "u", "e", "o"]
    for m in mouths:
        if pack.compositor is not None:
            from kokoro_term.avatar.compositor import AvatarState
            frame = pack.compositor.composite(AvatarState(emotion="neutral", mouth_state=m))
        else:
            frame = pack.get_composite_frame(emotion="neutral", is_speaking=True, time_sec=time.time())
        if frame:
            print(f"\n[Mouth: {m}]")
            ansi = image_to_half_block(frame, width=28, height=28)
            print(ansi)
        time.sleep(0.3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Expression Slicer & Manifest Generator")
    parser.add_argument("--input", default="assets_in/roxy", help="Directory containing base.png and full-frame variants")
    parser.add_argument("--output", default="characters/roxy/avatar", help="Destination character avatar directory")
    parser.add_argument("--character", default="roxy", help="Character identifier")
    parser.add_argument("--preview", action="store_true", help="Cycle through all expressions after slicing")
    args = parser.parse_args()

    m_path = slice_directory(args.input, args.output, args.character)
    if args.preview:
        run_preview(m_path)
