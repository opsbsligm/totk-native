"""Export a buildable source archive with per-file integrity and commit identity."""
import argparse
from pathlib import Path
from source_tree import archive_sources


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    archive_sources(Path(__file__).resolve().parents[1], a.output.resolve())
    print('Buildable source archive: ' + str(a.output.resolve()))


if __name__ == '__main__':
    main()
