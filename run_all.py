#!/usr/bin/env python3
# Cross-platform one-shot extractor + converter for ZeroEscapeRE.
# Replaces extract_ze2_data_en_us.sh and auto_convert_ze2_models.sh so the
# whole pipeline runs on Windows (and macOS) without bash/find/head/unzip.
#
# Usage:
#   python run_all.py  path\to\ze2_data_en_us.bin
#
# Output:
#   workdir/converted_models/*.blend   (characters: one .blend per animation)
#   workdir/converted_rooms/*.blend    (rooms)
#
# Robust by design: it finds character/room archives by content + stable
# name-hash instead of the hardcoded file indices in the original script
# (those break on any game build that differs from the author's).

import os
import sys
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "workdir"
DUMP = WORK / "ze2_data_en_us"      # raw .bin extraction
EXM  = WORK / "extracted_models"    # unzipped character archives
EXR  = WORK / "extracted_rooms"     # unpacked room PACKs
CVM  = WORK / "converted_models"    # character .blend output
CVR  = WORK / "converted_rooms"     # room .blend output

BINDOT_UNPACKER = ROOT / "bindot" / "unpacker.py"
PACK_UNPACKER   = ROOT / "pack" / "unpacker.py"
EXPORTER        = ROOT / "model_converter" / "blender_exporter.py"

# Stable BinDot name-hashes of the room / character directories. The numeric
# DIRECTORY PREFIX (e.g. "13-", "22-") drifts between game builds; this hash
# (a hash of the directory's path name) does not. We match on the suffix.
ROOM_DIR_HASH  = "781874508"
CHARA_DIR_HASH = "1425188142"

PY = sys.executable


# --- Make `import magic` work everywhere without libmagic -------------------
# helper.py does `import magic` at load and calls detect_extension() purely to
# print a guessed type. We shadow it with a no-op stub so Windows needs no
# libmagic DLLs and Linux needs no system package.
def build_env():
    compat = ROOT / "_compat"
    compat.mkdir(exist_ok=True)
    (compat / "magic.py").write_text(
        "class Magic:\n"
        "    def __init__(self, *a, **k):\n"
        "        self.cookie = None\n"
        "    def from_buffer(self, b):\n"
        "        return 'data'\n"
        "def magic_load(*a, **k):\n"
        "    return 0\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    # NB: never leave a trailing os.pathsep. An empty PYTHONPATH entry is read
    # as the current dir (= repo root), which puts the broken `helper/` package
    # on sys.path, shadows the editable-install module, and crashes every
    # subprocess that does `from helper import *`.
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(compat) + (os.pathsep + existing if existing else "")
    return env


ENV = None  # set in main()


def run(args, check=True):
    args = [str(a) for a in args]
    print("  $", " ".join(args))
    return subprocess.run(args, cwd=str(ROOT), env=ENV, check=check)


def head(path, n=4):
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return b""


def dirs_by_hash(name_hash):
    if not DUMP.is_dir():
        return []
    return [d for d in DUMP.iterdir()
            if d.is_dir() and d.name.endswith("-" + name_hash)]


# --- Pipeline steps ---------------------------------------------------------
def step_extract_bin(bin_path):
    print("\n[1/4] Extracting .bin ->", DUMP)
    DUMP.mkdir(parents=True, exist_ok=True)
    run([PY, BINDOT_UNPACKER, bin_path, DUMP])


def step_unzip_characters():
    print("\n[2/4] Unzipping character archives ->", EXM)
    EXM.mkdir(parents=True, exist_ok=True)

    chara_dirs = dirs_by_hash(CHARA_DIR_HASH)
    if chara_dirs:
        candidates = [f for d in chara_dirs for f in d.rglob("*") if f.is_file()]
        print(f"  character container(s): {[d.name for d in chara_dirs]}")
    else:
        # Fallback: any ZIP anywhere in the dump.
        print("  no container matched the known hash; scanning whole dump for ZIPs")
        candidates = [f for f in DUMP.rglob("*") if f.is_file()]

    count = 0
    for f in candidates:
        if head(f, 2) == b"PK":
            try:
                with zipfile.ZipFile(f) as z:
                    z.extractall(EXM)
                count += 1
            except zipfile.BadZipFile:
                pass
    print(f"  unzipped {count} archive(s)")


def step_unpack_rooms():
    print("\n[3/4] Unpacking room PACKs ->", EXR)
    EXR.mkdir(parents=True, exist_ok=True)

    room_dirs = dirs_by_hash(ROOM_DIR_HASH)
    if room_dirs:
        candidates = [f for d in room_dirs for f in d.rglob("*") if f.is_file()]
        print(f"  room container(s): {[d.name for d in room_dirs]}")
    else:
        print("  no container matched the known hash; scanning whole dump for PACKs")
        candidates = [f for f in DUMP.rglob("*") if f.is_file()]

    count = 0
    for f in candidates:
        if head(f, 4) == b"PACK":
            run([PY, PACK_UNPACKER, f, EXR])
            count += 1
    print(f"  unpacked {count} PACK archive(s)")


def convert(out_blend, inputs):
    inputs = [p for p in inputs if p and Path(p).exists()]
    try:
        run([PY, EXPORTER, out_blend, *inputs])
        return True
    except subprocess.CalledProcessError as e:
        print(f"  !! conversion failed for {Path(out_blend).name}: {e}")
        return False


def step_convert():
    print("\n[4/4] Converting to .blend")
    CVM.mkdir(parents=True, exist_ok=True)
    CVR.mkdir(parents=True, exist_ok=True)

    n_char = n_room = 0

    chara_root = EXM / "scenes" / "chara"
    if chara_root.is_dir():
        for model in sorted(p for p in chara_root.iterdir() if p.is_dir()):
            bsn = model / "scene.bsn"
            mdl = sorted((model / "mdl").glob("*")) if (model / "mdl").is_dir() else []
            tex = sorted((model / "tex").glob("*")) if (model / "tex").is_dir() else []
            base = [bsn, *mdl, *tex]
            if convert(CVM / f"{model.name}.base.blend", base):
                n_char += 1
            for motion in sorted(model.glob("*.motion")):
                convert(CVM / f"{model.name}.{motion.stem}.blend", [*base, motion])

    room_root = EXR / "scenes" / "room"
    if room_root.is_dir():
        for model in sorted(p for p in room_root.iterdir() if p.is_dir()):
            mdl = sorted((model / "mdl").glob("*")) if (model / "mdl").is_dir() else []
            tex = sorted((model / "tex").glob("*")) if (model / "tex").is_dir() else []
            if convert(CVR / f"{model.name}.blend", [*mdl, *tex]):
                n_room += 1

    print(f"\nDone. {n_char} character model(s) -> {CVM}")
    print(f"      {n_room} room model(s) -> {CVR}")
    if n_char == 0 and n_room == 0:
        print("\nNo models produced. Run with the .bin path and check the\n"
              "[2/4]/[3/4] messages above for how many archives were found.")


def main():
    global ENV
    if len(sys.argv) != 2:
        print("Usage: python run_all.py <path to ze2_data_en_us.bin>")
        sys.exit(1)
    bin_path = Path(sys.argv[1]).resolve()
    if not bin_path.is_file():
        print("File not found:", bin_path)
        sys.exit(1)

    ENV = build_env()
    WORK.mkdir(exist_ok=True)

    step_extract_bin(bin_path)
    step_unzip_characters()
    step_unpack_rooms()
    step_convert()


if __name__ == "__main__":
    main()
