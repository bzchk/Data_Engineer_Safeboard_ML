"""Reject missing, extra or changed distributions in a digest-pinned base."""
from importlib.metadata import distributions
from pathlib import Path
import re
import sys

def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()

def installed():
    return {canonical(d.metadata["Name"]): d.version for d in distributions()}

if __name__ == "__main__":
    if sys.argv[1] == "--freeze":
        print("\n".join(f"{name}=={version}" for name, version in sorted(installed().items())))
    else:
        expected = {}
        for line in Path(sys.argv[1]).read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            name, version = line.split("==")
            expected[canonical(name)] = version
        if installed() != expected:
            raise SystemExit("Python environment does not match requirements lock")
        print(f"Verified {len(expected)} pinned distributions")
