"""Discover PowerShell profiles and install their completion loader."""

from __future__ import annotations

import base64
import codecs
import json
import locale
from pathlib import Path
import re
import shutil
import subprocess

from util import BUILDSYS_DIR, ConfigError


START_MARKER = "# >>> buildsys completion >>>"
END_MARKER = "# <<< buildsys completion <<<"


def discover_profiles() -> list[Path]:
    profiles = []
    for name in ("pwsh", "powershell"):
        executable = shutil.which(name)
        if not executable:
            continue
        result = subprocess.run([
            executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
            "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; "
            "ConvertTo-Json -Compress -InputObject ([string]$PROFILE.CurrentUserAllHosts)",
        ], capture_output=True, encoding="utf-8-sig", check=True)
        try:
            profile = json.loads(result.stdout)
        except ValueError as exc:
            raise ConfigError(f"{name}: could not determine the current user profile") from exc
        if not isinstance(profile, str) or not profile:
            raise ConfigError(f"{name}: could not determine the current user profile")
        path = Path(profile).expanduser().resolve()
        if path not in profiles:
            profiles.append(path)
    if not profiles:
        raise ConfigError("PowerShell was not found; install PowerShell or choose --terminal=bash")
    return profiles


def quote_path(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def profile_content(path: Path, script: Path) -> bytes:
    """Update our marked block without changing the user's encoding or content."""
    raw = path.read_bytes() if path.exists() else codecs.BOM_UTF8
    encoding = "utf-8"
    bom = b""
    for signature, codec in (
        (codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
        (codecs.BOM_UTF8, "utf-8"),
        (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be"),
    ):
        if raw.startswith(signature):
            bom, encoding = signature, codec
            break
    try:
        content = raw[len(bom):].decode(encoding)
    except UnicodeDecodeError:
        if bom:
            raise
        encoding = locale.getpreferredencoding(False)
        content = raw.decode(encoding)
    newline = "\r\n" if "\r\n" in content else "\n"
    literal = quote_path(script)
    loader = f"if (Test-Path -LiteralPath {literal}) {{ . {literal} }}"
    try:
        loader.encode(encoding)
        needs_ascii = not bom and not loader.isascii()
    except UnicodeEncodeError:
        needs_ascii = True
    if needs_ascii:
        # Legacy ANSI profiles may not represent a new installation path.
        # ASCII loaders also work in BOM-less UTF-8 profiles on PowerShell 5.1.
        encoded = base64.b64encode(str(script).encode("utf-8")).decode("ascii")
        literal = f"([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')))"
        loader = f"if (Test-Path -LiteralPath {literal}) {{ . {literal} }}"
    block = newline.join((START_MARKER, loader, END_MARKER, ""))
    pattern = re.compile(r"(?ms)^" + re.escape(START_MARKER) + r"\r?\n.*?^"
                         + re.escape(END_MARKER) + r"(?:\r?\n|$)")
    if pattern.search(content):
        replaced = False

        def replace(match: re.Match[str]) -> str:
            nonlocal replaced
            if replaced:
                return ""
            replaced = True
            return block

        content = pattern.sub(replace, content)
    else:
        if content and not content.endswith(("\r", "\n")):
            content += newline
        content += block
    return bom + content.encode(encoding)


def install(directory: Path | None) -> None:
    if directory is not None:
        directory = directory.expanduser().resolve()
        if not directory.is_dir():
            raise ConfigError(f"{directory}: install directory does not exist")
    profiles = discover_profiles()
    # Prepare every update before writing, so decoding failures leave profiles alone.
    updates = []
    for profile in profiles:
        script = (directory or profile.parent / "completions") / "buildsys.ps1"
        try:
            content = profile_content(profile, script)
        except UnicodeError as exc:
            raise ConfigError(f"{profile}: could not preserve profile encoding: {exc}") from exc
        updates.append((profile, script, content))
    adapter = (BUILDSYS_DIR / "powershell-completion/buildsys.ps1").read_bytes()
    for profile, script, content in updates:
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_bytes(codecs.BOM_UTF8 + adapter.removeprefix(codecs.BOM_UTF8))
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_bytes(content)
        print(f"installed {script}; updated {profile}")
        print(f"load in the current session: . {quote_path(script)}")
