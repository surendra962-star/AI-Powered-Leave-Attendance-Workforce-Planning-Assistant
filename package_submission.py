"""Submission packaging and automated verification script.

1. Runs the complete test suite to verify 100% pass rate.
2. Initializes or updates the private Git repository.
3. Generates a clean, compliant submission ZIP archive (excluding virtual environments, caches, and local databases).
4. Emits a verification manifest with SHA-256 checksums.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
SUBMISSION_ZIP = ROOT / "ai_hr_submission.zip"
EXCLUDE_DIRS = {
    ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".git", "data/chroma", "submission", ".idea", ".vscode"
}
EXCLUDE_EXTS = {".pyc", ".pyo", ".pyd", ".db", ".zip", ".tar.gz", ".DS_Store"}


def run_tests() -> bool:
    print("=" * 60)
    print("STEP 1: Running Full Test Suite Verification")
    print("=" * 60)
    pytest_bin = ROOT / ".venv" / "bin" / "pytest"
    cmd = [str(pytest_bin) if pytest_bin.exists() else "pytest", "tests/", "-q"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr)
    if proc.returncode == 0:
        print("✅ ALL TESTS PASSED SUCCESSFULLY!")
        return True
    else:
        print("❌ TEST SUITE FAILED!")
        return False


def setup_git_repo() -> None:
    print("\n" + "=" * 60)
    print("STEP 2: Initializing / Updating Git Repository")
    print("=" * 60)
    git_dir = ROOT / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=str(ROOT), check=True)
        print("Initialized new local Git repository.")
    subprocess.run(["git", "config", "user.name", "AI/ML Intern Candidate"], cwd=str(ROOT), check=True)
    subprocess.run(["git", "config", "user.email", "candidate@v7ai.org"], cwd=str(ROOT), check=True)
    subprocess.run(["git", "add", "."], cwd=str(ROOT), check=True)
    # Check if there are changes to commit
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT), capture_output=True, text=True)
    if status.stdout.strip():
        subprocess.run(["git", "commit", "-m", "AI-Powered HR Assistant: Complete implementation with RAG, Flask REST APIs, and Streamlit"], cwd=str(ROOT), check=True)
        print("Committed all clean project files to Git.")
    else:
        print("Git working tree clean; no uncommitted changes.")


def create_submission_zip() -> Path:
    print("\n" + "=" * 60)
    print("STEP 3: Packaging Clean Submission Archive")
    print("=" * 60)
    if SUBMISSION_ZIP.exists():
        SUBMISSION_ZIP.unlink()

    packed_files = []
    with zipfile.ZipFile(SUBMISSION_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ROOT):
            rel_dir = os.path.relpath(root, ROOT)
            # Prune excluded directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not any(ex in os.path.join(rel_dir, d) for ex in EXCLUDE_DIRS)]

            for file in sorted(files):
                if file.startswith("._") or file in (".DS_Store", "ai_hr_submission.zip"):
                    continue
                ext = os.path.splitext(file)[1].lower()
                if ext in EXCLUDE_EXTS:
                    continue

                full_path = Path(root) / file
                rel_path = full_path.relative_to(ROOT)
                zf.write(full_path, arcname=str(rel_path))
                packed_files.append(str(rel_path))

    # Compute SHA-256
    sha256 = hashlib.sha256(SUBMISSION_ZIP.read_bytes()).hexdigest()
    size_kb = SUBMISSION_ZIP.stat().st_size / 1024.0

    print(f"📦 Archive created: {SUBMISSION_ZIP.name}")
    print(f"📁 Total files packaged: {len(packed_files)}")
    print(f"💾 File size: {size_kb:.2f} KB")
    print(f"🔒 SHA-256 Checksum: {sha256}")
    return SUBMISSION_ZIP


if __name__ == "__main__":
    tests_ok = run_tests()
    if not tests_ok and "--force" not in sys.argv:
        print("Aborting packaging due to failing tests. Use --force to override.")
        sys.exit(1)
    setup_git_repo()
    zip_path = create_submission_zip()
    print("\n🎉 Submission preparation complete!")

