# -*- coding: utf-8 -*-
"""只读解析 NX Check-Mate 的 .dfa 规则文件（Knowledge Fusion 纯文本）。

只提取**判定口径**：参数名、类型、默认值、说明，以及 do_check 里出现的比较算子
和引用的参数。Siemens 的原始文件不进入仓库；如需在本机留档，用 --raw-dir 写到
.gitignore 保护的 .local/ 下。

用法：
    python tools/checkmate/extract_dfa.py <某个.dfa>
    python tools/checkmate/extract_dfa.py --checkmate-root --name-contains sheet_metal_thickness
    python tools/checkmate/extract_dfa.py <某个.dfa> --raw-dir .local/checkmate_raw

输出：JSON 到 stdout（一个文件 = 一个对象，目录 = 数组）。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

#: 文档式参数条目：``( Number )  ld_ratio_max  - ... the default value is 5.``
_DOC_ENTRY = re.compile(r"^\s*\(\s*(?P<type>[A-Za-z][A-Za-z0-9_ ]*?)\s*\)\s+(?P<name>[A-Za-z_]\w*)\s*[-:]\s+?(?P<rest>.*)$")
#: 类声明式参数：``( Number Parameter ) draft_angle: 3.0;``
_CLASS_PARAM = re.compile(r"^\s*\(\s*(?P<type>[A-Za-z][A-Za-z0-9_ ]*?\bParameter)\s*\)\s+(?P<name>[A-Za-z_]\w*)\s*:\s*(?P<value>[^;]*);")
_DEFAULT = re.compile(r"[Tt]he default (?:value )?is\s*:?\s+(?P<value>.+?)(?:\.\s*$|\s*$)")
_DECORATION = re.compile(r"^\s*\*{3,}.*$|\*{3,}.*$")
_COMPARE = re.compile(r"(>=|<=|==|!=|>|<)")
_DESCRIPTION = re.compile(r"<Description>(?P<body>.*?)</Description>", re.S)


def find_checkmate_root() -> str:
    """按 UGII_BASE_DIR / 常见安装位置找 Check-Mate 目录。"""
    candidates = []
    base = os.environ.get("UGII_BASE_DIR")
    if base:
        candidates.append(os.path.join(base, "DESIGN_TOOLS", "checkmate"))
    for root in (r"C:\Program Files\Siemens", r"C:\Siemens", r"D:\Siemens"):
        for child in sorted(glob.glob(os.path.join(root, "*")), reverse=True):
            candidates.append(os.path.join(child, "DESIGN_TOOLS", "checkmate"))
    for path in candidates:
        if os.path.isdir(path):
            return path
    raise SystemExit("未找到 Check-Mate 目录，请设置 UGII_BASE_DIR 或用 --checkmate-root 指定")


def _title(text: str) -> str:
    match = _DESCRIPTION.search(text)
    if not match:
        return ""
    for line in match.group("body").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _section(text: str, tag: str) -> str:
    start = text.find("<" + tag + ">")
    if start < 0:
        return ""
    end = text.find("</" + tag + ">", start)
    return text[start + len(tag) + 2 : end if end >= 0 else len(text)]


def _parse_doc_parameters(section: str) -> list[dict]:
    lines = section.splitlines()
    entries: list[dict] = []
    current = None
    for line in lines:
        doc = _DOC_ENTRY.match(line)
        if doc and not doc.group("type").endswith("Parameter"):
            if current:
                entries.append(current)
            current = {
                "name": doc.group("name"),
                "type": doc.group("type").strip(),
                "default": "",
                "description": doc.group("rest").strip(),
            }
            continue
        if current is None:
            continue
        default = _DEFAULT.search(line)
        if default and not current["default"]:
            current["default"] = default.group("value").strip().rstrip(".")
            continue
        stripped = _DECORATION.sub("", line).strip()
        if stripped:
            current["description"] += " " + stripped
    if current:
        entries.append(current)
    for entry in entries:
        entry["description"] = re.sub(r"\s+", " ", entry["description"]).strip()[:400]
    return entries


def _parse_class_parameters(text: str) -> list[dict]:
    entries = []
    for line in text.splitlines():
        match = _CLASS_PARAM.match(line)
        if match and not match.group("type").startswith("String Parameter"):
            entries.append(
                {
                    "name": match.group("name"),
                    "type": match.group("type").strip(),
                    "default": match.group("value").strip(),
                    "description": "",
                }
            )
    return entries


def extract(path: str) -> dict:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    doc_params = _parse_doc_parameters(_section(text, "Parameters"))
    class_params = _parse_class_parameters(text) if not doc_params else []
    parameters = doc_params or class_params

    do_check = ""
    marker = text.find("do_check")
    if marker >= 0:
        do_check = text[marker : marker + 20000]
    ops = sorted(set(_COMPARE.findall(do_check)))
    referenced = sorted(
        {p["name"] for p in parameters if re.search(r"\b" + re.escape(p["name"]) + r"\b", do_check)}
    )
    return {
        "file": os.path.abspath(path),
        "name": os.path.basename(path),
        "title": _title(text),
        "parameters": parameters,
        "do_check": {
            "present": bool(do_check),
            "comparison_ops": ops,
            "referenced_parameters": referenced,
        },
        "bytes": len(text.encode("utf-8", errors="ignore")),
    }


def _iter_targets(args) -> list[str]:
    targets: list[str] = []
    for item in args.paths:
        if os.path.isdir(item):
            targets.extend(glob.glob(os.path.join(item, "**", "*.dfa"), recursive=True))
        else:
            targets.append(item)
    if args.checkmate_root:
        root = args.paths[0] if args.paths else find_checkmate_root()
        targets.extend(glob.glob(os.path.join(root, "**", "*.dfa"), recursive=True))
    targets = [t for t in targets if os.path.isfile(t)]
    if args.name_contains:
        needle = args.name_contains.lower()
        targets = [t for t in targets if needle in os.path.basename(t).lower()]
    return sorted(set(targets))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help=".dfa 文件或目录")
    parser.add_argument("--checkmate-root", action="store_true", help="扫描整个 Check-Mate 目录（可配合 paths 指定根）")
    parser.add_argument("--name-contains", default="", help="只保留文件名包含该子串的规则")
    parser.add_argument("--raw-dir", default="", help="把原文摘录写到该目录（建议 .local/ 下，不入库）")
    parser.add_argument("--limit", type=int, default=0, help="最多输出前 N 个（0 = 不限）")
    args = parser.parse_args(argv)

    targets = _iter_targets(args)
    if not targets:
        print("没有找到 .dfa 文件", file=sys.stderr)
        return 1
    if args.limit:
        targets = targets[: args.limit]

    results = []
    for path in targets:
        try:
            result = extract(path)
        except Exception as exc:  # 单个文件解析失败不影响其它
            result = {"file": os.path.abspath(path), "error": f"{type(exc).__name__}: {exc}"}
        results.append(result)
        if args.raw_dir:
            os.makedirs(args.raw_dir, exist_ok=True)
            with open(path, "r", encoding="utf-8", errors="replace") as src:
                raw = src.read()
            with open(os.path.join(args.raw_dir, os.path.basename(path) + ".txt"), "w", encoding="utf-8") as dst:
                dst.write(raw)

    payload = results[0] if len(results) == 1 else results
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
