import sys

import yaml


def main() -> int:
    raw = sys.stdin.buffer.read().split(b"\0")
    data = {}
    it = iter(raw)
    for key in it:
        if not key:
            break
        try:
            value = next(it)
        except StopIteration:
            break
        data[key.decode()] = value.decode()

    if not data:
        return 0

    sys.stdout.write(
        yaml.safe_dump(
            data,
            default_flow_style=False,
            default_style='"',
            sort_keys=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
