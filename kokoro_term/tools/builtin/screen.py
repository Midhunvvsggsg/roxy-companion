"""Screen Capture and Screen Vision Awareness Tool for Roxy Agent."""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import tempfile
from typing import Any, Optional
from kokoro_term.tools.base import BaseTool, ToolResult
from kokoro_term.tools.env_detect import detect_environment


class CaptureScreenTool(BaseTool):
    name = "capture_screen"
    description = "Capture a screenshot of the current screen or active window."
    parameters = {
        "target": {
            "type": "string",
            "description": "'full' (default) or 'window' (active window)",
        }
    }
    tier = "safe"

    async def execute(self, target: str = "full", **kwargs) -> ToolResult:
        env = detect_environment()
        out_file = os.path.join(tempfile.gettempdir(), "roxy_screen_capture.png")

        try:
            if env.get("display_server") == "Wayland" and shutil.which("grim"):
                cmd = ["grim", out_file]
                proc = await asyncio.create_subprocess_exec(*cmd)
                await proc.communicate()
            elif shutil.which("import"):  # ImageMagick X11
                cmd = ["import", "-window", "root", out_file]
                proc = await asyncio.create_subprocess_exec(*cmd)
                await proc.communicate()
            else:
                # Fallback to PIL ImageGrab
                from PIL import ImageGrab
                loop = asyncio.get_running_loop()
                img = await loop.run_in_executor(None, ImageGrab.grab)
                img.save(out_file)

            if os.path.exists(out_file):
                size_kb = round(os.path.getsize(out_file) / 1024, 1)
                return ToolResult(
                    success=True,
                    output=f"Screenshot captured successfully ({size_kb} KB) at {out_file}",
                )
            return ToolResult(success=False, output="", error="Screenshot file was not generated.")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Capture failed: {e}")


class InspectScreenTool(BaseTool):
    name = "inspect_screen"
    description = "Capture the screen and describe or answer questions about what is currently visible on Midhun's screen."
    parameters = {
        "query": {
            "type": "string",
            "description": "Specific question or what to look for on the screen (e.g. 'what app is open', 'summarize my code')",
        }
    }
    tier = "safe"

    async def execute(self, query: str = "Describe what is on screen", **kwargs) -> ToolResult:
        # First capture screen
        cap = CaptureScreenTool()
        cap_res = await cap.execute()
        if not cap_res.success:
            return ToolResult(success=False, output="", error=f"Could not capture screen: {cap_res.error}")

        out_file = os.path.join(tempfile.gettempdir(), "roxy_screen_capture.png")
        if not os.path.exists(out_file):
            return ToolResult(success=False, output="", error="Captured screenshot not found on disk.")

        # Analyze using Gemini Vision API
        try:
            with open(out_file, "rb") as f:
                img_bytes = f.read()
            b64_img = base64.b64encode(img_bytes).decode("utf-8")

            # Try google-genai or google.generativeai
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                return ToolResult(
                    success=False,
                    output="",
                    error="GEMINI_API_KEY is not configured for vision analysis.",
                )

            analysis = ""
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=api_key)
                prompt_text = f"You are Roxy Migurdia. Answer the following about the user's screen in your concise anime persona: {query}"
                resp = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        prompt_text,
                        types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                    ],
                )
                analysis = resp.text.strip()
            except Exception:
                import google.generativeai as gai
                gai.configure(api_key=api_key)
                model = gai.GenerativeModel("gemini-2.5-flash")
                resp = model.generate_content([
                    f"You are Roxy Migurdia. Answer the following about the user's screen in your concise anime persona: {query}",
                    {"mime_type": "image/png", "data": b64_img},
                ])
                analysis = resp.text.strip()

            return ToolResult(success=True, output=analysis or "Screen inspected: no details returned.")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Vision inspection failed: {e}")
