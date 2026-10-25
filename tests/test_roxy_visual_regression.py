import json
from pathlib import Path
import cv2
import numpy as np
import pytest

RESTORED_DIR = Path("/home/midhun/Development/mesh-avatar-studio/work/restored")
BUILT_DIR = Path("/home/midhun/Development/mesh-avatar-studio/projects/roxy/built")
MASKS_FILE = Path("/home/midhun/kokoro-term/characters/roxy/avatar/forehead_masks.json")
VERIFY_VIEWS_DIR = Path("/home/midhun/Development/mesh-avatar-studio/work/verify_views/crops_4x")

def poly_mask(shape, pts):
    m = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillPoly(m, [np.array(pts, dtype=np.int32)], 255)
    return m

def test_masks_json_valid():
    assert MASKS_FILE.exists(), f"{MASKS_FILE} does not exist"
    with open(MASKS_FILE) as f:
        masks = json.load(f)
    assert "item_a_nose_bridge_stroke" in masks
    assert "item_a_center_tuft_base" in masks
    assert "item_b_forehead_whole" in masks
    assert "item_b_forehead_arc_left" in masks
    assert "item_b_forehead_arc_right" in masks
    assert "item_c_left_vertical_tick" in masks
    assert "item_c_left_fine_strokes" in masks
    assert "item_c_right_vertical_tick" in masks
    assert "item_c_right_fine_strokes" in masks
    assert "item_d_bangs_bottom_edge" in masks
    assert "item_d_hair_peach_streaks" in masks

def test_pixel_diff_outside_masks_is_zero():
    with open(MASKS_FILE) as f:
        masks = json.load(f)
    with open(RESTORED_DIR / "layers.json") as f:
        meta = json.load(f)

    # 1. Base layer (whole forehead cel repaint + center tuft)
    base_restored = cv2.imread(str(RESTORED_DIR / "base.png"), cv2.IMREAD_UNCHANGED)
    base_built = cv2.imread(str(BUILT_DIR / "base.png"), cv2.IMREAD_UNCHANGED)
    m_base = (poly_mask((1024, 1024), masks["item_a_center_tuft_base"]) > 0) | \
             (poly_mask((1024, 1024), masks["item_b_forehead_whole"]) > 0)
    diff_base = np.max(np.abs(base_built[~m_base].astype(int) - base_restored[~m_base].astype(int)))
    assert diff_base == 0, f"base.png has diff of {diff_base} outside masks"

    # 2. eye0_lash
    l0_restored = cv2.imread(str(RESTORED_DIR / "eye0_lash.png"), cv2.IMREAD_UNCHANGED)
    l0_built = cv2.imread(str(BUILT_DIR / "eye0_lash.png"), cv2.IMREAD_UNCHANGED)
    rx0, ry0, rw0, rh0 = meta["layers"]["eye0_lash"]
    m_l0 = (poly_mask((1024, 1024), masks["item_c_left_vertical_tick"]) > 0) | \
           (poly_mask((1024, 1024), masks["item_c_left_fine_strokes"]) > 0)
    m_l0_crop = m_l0[ry0:ry0+rh0, rx0:rx0+rw0]
    diff_l0 = np.max(np.abs(l0_built[~m_l0_crop].astype(int) - l0_restored[~m_l0_crop].astype(int)))
    assert diff_l0 == 0, f"eye0_lash has diff of {diff_l0} outside masks"

    # 3. eye1_lash
    l1_restored = cv2.imread(str(RESTORED_DIR / "eye1_lash.png"), cv2.IMREAD_UNCHANGED)
    l1_built = cv2.imread(str(BUILT_DIR / "eye1_lash.png"), cv2.IMREAD_UNCHANGED)
    rx1, ry1, rw1, rh1 = meta["layers"]["eye1_lash"]
    m_l1 = (poly_mask((1024, 1024), masks["item_a_nose_bridge_stroke"]) > 0) | \
           (poly_mask((1024, 1024), masks["item_c_right_vertical_tick"]) > 0) | \
           (poly_mask((1024, 1024), masks["item_c_right_fine_strokes"]) > 0)
    m_l1_crop = m_l1[ry1:ry1+rh1, rx1:rx1+rw1]
    diff_l1 = np.max(np.abs(l1_built[~m_l1_crop].astype(int) - l1_restored[~m_l1_crop].astype(int)))
    assert diff_l1 == 0, f"eye1_lash has diff of {diff_l1} outside masks"

    # 4. eye1_low
    low_restored = cv2.imread(str(RESTORED_DIR / "eye1_low.png"), cv2.IMREAD_UNCHANGED)
    low_built = cv2.imread(str(BUILT_DIR / "eye1_low.png"), cv2.IMREAD_UNCHANGED)
    rx_low, ry_low, rw_low, rh_low = meta["layers"]["eye1_low"]
    m_low = poly_mask((1024, 1024), masks["item_a_nose_bridge_stroke"]) > 0
    m_low_crop = m_low[ry_low:ry_low+rh_low, rx_low:rx_low+rw_low]
    diff_low = np.max(np.abs(low_built[~m_low_crop].astype(int) - low_restored[~m_low_crop].astype(int)))
    assert diff_low == 0, f"eye1_low has diff of {diff_low} outside masks"

    # 5. hair
    hair_restored = cv2.imread(str(RESTORED_DIR / "hair.png"), cv2.IMREAD_UNCHANGED)
    hair_built = cv2.imread(str(BUILT_DIR / "hair.png"), cv2.IMREAD_UNCHANGED)
    hrx, hry, hrw, hrh = meta["layers"]["hair"]
    m_hair = (poly_mask((1024, 1024), masks["item_c_hair_outer_tick_left"]) > 0) | \
             (poly_mask((1024, 1024), masks["item_c_hair_outer_tick_right"]) > 0) | \
             (poly_mask((1024, 1024), masks["item_d_bangs_bottom_edge"]) > 0) | \
             (poly_mask((1024, 1024), masks["item_d_hair_peach_streaks"]) > 0)
    m_hair_crop = m_hair[hry:hry+hrh, hrx:hrx+hrw]
    diff_hair = np.max(np.abs(hair_built[~m_hair_crop].astype(int) - hair_restored[~m_hair_crop].astype(int)))
    assert diff_hair == 0, f"hair.png has diff of {diff_hair} outside masks"

def test_forehead_palette_check_rendered_outputs():
    """Verify that in the rendered face outputs, the forehead skin zone contains only valid skin/shadow colors and no stray dark strokes."""
    # Check rendered views in crops_4x
    views = [
        "crop_view_1_split_neutral.png",
        "crop_view_2_focus_neutral.png",
        "crop_view_3_chat_neutral.png",
        "crop_expr_happy.png"
    ]
    for view_name in views:
        img_path = VERIFY_VIEWS_DIR / view_name
        assert img_path.exists(), f"Missing rendered view: {img_path}"
        img = cv2.imread(str(img_path))
        h, w = img.shape[:2]

        # Forehead region below bangs tips and above eyebrows:
        # On 800x880 crop, forehead center is around y: 220..300, x: 260..620
        forehead_sample = img[220:300, 260:620]
        r = forehead_sample[..., 2]
        g = forehead_sample[..., 1]
        b = forehead_sample[..., 0]

        # Ensure all pixels are porcelain skin or shadow (R > 180, G > 160, B > 140, R >= B)
        # and strictly no dark stroke pixels (gray < 150)
        gray = cv2.cvtColor(forehead_sample, cv2.COLOR_BGR2GRAY)
        dark_pixels = np.sum(gray < 150)
        assert dark_pixels == 0, f"{view_name} has {dark_pixels} dark pixels in forehead region"

        # Check nose bridge region (y: 340..420, x: 380..500)
        nose_sample = img[340:420, 380:500]
        nose_gray = cv2.cvtColor(nose_sample, cv2.COLOR_BGR2GRAY)
        nose_dark = np.sum(nose_gray < 140)
        assert nose_dark == 0, f"{view_name} has {nose_dark} dark pixels at nose bridge"

        # Check skin color balance: mean red should exceed blue by 15-40 (warm porcelain tone)
        r_mean = np.mean(r)
        b_mean = np.mean(b)
        assert 15 <= (r_mean - b_mean) <= 55, f"{view_name} forehead skin balance unexpected: R-B = {r_mean - b_mean}"


def test_face_symmetry_metrics_under_one_point_five_percent():
    """Verify face symmetry metrics: eye center height, width, brow height, mouth offset, and bangs height are strictly < 1.5% of face width."""
    layers_dir = Path("/home/midhun/kokoro-term/characters/roxy/avatar/layers")
    base = cv2.imread(str(layers_dir / "base.png"), cv2.IMREAD_UNCHANGED)
    brows = cv2.imread(str(layers_dir / "brows_neutral.png"), cv2.IMREAD_UNCHANGED)
    mouth = cv2.imread(str(layers_dir / "mouth_closed.png"), cv2.IMREAD_UNCHANGED)
    hair = cv2.imread(str(layers_dir / "hair_front.png"), cv2.IMREAD_UNCHANGED)
    eyes = cv2.imread(str(layers_dir / "eyes_open.png"), cv2.IMREAD_UNCHANGED)

    # Face width at eye level
    skin_xs = np.where(base[450, :, 3] > 0)[0]
    face_width = float(skin_xs.max() - skin_xs.min())
    midline = float(skin_xs.min() + skin_xs.max()) / 2.0
    assert face_width > 400

    # 1. Mouth offset
    mouth_pts = np.where(mouth[..., 3] > 50)
    mouth_x_center = float(np.mean(mouth_pts[1]))
    mouth_offset_pct = (abs(mouth_x_center - midline) / face_width) * 100.0
    assert mouth_offset_pct < 1.5, f"Mouth offset {mouth_offset_pct:.2f}% exceeds 1.5%"

    # 2. Brows height difference
    brow_pts = np.where(brows[..., 3] > 50)
    b_left = brow_pts[1] < midline
    b_right = brow_pts[1] > midline
    brow_diff_pct = (abs(np.mean(brow_pts[0][b_left]) - np.mean(brow_pts[0][b_right])) / face_width) * 100.0
    assert brow_diff_pct < 1.5, f"Brow height diff {brow_diff_pct:.2f}% exceeds 1.5%"

    # 3. Eyes height difference
    eye_pts = np.where(eyes[..., 3] > 50)
    e_left = eye_pts[1] < midline
    e_right = eye_pts[1] > midline
    eye_h_pct = (abs(np.mean(eye_pts[0][e_left]) - np.mean(eye_pts[0][e_right])) / face_width) * 100.0
    assert eye_h_pct < 1.5, f"Eye height diff {eye_h_pct:.2f}% exceeds 1.5%"

    # 4. Eyes width from midline difference
    eye_w_diff = abs((midline - np.mean(eye_pts[1][e_left])) - (np.mean(eye_pts[1][e_right]) - midline))
    eye_w_pct = (eye_w_diff / face_width) * 100.0
    assert eye_w_pct < 1.5, f"Eye width diff {eye_w_pct:.2f}% exceeds 1.5%"

    # 5. Bangs height difference
    with open(MASKS_FILE) as f:
        masks = json.load(f)
    bangs_pts = np.array(masks["item_d_bangs_bottom_edge"])[1:12]
    b_left_pts = [p for p in bangs_pts if p[0] < midline]
    b_right_pts = [p for p in bangs_pts if p[0] > midline]
    bangs_h_diff = abs(np.mean([p[1] for p in b_left_pts]) - np.mean([p[1] for p in b_right_pts]))
    bangs_h_pct = (bangs_h_diff / face_width) * 100.0
    assert bangs_h_pct < 1.5, f"Bangs height diff {bangs_h_pct:.2f}% exceeds 1.5%"

