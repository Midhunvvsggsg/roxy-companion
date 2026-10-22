from __future__ import annotations

import difflib
import fnmatch
import os
from pathlib import Path
from typing import Any
import send2trash

from kokoro_term.tools.base import BaseTool, ToolResult


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read the contents of a text file (supports start_line and max_lines)."
    parameters = {
        "path": {"type": "string", "description": "Path to the file to read"},
        "start_line": {"type": "integer", "description": "Starting line number (1-based)", "default": 1},
        "max_lines": {"type": "integer", "description": "Maximum lines to read", "default": 200},
    }
    tier = "safe"

    async def execute(self, path: str, start_line: int = 1, max_lines: int = 200, **kwargs) -> ToolResult:
        file_path = Path(path).expanduser().resolve()
        if not file_path.exists():
            return ToolResult(success=False, output="", error=f"File not found: {path}")
        if not file_path.is_file():
            return ToolResult(success=False, output="", error=f"Path is not a regular file: {path}")

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            start_idx = max(0, start_line - 1)
            selected = lines[start_idx : start_idx + max_lines]
            content = "".join(selected)
            return ToolResult(success=True, output=content)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write content to a file. Generates a diff if overwriting existing content."
    parameters = {
        "path": {"type": "string", "description": "Target file path"},
        "content": {"type": "string", "description": "Full text content to write"},
    }
    tier = "moderate"

    async def dry_run(self, path: str, content: str, **kwargs) -> str:
        file_path = Path(path).expanduser().resolve()
        if file_path.exists():
            old_text = file_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            new_text = content.splitlines(keepends=True)
            diff = "".join(difflib.unified_diff(old_text, new_text, fromfile=str(path), tofile=str(path)))
            return f"Would overwrite '{path}' with diff:\n{diff}"
        return f"Would create new file '{path}' ({len(content)} bytes)"

    async def execute(self, path: str, content: str, **kwargs) -> ToolResult:
        file_path = Path(path).expanduser().resolve()
        diff_str = None

        try:
            if file_path.exists():
                old_text = file_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                new_text = content.splitlines(keepends=True)
                diff_str = "".join(difflib.unified_diff(old_text, new_text, fromfile=str(path), tofile=str(path)))

            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            msg = f"Successfully wrote {len(content)} bytes to {path}."
            return ToolResult(success=True, output=msg, diff=diff_str)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = "Search for files by filename pattern within a directory."
    parameters = {
        "directory": {"type": "string", "description": "Root directory to search in", "default": "."},
        "pattern": {"type": "string", "description": "Glob pattern (e.g., '*.py', '*.yaml')", "default": "*"},
        "max_results": {"type": "integer", "description": "Max results to return", "default": 30},
    }
    tier = "safe"

    async def execute(self, directory: str = ".", pattern: str = "*", max_results: int = 30, **kwargs) -> ToolResult:
        root_path = Path(directory).expanduser().resolve()
        if not root_path.exists() or not root_path.is_dir():
            return ToolResult(success=False, output="", error=f"Directory not found: {directory}")

        matches = []
        try:
            for root, _, files in os.walk(root_path):
                # Skip hidden directories like .git, .venv
                parts = Path(root).parts
                if any(p.startswith(".") for p in parts if p not in (".", "..")):
                    continue

                for filename in files:
                    if fnmatch.fnmatch(filename, pattern):
                        matches.append(os.path.relpath(os.path.join(root, filename), root_path))
                        if len(matches) >= max_results:
                            break
                if len(matches) >= max_results:
                    break

            if not matches:
                return ToolResult(success=True, output=f"No files matching '{pattern}' in {directory}")

            return ToolResult(success=True, output="\n".join(matches))
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class TrashFileTool(BaseTool):
    name = "trash_file"
    description = "Safely move a file or folder to the system Recycle Bin / Trash with undo support."
    parameters = {
        "path": {"type": "string", "description": "Path to file or folder to trash"},
    }
    tier = "dangerous"

    async def dry_run(self, path: str, **kwargs) -> str:
        return f"Would move '{path}' to system Recycle Bin / Trash."

    async def execute(self, path: str, **kwargs) -> ToolResult:
        file_path = Path(path).expanduser().resolve()
        if not file_path.exists():
            return ToolResult(success=False, output="", error=f"Target does not exist: {path}")

        try:
            send2trash.send2trash(str(file_path))
            return ToolResult(success=True, output=f"Moved '{path}' to system Trash (can be restored).")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to trash '{path}': {e}")
