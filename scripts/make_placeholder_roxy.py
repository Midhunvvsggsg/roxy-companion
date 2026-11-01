#!/usr/bin/env python3
"""
Procedural 2D Anime Avatar Generator for Roxy Migurdia (Mushoku Tensei).
Generates high-resolution 1024x1024 layered transparent PNGs with 4x supersampling (4096x4096).
No external native dependencies (pure Pillow).
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter


# Color Palette (Accurate Roxy Migurdia anime palette)
SKIN_BASE = (255, 236, 224, 255)
SKIN_SHADOW = (240, 208, 192, 255)
HAIR_BASE = (104, 164, 217, 255)      # Light sky blue
HAIR_SHADOW = (68, 117, 169, 255)     # Deep twilight blue
HAIR_HIGHLIGHT = (168, 208, 245, 255) # Soft sheen
ROBE_BASE = (37, 44, 66, 255)         # Dark navy mage robe
ROBE_SHADOW = (24, 28, 44, 255)
ROBE_TRIM = (196, 158, 88, 255)       # Gold magician embroidery
COLLAR_WHITE = (248, 248, 252, 255)
COLLAR_SHADOW = (216, 218, 230, 255)
HAT_BASE = (32, 38, 56, 255)
HAT_SHADOW = (20, 24, 38, 255)
HAT_RIBBON = (156, 54, 76, 255)       # Wine red/crimson hat band
EYE_BLUE_OUTER = (30, 90, 180, 255)
EYE_BLUE_MID = (45, 140, 240, 255)
EYE_BLUE_LIGHT = (120, 200, 255, 255)
PUPIL_DARK = (16, 40, 90, 255)
LINE_COLOR = (42, 36, 48, 255)        # Clean dark anime lineart
BLUSH_PINK = (255, 120, 144, 160)
MOUTH_INNER = (180, 50, 70, 255)
MOUTH_LIP = (210, 80, 100, 255)
TEETH_WHITE = (250, 250, 255, 255)


def draw_antialiased_polygon(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], fill, outline=None, width=1):
    draw.polygon(points, fill=fill)
    if outline:
        draw.line(points + [points[0]], fill=outline, width=width)


def create_roxy_layers(output_dir: str | Path = "characters/roxy/avatar/layers") -> dict[str, Path]:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 4x Supersampling for ultra-crisp lineart and soft cel shading
    S = 4
    W = 1024 * S
    H = 1024 * S

    def new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        return im, dr

    def downscale(im: Image.Image, filename: str) -> Path:
        final_img = im.resize((1024, 1024), Image.Resampling.LANCZOS)
        p = out_path / filename
        final_img.save(p, "PNG")
        return p

    created_files = {}

    # -------------------------------------------------------------
    # 1. BODY_BACK (Hat back, Hair back/braids, Neck, Robe, Collar, Hat)
    # -------------------------------------------------------------
    im, dr = new_canvas()

    # Hair Back (twin low braids falling past shoulders)
    # Left braid
    dr.polygon([
        (260 * S, 480 * S), (220 * S, 620 * S), (240 * S, 760 * S),
        (280 * S, 880 * S), (330 * S, 880 * S), (320 * S, 720 * S),
        (330 * S, 560 * S)
    ], fill=HAIR_SHADOW, outline=LINE_COLOR, width=3 * S)
    dr.polygon([
        (275 * S, 500 * S), (240 * S, 630 * S), (255 * S, 750 * S),
        (290 * S, 860 * S), (315 * S, 860 * S), (305 * S, 710 * S),
        (315 * S, 560 * S)
    ], fill=HAIR_BASE)

    # Right braid
    dr.polygon([
        (764 * S, 480 * S), (804 * S, 620 * S), (784 * S, 760 * S),
        (744 * S, 880 * S), (694 * S, 880 * S), (704 * S, 720 * S),
        (694 * S, 560 * S)
    ], fill=HAIR_SHADOW, outline=LINE_COLOR, width=3 * S)
    dr.polygon([
        (749 * S, 500 * S), (784 * S, 630 * S), (769 * S, 750 * S),
        (734 * S, 860 * S), (709 * S, 860 * S), (719 * S, 710 * S),
        (709 * S, 560 * S)
    ], fill=HAIR_BASE)

    # Hair bands on braids
    dr.rectangle([270 * S, 840 * S, 320 * S, 860 * S], fill=HAT_RIBBON, outline=LINE_COLOR, width=2 * S)
    dr.rectangle([704 * S, 840 * S, 754 * S, 860 * S], fill=HAT_RIBBON, outline=LINE_COLOR, width=2 * S)

    # Shoulders & Robe Back
    dr.polygon([
        (200 * S, 760 * S), (360 * S, 650 * S), (664 * S, 650 * S),
        (824 * S, 760 * S), (870 * S, 1024 * S), (154 * S, 1024 * S)
    ], fill=ROBE_BASE, outline=LINE_COLOR, width=4 * S)

    # Robe shading
    dr.polygon([
        (154 * S, 1024 * S), (240 * S, 800 * S), (360 * S, 850 * S),
        (330 * S, 1024 * S)
    ], fill=ROBE_SHADOW)
    dr.polygon([
        (870 * S, 1024 * S), (784 * S, 800 * S), (664 * S, 850 * S),
        (694 * S, 1024 * S)
    ], fill=ROBE_SHADOW)

    # White Clerical/Magician Collar
    dr.polygon([
        (380 * S, 630 * S), (512 * S, 740 * S), (644 * S, 630 * S),
        (590 * S, 610 * S), (512 * S, 625 * S), (434 * S, 610 * S)
    ], fill=COLLAR_WHITE, outline=LINE_COLOR, width=3 * S)
    # Gold brooch / collar trim
    dr.ellipse([496 * S, 720 * S, 528 * S, 752 * S], fill=ROBE_TRIM, outline=LINE_COLOR, width=2 * S)
    dr.ellipse([502 * S, 726 * S, 522 * S, 746 * S], fill=EYE_BLUE_MID)

    # Slender Neck & Face Contour
    # Neck shadow
    dr.polygon([(464 * S, 540 * S), (560 * S, 540 * S), (570 * S, 640 * S), (454 * S, 640 * S)], fill=SKIN_SHADOW)
    # Neck
    dr.polygon([(472 * S, 540 * S), (552 * S, 540 * S), (560 * S, 630 * S), (464 * S, 630 * S)], fill=SKIN_BASE)

    # Face Shape (Petite, pointed anime chin, soft jaw)
    dr.polygon([
        (350 * S, 390 * S), (356 * S, 470 * S), (400 * S, 540 * S),
        (512 * S, 600 * S), (624 * S, 540 * S), (668 * S, 470 * S),
        (674 * S, 390 * S), (512 * S, 370 * S)
    ], fill=SKIN_BASE, outline=LINE_COLOR, width=3 * S)

    # Nose (Minimal anime dot/dash)
    dr.line([(510 * S, 482 * S), (514 * S, 490 * S)], fill=LINE_COLOR, width=2 * S)

    # Ears
    dr.ellipse([336 * S, 420 * S, 360 * S, 470 * S], fill=SKIN_BASE, outline=LINE_COLOR, width=2 * S)
    dr.ellipse([664 * S, 420 * S, 688 * S, 470 * S], fill=SKIN_BASE, outline=LINE_COLOR, width=2 * S)

    # Roxy's Witch Hat:
    # Wide brim placed carefully ABOVE the eyes so it never covers brows/eyes
    # Cone back
    dr.polygon([
        (512 * S, 30 * S), (560 * S, 60 * S), (512 * S, 120 * S),
        (330 * S, 270 * S), (694 * S, 270 * S)
    ], fill=HAT_BASE, outline=LINE_COLOR, width=4 * S)
    # Hat ribbon band
    dr.polygon([(344 * S, 260 * S), (680 * S, 260 * S), (688 * S, 280 * S), (336 * S, 280 * S)], fill=HAT_RIBBON)
    # Wide brim curved upward
    dr.arc([200 * S, 240 * S, 824 * S, 330 * S], start=180, end=360, fill=LINE_COLOR, width=5 * S)
    dr.chord([204 * S, 246 * S, 820 * S, 326 * S], start=180, end=360, fill=HAT_BASE, outline=LINE_COLOR, width=4 * S)

    created_files["body_back"] = downscale(im, "body_back.png")

    # -------------------------------------------------------------
    # 2. HAIR_FRONT (Bangs across forehead, framing side locks)
    # -------------------------------------------------------------
    im, dr = new_canvas()

    # Left long side lock
    dr.polygon([
        (340 * S, 320 * S), (330 * S, 460 * S), (350 * S, 580 * S),
        (374 * S, 580 * S), (360 * S, 450 * S), (366 * S, 340 * S)
    ], fill=HAIR_BASE, outline=LINE_COLOR, width=3 * S)

    # Right long side lock
    dr.polygon([
        (684 * S, 320 * S), (694 * S, 460 * S), (674 * S, 580 * S),
        (650 * S, 580 * S), (664 * S, 450 * S), (658 * S, 340 * S)
    ], fill=HAIR_BASE, outline=LINE_COLOR, width=3 * S)

    # Side-swept front bangs (parted slightly, keeping eyes completely visible)
    # Left bang strand
    dr.polygon([
        (370 * S, 300 * S), (390 * S, 370 * S), (410 * S, 360 * S), (394 * S, 300 * S)
    ], fill=HAIR_BASE, outline=LINE_COLOR, width=2 * S)
    # Center-left parted bang
    dr.polygon([
        (406 * S, 290 * S), (430 * S, 380 * S), (454 * S, 370 * S), (434 * S, 290 * S)
    ], fill=HAIR_BASE, outline=LINE_COLOR, width=2 * S)
    # Center bang
    dr.polygon([
        (460 * S, 290 * S), (490 * S, 365 * S), (506 * S, 355 * S), (484 * S, 290 * S)
    ], fill=HAIR_BASE, outline=LINE_COLOR, width=2 * S)
    # Right-swept bang
    dr.polygon([
        (512 * S, 290 * S), (544 * S, 376 * S), (566 * S, 360 * S), (536 * S, 290 * S)
    ], fill=HAIR_BASE, outline=LINE_COLOR, width=2 * S)
    # Rightmost bang
    dr.polygon([
        (560 * S, 294 * S), (610 * S, 385 * S), (634 * S, 370 * S), (594 * S, 294 * S)
    ], fill=HAIR_BASE, outline=LINE_COLOR, width=2 * S)

    # Soft hair sheen highlight curve across forehead bangs
    dr.line([(380 * S, 330 * S), (450 * S, 335 * S)], fill=HAIR_HIGHLIGHT, width=3 * S)
    dr.line([(530 * S, 335 * S), (610 * S, 330 * S)], fill=HAIR_HIGHLIGHT, width=3 * S)

    created_files["hair_front"] = downscale(im, "hair_front.png")

    # -------------------------------------------------------------
    # 3. EYES: OPEN, HALF, CLOSED
    # -------------------------------------------------------------
    # Eyes Open
    im, dr = new_canvas()
    # Left eye outer & sclera
    dr.ellipse([400 * S, 404 * S, 464 * S, 452 * S], fill=(255, 255, 255, 255))
    # Iris gradient & pupil
    dr.ellipse([412 * S, 404 * S, 454 * S, 452 * S], fill=EYE_BLUE_OUTER)
    dr.ellipse([416 * S, 412 * S, 450 * S, 448 * S], fill=EYE_BLUE_MID)
    dr.ellipse([422 * S, 424 * S, 444 * S, 446 * S], fill=EYE_BLUE_LIGHT)
    dr.ellipse([426 * S, 416 * S, 440 * S, 434 * S], fill=PUPIL_DARK)
    # Eye specular glint
    dr.ellipse([418 * S, 410 * S, 428 * S, 420 * S], fill=(255, 255, 255, 255))
    dr.ellipse([436 * S, 434 * S, 442 * S, 440 * S], fill=(255, 255, 255, 230))
    # Eyelash line
    dr.arc([394 * S, 396 * S, 470 * S, 436 * S], start=190, end=350, fill=LINE_COLOR, width=4 * S)

    # Right eye outer & sclera
    dr.ellipse([560 * S, 404 * S, 624 * S, 452 * S], fill=(255, 255, 255, 255))
    dr.ellipse([570 * S, 404 * S, 612 * S, 452 * S], fill=EYE_BLUE_OUTER)
    dr.ellipse([574 * S, 412 * S, 608 * S, 448 * S], fill=EYE_BLUE_MID)
    dr.ellipse([580 * S, 424 * S, 602 * S, 446 * S], fill=EYE_BLUE_LIGHT)
    dr.ellipse([584 * S, 416 * S, 598 * S, 434 * S], fill=PUPIL_DARK)
    dr.ellipse([576 * S, 410 * S, 586 * S, 420 * S], fill=(255, 255, 255, 255))
    dr.ellipse([594 * S, 434 * S, 600 * S, 440 * S], fill=(255, 255, 255, 230))
    dr.arc([554 * S, 396 * S, 630 * S, 436 * S], start=190, end=350, fill=LINE_COLOR, width=4 * S)
    created_files["eyes_open"] = downscale(im, "eyes_open.png")

    # Eyes Half
    im, dr = new_canvas()
    # Left eye half
    dr.chord([400 * S, 416 * S, 464 * S, 454 * S], start=0, end=180, fill=(255, 255, 255, 255))
    dr.chord([412 * S, 418 * S, 454 * S, 452 * S], start=0, end=180, fill=EYE_BLUE_MID)
    dr.ellipse([424 * S, 424 * S, 442 * S, 442 * S], fill=PUPIL_DARK)
    dr.ellipse([418 * S, 422 * S, 426 * S, 430 * S], fill=(255, 255, 255, 255))
    dr.line([(396 * S, 420 * S), (468 * S, 420 * S)], fill=LINE_COLOR, width=4 * S)

    # Right eye half
    dr.chord([560 * S, 416 * S, 624 * S, 454 * S], start=0, end=180, fill=(255, 255, 255, 255))
    dr.chord([570 * S, 418 * S, 612 * S, 452 * S], start=0, end=180, fill=EYE_BLUE_MID)
    dr.ellipse([582 * S, 424 * S, 600 * S, 442 * S], fill=PUPIL_DARK)
    dr.ellipse([576 * S, 422 * S, 584 * S, 430 * S], fill=(255, 255, 255, 255))
    dr.line([(556 * S, 420 * S), (628 * S, 420 * S)], fill=LINE_COLOR, width=4 * S)
    created_files["eyes_half"] = downscale(im, "eyes_half.png")

    # Eyes Closed
    im, dr = new_canvas()
    # Curved peaceful closed eye lines with delicate lashes
    dr.arc([400 * S, 414 * S, 464 * S, 444 * S], start=20, end=160, fill=LINE_COLOR, width=4 * S)
    dr.arc([560 * S, 414 * S, 624 * S, 444 * S], start=20, end=160, fill=LINE_COLOR, width=4 * S)
    created_files["eyes_closed"] = downscale(im, "eyes_closed.png")

    # -------------------------------------------------------------
    # 4. EYEBROWS: NEUTRAL, ANGRY, SAD, SURPRISED
    # -------------------------------------------------------------
    # Brows Neutral (Calm, slightly serious)
    im, dr = new_canvas()
    dr.line([(404 * S, 390 * S), (460 * S, 386 * S)], fill=HAIR_SHADOW, width=3 * S)
    dr.line([(564 * S, 386 * S), (620 * S, 390 * S)], fill=HAIR_SHADOW, width=3 * S)
    created_files["brows_neutral"] = downscale(im, "brows_neutral.png")

    # Brows Angry / Pouty (Furrowed inward)
    im, dr = new_canvas()
    dr.line([(404 * S, 380 * S), (460 * S, 396 * S)], fill=HAIR_SHADOW, width=3 * S)
    dr.line([(564 * S, 396 * S), (620 * S, 380 * S)], fill=HAIR_SHADOW, width=3 * S)
    created_files["brows_angry"] = downscale(im, "brows_angry.png")

    # Brows Sad (Angled upward in center)
    im, dr = new_canvas()
    dr.line([(404 * S, 396 * S), (460 * S, 380 * S)], fill=HAIR_SHADOW, width=3 * S)
    dr.line([(564 * S, 380 * S), (620 * S, 396 * S)], fill=HAIR_SHADOW, width=3 * S)
    created_files["brows_sad"] = downscale(im, "brows_sad.png")

    # Brows Surprised (Arched high)
    im, dr = new_canvas()
    dr.arc([404 * S, 360 * S, 460 * S, 390 * S], start=200, end=340, fill=HAIR_SHADOW, width=3 * S)
    dr.arc([564 * S, 360 * S, 620 * S, 390 * S], start=200, end=340, fill=HAIR_SHADOW, width=3 * S)
    created_files["brows_surprised"] = downscale(im, "brows_surprised.png")

    # -------------------------------------------------------------
    # 5. MOUTHS: CLOSED, A, I, U, E, O
    # -------------------------------------------------------------
    # Mouth Closed (Small dignified tutor line)
    im, dr = new_canvas()
    dr.line([(496 * S, 526 * S), (528 * S, 526 * S)], fill=LINE_COLOR, width=3 * S)
    # Tiny soft lower lip shadow
    dr.line([(508 * S, 534 * S), (516 * S, 534 * S)], fill=SKIN_SHADOW, width=2 * S)
    created_files["mouth_closed"] = downscale(im, "mouth_closed.png")

    # Mouth A (Open talking/speaking shape)
    im, dr = new_canvas()
    dr.chord([490 * S, 514 * S, 534 * S, 544 * S], start=0, end=180, fill=MOUTH_INNER, outline=LINE_COLOR, width=2 * S)
    dr.rectangle([498 * S, 514 * S, 526 * S, 520 * S], fill=TEETH_WHITE)
    dr.chord([498 * S, 530 * S, 526 * S, 542 * S], start=0, end=180, fill=MOUTH_LIP)
    created_files["mouth_a"] = downscale(im, "mouth_a.png")

    # Mouth I (Wide horizontal smile/expression)
    im, dr = new_canvas()
    dr.chord([486 * S, 520 * S, 538 * S, 536 * S], start=0, end=180, fill=MOUTH_INNER, outline=LINE_COLOR, width=2 * S)
    dr.line([(486 * S, 522 * S), (538 * S, 522 * S)], fill=TEETH_WHITE, width=3 * S)
    created_files["mouth_i"] = downscale(im, "mouth_i.png")

    # Mouth U (Small rounded puckered cute mouth)
    im, dr = new_canvas()
    dr.ellipse([504 * S, 520 * S, 520 * S, 536 * S], fill=MOUTH_INNER, outline=LINE_COLOR, width=2 * S)
    created_files["mouth_u"] = downscale(im, "mouth_u.png")

    # Mouth E (Smiling open dialogue shape)
    im, dr = new_canvas()
    dr.polygon([
        (488 * S, 518 * S), (536 * S, 518 * S), (524 * S, 538 * S), (500 * S, 538 * S)
    ], fill=MOUTH_INNER, outline=LINE_COLOR, width=2 * S)
    dr.line([(492 * S, 520 * S), (532 * S, 520 * S)], fill=TEETH_WHITE, width=3 * S)
    created_files["mouth_e"] = downscale(im, "mouth_e.png")

    # Mouth O (Round surprised/excited vocal shape)
    im, dr = new_canvas()
    dr.ellipse([500 * S, 514 * S, 524 * S, 544 * S], fill=MOUTH_INNER, outline=LINE_COLOR, width=2 * S)
    dr.ellipse([504 * S, 532 * S, 520 * S, 542 * S], fill=MOUTH_LIP)
    created_files["mouth_o"] = downscale(im, "mouth_o.png")

    # -------------------------------------------------------------
    # 6. OVERLAYS: BLUSH & SWEAT
    # -------------------------------------------------------------
    # Blush
    im, dr = new_canvas()
    # Left cheek blush lines & soft oval
    dr.ellipse([370 * S, 450 * S, 430 * S, 480 * S], fill=BLUSH_PINK)
    dr.line([(385 * S, 455 * S), (395 * S, 475 * S)], fill=(240, 90, 120, 200), width=2 * S)
    dr.line([(400 * S, 455 * S), (410 * S, 475 * S)], fill=(240, 90, 120, 200), width=2 * S)
    dr.line([(415 * S, 455 * S), (425 * S, 475 * S)], fill=(240, 90, 120, 200), width=2 * S)

    # Right cheek blush lines & soft oval
    dr.ellipse([594 * S, 450 * S, 654 * S, 480 * S], fill=BLUSH_PINK)
    dr.line([(609 * S, 455 * S), (619 * S, 475 * S)], fill=(240, 90, 120, 200), width=2 * S)
    dr.line([(624 * S, 455 * S), (634 * S, 475 * S)], fill=(240, 90, 120, 200), width=2 * S)
    dr.line([(639 * S, 455 * S), (649 * S, 475 * S)], fill=(240, 90, 120, 200), width=2 * S)
    created_files["blush"] = downscale(im, "blush.png")

    # Sweat drop (Anime nervous/embarrassed sweat bead)
    im, dr = new_canvas()
    sweat_blue = (120, 210, 255, 230)
    dr.polygon([(640 * S, 370 * S), (634 * S, 390 * S), (646 * S, 390 * S)], fill=sweat_blue, outline=LINE_COLOR, width=2 * S)
    dr.ellipse([632 * S, 384 * S, 648 * S, 400 * S], fill=sweat_blue, outline=LINE_COLOR, width=2 * S)
    dr.ellipse([636 * S, 388 * S, 640 * S, 392 * S], fill=(255, 255, 255, 255))
    created_files["sweat"] = downscale(im, "sweat.png")

    print(f"Generated {len(created_files)} individual 1024x1024 anime layers in {out_path}")
    return created_files


def generate_full_frame_variants(layers_dir: str | Path, out_dir: str | Path = "assets_in/roxy") -> dict[str, Path]:
    """
    Composite full-frame variants for slicer testing (base.png, eyes_closed.png, etc.).
    """
    ldir = Path(layers_dir)
    odir = Path(out_dir)
    odir.mkdir(parents=True, exist_ok=True)

    def load_layer(name: str) -> Image.Image:
        return Image.open(ldir / f"{name}.png").convert("RGBA")

    # Base: body_back + hair_front + eyes_open + brows_neutral + mouth_closed
    body_back = load_layer("body_back")
    hair_front = load_layer("hair_front")
    eyes_open = load_layer("eyes_open")
    brows_neutral = load_layer("brows_neutral")
    mouth_closed = load_layer("mouth_closed")

    def make_composite(eyes=None, brows=None, mouth=None, blush=False, sweat=False) -> Image.Image:
        canvas = Image.new("RGBA", (1024, 1024), (240, 240, 244, 255)) # flat light-gray background
        canvas.paste(body_back, (0, 0), body_back)
        if blush:
            blush_img = load_layer("blush")
            canvas.paste(blush_img, (0, 0), blush_img)
        if sweat:
            sweat_img = load_layer("sweat")
            canvas.paste(sweat_img, (0, 0), sweat_img)

        e = eyes or eyes_open
        b = brows or brows_neutral
        m = mouth or mouth_closed

        canvas.paste(e, (0, 0), e)
        canvas.paste(b, (0, 0), b)
        canvas.paste(m, (0, 0), m)
        canvas.paste(hair_front, (0, 0), hair_front)
        return canvas

    outputs = {}
    # 1. Base
    base = make_composite()
    base.save(odir / "base.png")
    outputs["base"] = odir / "base.png"

    # 2. Variants
    variants = [
        ("eyes_closed", make_composite(eyes=load_layer("eyes_closed"))),
        ("eyes_half", make_composite(eyes=load_layer("eyes_half"))),
        ("brows_angry", make_composite(brows=load_layer("brows_angry"))),
        ("brows_sad", make_composite(brows=load_layer("brows_sad"))),
        ("brows_surprised", make_composite(brows=load_layer("brows_surprised"))),
        ("mouth_a", make_composite(mouth=load_layer("mouth_a"))),
        ("mouth_i", make_composite(mouth=load_layer("mouth_i"))),
        ("mouth_u", make_composite(mouth=load_layer("mouth_u"))),
        ("mouth_e", make_composite(mouth=load_layer("mouth_e"))),
        ("mouth_o", make_composite(mouth=load_layer("mouth_o"))),
        ("emotion_embarrassed", make_composite(eyes=load_layer("eyes_half"), mouth=load_layer("mouth_u"), blush=True)),
        ("emotion_happy", make_composite(eyes=load_layer("eyes_closed"), mouth=load_layer("mouth_i"), blush=True)),
        ("emotion_thinking", make_composite(eyes=load_layer("eyes_half"), brows=load_layer("brows_neutral"), mouth=load_layer("mouth_closed"), sweat=True)),
    ]

    for name, img in variants:
        p = odir / f"{name}.png"
        img.save(p)
        outputs[name] = p

    print(f"Generated {len(outputs)} full-frame variants in {odir}")
    return outputs


if __name__ == "__main__":
    layers = create_roxy_layers("characters/roxy/avatar/layers")
    generate_full_frame_variants("characters/roxy/avatar/layers", "assets_in/roxy")
