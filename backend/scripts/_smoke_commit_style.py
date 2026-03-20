import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.services.commit_style_analyzer import (  # noqa: E402
    analyze_github_commit_detail,
    conventional_commit_pct,
    rollup_style_from_commits,
)


def main() -> None:
    detail = {
        "stats": {"additions": 10, "deletions": 2},
        "files": [
            {
                "filename": "src/a.py",
                "patch": "@@ -0,0 +1,3 @@\n+    x = 1\n+    y = 2\n",
                "additions": 10,
                "deletions": 0,
            },
            {
                "filename": "tests/test_a.py",
                "patch": "+def test():\n+    pass\n",
                "additions": 2,
                "deletions": 0,
            },
        ],
    }
    d = analyze_github_commit_detail(detail)
    assert d and d["file_count"] == 2 and d["testish_files"] >= 1, d
    assert abs(conventional_commit_pct(["feat: x", "wip"]) - 50.0) < 0.01

    class Row:
        commit_style_json: str

    r = Row()
    r.commit_style_json = json.dumps(d)
    tags, mix, n = rollup_style_from_commits([r])  # type: ignore[list-item]
    assert n == 1 and tags and mix, (tags, mix, n)
    print("smoke_commit_style_ok", tags[0][:40])


if __name__ == "__main__":
    main()
