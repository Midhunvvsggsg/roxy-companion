# Making Your Own Sprite Pack for Kokoro-Term

Kokoro-Term features a layered, real-time 2D anime avatar compositor capable of autonomous breathing, blinking, head sway, emotion transitions, and audio-synchronized lip-sync. This guide walks you through creating, exporting, slicing, and configuring a custom sprite pack for any character.

---

## 1. Canvas & Art Specifications

- **Master Canvas Size**: 1024×1024 pixels (Square 1:1 aspect ratio)
- **Format**: 32-bit RGBA PNG with alpha transparency
- **Color Space**: sRGB
- **Style**: 2D anime cel-shaded character bust portrait, front-facing, head upright
- **Background**: Transparent for layers; flat neutral light gray (`#F0F0F0`) if creating full-frame variant sheets for the slicer.

---

## 2. Layer Architecture & Z-Order

The compositor composites transparent PNG layers strictly ordered by their `z_index`. Head features receive breathing and speaking sway offsets relative to the base body.

| Layer Key | Group | Default Z-Index | Description & Usage |
| :--- | :--- | :--- | :--- |
| `base` | `base` | 10 | Hair back, neck, robe/collar, hat, and ears. |
| `blush` | `overlay` | 15 | Soft pink cheek fluster for embarrassed / happy states. |
| `sweat` | `overlay` | 15 | Sweat drops for thinking / nervous states. |
| `eyes_open` | `eyes` | 20 | Calm, default bright open eyes. |
| `eyes_half` | `eyes` | 20 | Half-closed eyes used during 120ms blink phases and shy states. |
| `eyes_closed` | `eyes` | 20 | Fully shut eyes for blinks and joyful smiles. |
| `brows_neutral`| `brows` | 21 | Default calm arched eyebrows. |
| `brows_angry`  | `brows` | 21 | Slanted inward for annoyed or pouting expressions. |
| `brows_sad`    | `brows` | 21 | Slanted outward for sorrow or vulnerability. |
| `brows_surprised`| `brows` | 21 | Raised high on the forehead. |
| `mouth_closed` | `mouth` | 22 | Small closed resting mouth. |
| `mouth_a`      | `mouth` | 22 | Open /a/ shape for broad vowels. |
| `mouth_i`      | `mouth` | 22 | Wide /i/ shape for smiling and sharp consonants. |
| `mouth_u`      | `mouth` | 22 | Compact rounded /u/ shape for soft speech and pouts. |
| `mouth_e`      | `mouth` | 22 | Mid-open /e/ shape. |
| `mouth_o`      | `mouth` | 22 | Tall rounded /o/ shape for surprise and open syllables. |
| `hair_front`   | `overlay` | 40 | Bangs and framing sidelocks drawn on top of eyes/brows. |

---

## 3. Exporting Layers from Krita

If you draw directly in **Krita**:

1. **Set Document Resolution**: Create a `1024 x 1024` document at 72 or 300 DPI.
2. **Organize Layer Groups**: Structure your layer stack to match the table above:
   ```text
   📁 [40] hair_front
   📁 [22] mouth
      ├── mouth_closed
      ├── mouth_a
      ├── mouth_i
      ├── mouth_u
      ├── mouth_e
      └── mouth_o
   📁 [21] brows
      ├── brows_neutral
      ├── brows_angry
      ├── brows_sad
      └── brows_surprised
   📁 [20] eyes
      ├── eyes_open
      ├── eyes_half
      └── eyes_closed
   📁 [15] overlays
      ├── blush
      └── sweat
   📁 [10] base
   ```
3. **Exporting as Full-Frame Layers**:
   - Go to **Tools > Scripts > Export Layers**.
   - Choose an output folder (e.g. `characters/<name>/avatar/layers/`).
   - Format: `PNG` (Save with alpha channel, uncompressed).
4. **Exporting Full-Frame Variant Sheets (For the Slicer)**:
   - Alternatively, toggle visibility to produce full composite snapshots:
     - `base.png` (neutral face, closed mouth, open eyes)
     - `eyes_closed.png`
     - `eyes_half.png`
     - `mouth_a.png`, `mouth_i.png`, `mouth_u.png`, `mouth_e.png`, `mouth_o.png`
     - `brows_angry.png`, `brows_sad.png`, `brows_surprised.png`
     - `emotion_happy.png`, `emotion_embarrassed.png`, `emotion_thinking.png`
   - Save these to `assets_in/<name>/`.

---

## 4. Using the Automated Expression Slicer

The expression slicer diffs variant images against `base.png`, checks for misalignment or accidental scaling, crops bounding boxes, extracts transparent PNGs, and generates `manifest.yaml` automatically.

```bash
uv run python scripts/slice_expressions.py \
  --input assets_in/roxy \
  --output characters/roxy/avatar \
  --character roxy \
  --preview
```

### Misalignment Protection
If a full-frame variant was accidentally moved by a few pixels or resized in your drawing software, the slicer flags a warning:
```text
⚠️ [WARNING] Variant 'brows_angry' may be shifted/rescaled! Detected 340 pixel diffs outside (380, 345, 644, 415)
```
This prevents registration drift across blinking and speaking frames.

---

## 5. Manifest Specification (`manifest.yaml`)

Each avatar folder contains a `manifest.yaml` configuring layers, emotion mappings, and animation parameters:

```yaml
character: roxy
canvas_size: [1024, 1024]
layers:
  base:
    file: layers/base.png
    z_index: 10
    offset: [0, 0]
    size: [1024, 1024]
    group: base
  blush:
    file: layers/blush.png
    z_index: 15
    offset: [0, 0]
    size: [1024, 1024]
    group: overlay
  hair_front:
    file: layers/hair_front.png
    z_index: 40
    offset: [0, 0]
    size: [1024, 1024]
    group: overlay

eye_states:
  open:
    file: layers/eyes_open.png
    z_index: 20
    offset: [370, 385]
    size: [284, 85]
    group: eyes
  half:
    file: layers/eyes_half.png
    z_index: 20
    offset: [370, 385]
    size: [284, 85]
    group: eyes
  closed:
    file: layers/eyes_closed.png
    z_index: 20
    offset: [370, 385]
    size: [284, 85]
    group: eyes

emotions:
  neutral:
    eyes: open
    brows: neutral
    mouth: closed
    blush: false
    overlays: []
  embarrassed:
    eyes: half
    brows: neutral
    mouth: u
    blush: true
    overlays: []
  happy:
    eyes: closed
    brows: neutral
    mouth: i
    blush: true
    overlays: []

animation:
  breathing_frequency: 0.25      # Hz
  breathing_amplitude_px: 8.0    # Pixels
  blink_interval_min: 3.0        # Seconds
  blink_interval_max: 6.0        # Seconds
  blink_duration: 0.12           # Seconds
  head_sway_amplitude_px: 4.0    # Pixels
```

---

## 6. Runtime In-App Commands

While running Kokoro-Term, you can test and inspect your sprite pack in real time:

- `/avatar validate`: Verifies all referenced files exist and match canvas dimensions.
- `/avatar preview`: Cycles through all emotions and mouth visemes automatically.
- `/avatar backend <auto|window|terminal>`: Switches between the desktop PySide6 window and in-terminal ANSI half-block renderer.
- `/emotion <name>`: Manually sets the companion's emotion (`neutral`, `happy`, `embarrassed`, `angry`, `sad`, `surprised`, `thinking`).
- `/testtalk`: Plays a synthetic speech audio sample with synchronized amplitude lip-sync.
- `/perf`: Displays compositor telemetry (FPS, composite count, frame latency in ms).

---

## 7. Display Backend Notes

1. **Desktop Window Backend (`AvatarWindow`)**:
   - Runs in an isolated PySide6 subprocess over localhost socket IPC (`127.0.0.1:18492`).
   - If the window is closed, the main TUI chat never crashes.
   - *Wayland Note*: On modern Linux Wayland compositors (GNOME 40+, Sway), client-side window positioning and `WindowStaysOnTopHint` depend on compositor policies. The window renders with full alpha transparency.
2. **Terminal In-TUI Backend (`TerminalAvatarBackend`)**:
   - Gracefully falls back from Kitty graphics to Sixel to half-block Unicode (`▀▄`) ANSI rendering.
   - Recomposites only when state changes, operating at near 0% idle CPU usage.
