"""Apply reviewed integration patches only to clean, exact upstream baselines."""

import argparse
import subprocess
from pathlib import Path

BASELINES = {
    "frappe": "2fcb9397a1f1da353b21e53d2f97ec56653acd02",
    "erpnext": "9cd11b19575bfc34f092a24f6c8b368c4dd69481",
}


def apply(project, checkout, check_only=False):
    root = checkout.resolve()
    patch = Path(__file__).resolve().parent / "patches" / f"{project}.patch"

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(root), *args], text=True, capture_output=True, check=True
        ).stdout.strip()

    if git("rev-parse", "HEAD") != BASELINES[project]:
        raise ValueError(f"{project} is not at the reviewed commit")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError(f"{project} checkout has changes; use a fresh checkout")
    git("apply", "--check", str(patch))
    if not check_only:
        git("apply", str(patch))
    return project


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project", choices=BASELINES)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    apply(args.project, args.checkout, args.check)
    print("Patch verified" if args.check else "Patch applied")
