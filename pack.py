#!/usr/bin/env python3
from __future__ import annotations
import json
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "raw"
BUILD_DIR = ROOT / "build"
BIN_DIR = ROOT / "bin"
FONT_URL = "https://github.com/Warren2060/ChillRound/releases/download/v3.200/ChillRoundF_v3.200.zip"
FONT_DIR = BUILD_DIR / "ChillRoundF_v3.200"
FONT_PATH = FONT_DIR / "ChillRoundFBold.ttf"
FONT_ZIP = BUILD_DIR / "font.zip"

TOOLS = [
    {
        "name": "shin-tl",
        "repo": "DCNick3/shin-translation-tools",
        "asset_map": {
            ("windows", "x86_64"): "shin-tl-x86_64-pc-windows-msvc.zip",
            ("linux", "x86_64"): "shin-tl-x86_64-unknown-linux-gnu.tar.xz",
            ("linux", "aarch64"): "shin-tl-aarch64-unknown-linux-gnu.tar.xz",
            ("darwin", "x86_64"): "shin-tl-x86_64-apple-darwin.tar.xz",
            ("darwin", "aarch64"): "shin-tl-aarch64-apple-darwin.tar.xz",
        },
        "exe_name": "shin-tl.exe",
    },
    {
        "name": "fnt4-tool",
        "repo": "nini22P/fnt4-tool",
        "asset_map": {
            ("windows", "x86_64"): "fnt4-tool-windows-x86_64.zip",
            ("windows", "aarch64"): "fnt4-tool-windows-aarch64.zip",
            ("linux", "x86_64"): "fnt4-tool-linux-x86_64.zip",
            ("linux", "aarch64"): "fnt4-tool-linux-aarch64.zip",
            ("darwin", "x86_64"): "fnt4-tool-macos-x86_64.zip",
            ("darwin", "aarch64"): "fnt4-tool-macos-aarch64.zip",
        },
        "exe_name": "fnt4-tool.exe",
    },
]


def run(*cmd, **kwargs):
    cmd_list = [str(x) for x in cmd]
    print("+", " ".join(cmd_list))
    subprocess.run(cmd_list, check=True, **kwargs)


def platform_key():
    system = platform.system().lower()
    if system.startswith("mingw") or system.startswith("cygwin"):
        system = "windows"
    if system == "darwin":
        system = "darwin"
    arch = platform.machine().lower()
    if arch in ("amd64", "x86_64", "x86-64"):
        arch = "x86_64"
    elif arch in ("aarch64", "arm64"):
        arch = "aarch64"
    return system, arch


def github_latest_asset_url(repo: str, asset_name: str) -> str:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "python-urllib"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    for asset in data.get("assets", []):
        if asset.get("name") == asset_name:
            return asset["browser_download_url"]
    raise RuntimeError(f"Asset '{asset_name}' not found in latest release of {repo}")


def download_file(url: str, dest: Path, min_size: int = 0) -> None:
    print(f"Downloading {url} -> {dest}")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "python-urllib"}), timeout=60) as resp:
        data = resp.read()
    dest.write_bytes(data)
    if min_size and dest.stat().st_size < min_size:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded file {dest} is smaller than expected ({min_size} bytes)")


def extract_archive(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if src.suffix == ".zip":
        with zipfile.ZipFile(src, "r") as zf:
            zf.extractall(dest)
    elif src.suffixes[-2:] == [".tar", ".xz"] or src.suffix == ".xz":
        with tarfile.open(src, "r:xz") as tf:
            tf.extractall(dest)
    else:
        raise RuntimeError(f"Unsupported archive format: {src}")


def find_executable(search_root: Path, name: str) -> Path | None:
    for path in search_root.rglob(name):
        if path.is_file():
            return path
    return None


def ensure_tool(tool: dict) -> Path:
    system, arch = platform_key()
    executable_name = tool["exe_name"] if system == "windows" else tool["name"]
    dest_exe = BIN_DIR / executable_name
    if dest_exe.exists():
        print(f"Tool already installed: {dest_exe}")
        return dest_exe
    key = (system, arch)
    asset_name = tool["asset_map"].get(key)
    if asset_name is None:
        raise RuntimeError(f"Unsupported platform/arch for {tool['name']}: {system}/{arch}")
    asset_url = github_latest_asset_url(tool["repo"], asset_name)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        archive_path = tmp / asset_name
        download_file(asset_url, archive_path)
        extract_dir = tmp / "extract"
        extract_archive(archive_path, extract_dir)
        candidate = find_executable(extract_dir, executable_name)
        if candidate is None and system != "windows":
            candidate = find_executable(extract_dir, tool["name"])
        if candidate is None:
            raise RuntimeError(f"Failed to find executable for {tool['name']} inside {archive_path}")
        shutil.copy2(candidate, dest_exe)
    if system != "windows":
        dest_exe.chmod(dest_exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Installed {tool['name']} -> {dest_exe}")
    return dest_exe


def download_tools() -> None:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    system, arch = platform_key()
    print(f"Platform detected: {system}/{arch}")
    for tool in TOOLS:
        ensure_tool(tool)


def download_font() -> None:
    if FONT_PATH.exists():
        print(f"Font already exists: {FONT_PATH}")
        return
    print("Downloading font...")
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    download_file(FONT_URL, FONT_ZIP, min_size=1_000_000)
    with zipfile.ZipFile(FONT_ZIP, "r") as zf:
        zf.extractall(BUILD_DIR)
    FONT_ZIP.unlink(missing_ok=True)


def extract_raw_roms() -> None:
    for name in ("data", "patch", "append"):
        target_path = RAW_DIR / name
        rom_file = RAW_DIR / f"{name}.rom"
        if target_path.exists():
            continue
        if rom_file.exists():
            print(f"Extracting {rom_file}...")
            run(BIN_DIR / ("shin-tl.exe" if platform_key()[0] == "windows" else "shin-tl"), "rom", "extract", rom_file, target_path)
        else:
            print(f"Missing {rom_file}, skipping extraction.")


def prepare_patch_dir() -> None:
    build_patch_path = BUILD_DIR / "patch"
    if not build_patch_path.exists():
        shutil.copytree(RAW_DIR / "patch", build_patch_path, dirs_exist_ok=True)


def main() -> int:
    for path in (RAW_DIR, BUILD_DIR, BUILD_DIR / "romfs", BIN_DIR):
        path.mkdir(parents=True, exist_ok=True)
    download_tools()
    download_font()
    extract_raw_roms()
    prepare_patch_dir()
    run(sys.executable, ROOT / "tools/script-tool.py", "import", "--main", "main.csv", "--text", "higurashi-hou.csv")
    run(sys.executable, ROOT / "shin-tools" / "mapping-tool.py", "mapping-config.json")
    run(BIN_DIR / ("shin-tl.exe" if platform_key()[0] == "windows" else "shin-tl"), "snr", "rewrite", "higurashi-hou-v2", RAW_DIR / "patch" / "main.snr", BUILD_DIR / "main-mapped.csv", BUILD_DIR / "patch" / "main.snr")
    run(BIN_DIR / ("fnt4-tool.exe" if platform_key()[0] == "windows" else "fnt4-tool"), "rebuild", RAW_DIR / "data" / "newrodin.fnt", BUILD_DIR / "patch" / "newrodin.fnt", FONT_PATH, "-s", "102", "--letter-spacing", "2", "-c", BUILD_DIR / "mapping.toml")
    run(BIN_DIR / ("shin-tl.exe" if platform_key()[0] == "windows" else "shin-tl"), "rom", "create", "--rom-version", "higurashi-hou-v2", BUILD_DIR / "patch", BUILD_DIR / "romfs" / "patch.rom")
    print("Build Complete!")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Command failed: {exc}")
        raise
    except Exception as exc:
        print(f"Error: {exc}")
        raise
