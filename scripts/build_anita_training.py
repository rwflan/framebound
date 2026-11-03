"""Build the private Anita engineering feature shard."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from framebound.v3.campaign.anita import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--native-size', type=int, default=256)
    args = parser.parse_args()
    result = build(
        args.source,
        version=args.version,
        output=args.output,
        native_size=args.native_size,
    )
    print(json.dumps(dict(
        version=result['version'],
        path=result['path'],
        counts=result['counts'],
        feature_manifest=result['manifest']['feature_manifest'],
    ), indent=2))


if __name__ == '__main__':
    main()
