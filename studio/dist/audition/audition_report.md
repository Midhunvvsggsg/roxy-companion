# Roxy Voice Persona Audition Report

Generated benchmark evaluation across candidate voices for Roxy Migurdia.

## 1. Candidate Comparison Summary

| Candidate Preset | Base Model | Tuning (Pitch/Rate) | Timbre & Impression | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **ava_mature_mommy** | `en-US-AvaNeural` | -4Hz / +0% | Warm, deep, maternal reassurance with gentle teasing undertones | **WINNER (Default Preset)** |
| **emma_caring_mentor** | `en-US-EmmaNeural` | -3Hz / +0% | Clear, affectionate older mentor with calm cadence | Alternative |
| **jenny_tuned_warm** | `en-US-JennyNeural` | -6Hz / -2% | Soft and intimate, lowered pitch removes generic assistant tone | Alternative |
| **sonia_poised_tutor** | `en-GB-SoniaNeural` | -2Hz / +0% | Sophisticated British tutor, polite, dignified, calm | Alternative |
| **natasha_gentle_protective** | `en-AU-NatashaNeural` | -3Hz / +0% | Gentle, maternal Australian accent with comforting inflection | Alternative |
| **ana_original_high** | `en-US-AnaNeural` | +22Hz / +6% | High-pitched generic anime girl (the baseline we are replacing) | Baseline (Deprecated) |

## 2. Benchmark Audio Samples

Each candidate was evaluated on three emotional scenarios:
1. **Calm Greeting**: *"Welcome home, Midhun-san. Let me take care of everything for you today."*
2. **Protective / Serious**: *"I noticed a dangerous command. Please let me handle this safely, okay?"*
3. **Teasing / Affectionate**: *"You've been working so hard... lean on me a little, I won't bite."*

| Candidate | Calm Greeting | Protective Serious | Teasing / Blush |
| :--- | :--- | :--- | :--- |
| **en-US-AvaNeural (Mature Mommy Preset)** ⭐ | [ava_mature_mommy__1_calm_greeting.mp3](ava_mature_mommy__1_calm_greeting.mp3) | [ava_mature_mommy__2_protective_serious.mp3](ava_mature_mommy__2_protective_serious.mp3) | [ava_mature_mommy__3_teasing_blush.mp3](ava_mature_mommy__3_teasing_blush.mp3) |
| **en-US-EmmaNeural** | [emma_caring_mentor__1_calm_greeting.mp3](emma_caring_mentor__1_calm_greeting.mp3) | [emma_caring_mentor__2_protective_serious.mp3](emma_caring_mentor__2_protective_serious.mp3) | [emma_caring_mentor__3_teasing_blush.mp3](emma_caring_mentor__3_teasing_blush.mp3) |
| **en-US-JennyNeural (Tuned Warm)** | [jenny_tuned_warm__1_calm_greeting.mp3](jenny_tuned_warm__1_calm_greeting.mp3) | [jenny_tuned_warm__2_protective_serious.mp3](jenny_tuned_warm__2_protective_serious.mp3) | [jenny_tuned_warm__3_teasing_blush.mp3](jenny_tuned_warm__3_teasing_blush.mp3) |
| **en-GB-SoniaNeural** | [sonia_poised_tutor__1_calm_greeting.mp3](sonia_poised_tutor__1_calm_greeting.mp3) | [sonia_poised_tutor__2_protective_serious.mp3](sonia_poised_tutor__2_protective_serious.mp3) | [sonia_poised_tutor__3_teasing_blush.mp3](sonia_poised_tutor__3_teasing_blush.mp3) |
| **en-AU-NatashaNeural** | [natasha_gentle_protective__1_calm_greeting.mp3](natasha_gentle_protective__1_calm_greeting.mp3) | [natasha_gentle_protective__2_protective_serious.mp3](natasha_gentle_protective__2_protective_serious.mp3) | [natasha_gentle_protective__3_teasing_blush.mp3](natasha_gentle_protective__3_teasing_blush.mp3) |
| **en-US-AnaNeural (Original High Anime - Baseline)** | [ana_original_high__1_calm_greeting.mp3](ana_original_high__1_calm_greeting.mp3) | [ana_original_high__2_protective_serious.mp3](ana_original_high__2_protective_serious.mp3) | [ana_original_high__3_teasing_blush.mp3](ana_original_high__3_teasing_blush.mp3) |

## 3. Winning Preset Analysis: `mature_mommy` (`en-US-AvaNeural`)

- **Why It Won**: Unlike `en-US-AnaNeural` (which sounded like a prepubescent 12-year-old with harsh high frequencies), `en-US-AvaNeural` possesses a rich, natural chest resonance. When tuned to `-4Hz` and normal pace `1.0x` (`+0%`), it delivers a deeply caring, calm, protective, and subtly teasing 'mommy' presence.
- **Dynamic Emotion Prosody**: The system dynamically slows down speech by -4% on blush/shy cues, and lowers pitch by an additional -4Hz on serious protective warnings.
- **Local & Custom Model Fallback**: Supports local Kokoro-TTS and custom ONNX/Piper voices via `voice.custom_model_path`.
