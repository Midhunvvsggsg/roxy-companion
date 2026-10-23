"""File System Operations Tools for Roxy Agent."""

from __future__ import annotations

import difflib
import fnmatch
import os
import shutil
from pathlib import Path
from typing import Any, Optional
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
            numbered = [f"{start_idx + i + 1}: {line}" for i, line in enumerate(selected)]
            content = "".join(numbered)
            return ToolResult(success=True, output=content or "(Empty file)")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write or overwrite content to a file. Generates a diff if overwriting."
    parameters = {
        "path": {"type": "string", "description": "Target file path"},
        "content": {"type": "string", "description": "Full text content to write"},
    }
    tier = "moderate"

    async def execute(self, path: str, content: str, **kwargs) -> ToolResult:
        file_path = Path(path).expanduser().resolve()
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            diff_text = None
            if file_path.exists():
                old_text = file_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                new_text = content.splitlines(keepends=True)
                diff = list(difflib.unified_diff(old_text, new_text, fromfile=str(path), tofile=str(path)))
                diff_text = "".join(diff)

            file_path.write_text(content, encoding="utf-8")
            msg = f"Successfully wrote {len(content)} characters to '{path}'."
            return ToolResult(success=True, output=msg, diff=diff_text)
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Write failed: {e}")


class AppendFileTool(BaseTool):
    name = "append_file"
    description = "Append text content to the end of a file."
    parameters = {
        "path": {"type": "string", "description": "Target file path"},
        "content": {"type": "string", "description": "Text content to append"},
    }
    tier = "moderate"

    async def execute(self, path: str, content: str, **kwargs) -> ToolResult:
        file_path = Path(path).expanduser().resolve()
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(success=True, output=f"Appended {len(content)} characters to '{path}'.")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Append failed: {e}")


class ListDirTool(BaseTool):
    name = "list_dir"
    description = "List files and directories inside a directory with size and modification details."
    parameters = {
        "path": {"type": "string", "description": "Directory path to list (default '.')", "default": "."},
    }
    tier = "safe"

    async def execute(self, path: str = ".", **kwargs) -> ToolResult:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return ToolResult(success=False, output="", error=f"Directory not found: {path}")
        if not target.is_dir():
            return ToolResult(success=False, output="", error=f"Path is not a directory: {path}")

        try:
            entries = []
            for item in sorted(target.iterdir()):
                try:
                    stat = item.stat()
                    type_char = "d" if item.is_dir() else "f"
                    size_str = f"{stat.st_size} B" if item.is_file() else "<DIR>"
                    entries.append(f"[{type_char}] {item.name:30s} {size_str}")
                except Exception:
                    entries.append(f"[?] {item.name}")
            return ToolResult(success=True, output="\n".join(entries) or "(Empty directory)")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = "Search for text regex or filenames across a directory using ripgrep or glob."
    parameters = {
        "query": {"type": "string", "description": "Search pattern or regex", "default": ""},
        "path": {"type": "string", "description": "Directory to search in", "default": "."},
    }
    tier = "safe"

    async def execute(
        self,
        query: str = "",
        path: str = ".",
        directory: Optional[str] = None,
        pattern: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        import asyncio
        search_dir = directory or path or "."
        q = query or pattern or ""
        target = Path(search_dir).expanduser().resolve()
        if not target.exists():
            return ToolResult(success=False, output="", error=f"Path not found: {search_dir}")

        # If pattern looks like filename glob (*.txt, *.py)
        if q.startswith("*.") or "*" in q:
            matches = list(target.glob(f"**/{q}"))[:30]
            output = "\n".join(str(m.relative_to(target)) for m in matches)
            return ToolResult(success=True, output=output or f"No files matching '{q}' found.")

        try:
            if shutil.which("rg"):
                cmd = ["rg", "-n", "--max-count", "10", q, str(target)]
            elif shutil.which("grep"):
                cmd = ["grep", "-rnI", "--max-count=10", q, str(target)]
            else:
                return ToolResult(success=False, output="", error="Neither rg nor grep is available.")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            res = stdout.decode(errors="replace").strip()
            return ToolResult(success=True, output=res or f"No matches found for '{q}'.")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class FileInfoTool(BaseTool):
    name = "file_info"
    description = "Get metadata, file size, permissions, and modification time for a file or directory."
    parameters = {
        "path": {"type": "string", "description": "File or directory path"},
    }
    tier = "safe"

    async def execute(self, path: str, **kwargs) -> ToolResult:
        import datetime
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return ToolResult(success=False, output="", error=f"Path not found: {path}")

        try:
            stat = target.stat()
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            info = [
                f"Path: {target}",
                f"Type: {'Directory' if target.is_dir() else 'File'}",
                f"Size: {stat.st_size} bytes ({round(stat.st_size / 1024, 2)} KB)",
                f"Permissions: {oct(stat.st_mode)[-3:]}",
                f"Last Modified: {mtime}",
            ]
            return ToolResult(success=True, output="\n".join(info))
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class TrashFileTool(BaseTool):
    name = "trash_file"
    description = "Move a file or directory safely to the system Trash/Recycle Bin."
    parameters = {
        "path": {"type": "string", "description": "Path to the file or directory to move to trash"},
    }
    tier = "dangerous"

    async def execute(self, path: str, **kwargs) -> ToolResult:
        file_path = Path(path).expanduser().resolve()
        if not file_path.exists():
            return ToolResult(success=False, output="", error=f"Path not found: {path}")

        try:
            send2trash.send2trash(str(file_path))
            return ToolResult(success=True, output=f"Moved '{path}' to system Trash.")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
