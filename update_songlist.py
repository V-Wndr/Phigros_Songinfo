# -*- coding: utf-8 -*-
"""
从 info.tsv 更新 songlist.json：匹配曲目、对不存在的曲目提供曲包选择或创建新曲包，并智能生成 ID。
"""

import json
import re
import sys
from pathlib import Path
from datetime import date

# Windows 控制台兼容：尽量使用 UTF-8 输出
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def normalize_title(s: str) -> str:
    """规范化标题便于匹配：空白字符统一为普通空格并去除首尾。"""
    if not s:
        return ""
    s = " ".join(s.split())  # 任意空白（含 \xa0、全角空格）变为单个空格
    return s.strip()


def normalize_key(s: str) -> str:
    """去掉符号与空格的 key，与 difficulty.tsv 风格一致，用于匹配。"""
    if not s:
        return ""
    # 去掉空白与标点（含全角），只保留字母数字及 CJK，与 difficulty.tsv 风格一致
    s = re.sub(r"[\s\u00a0\u3000\.,;:!?()\[\]&'\"～\-]+", "", s)
    s = re.sub(r"[\u3000-\u303f\uff00-\uffef]", "", s)  # 去掉全角标点等（如 ：）
    s = re.sub(r"[^\w]", "", s, flags=re.UNICODE)  # 保留字母、数字、下划线、CJK
    return s.lower()  # 不区分大小写，使 Re：birth 与 Re：Birth 等匹配


def find_song_by_title(
    title: str, title_to_song: dict, data: list, key_to_song: dict
) -> tuple[int, dict] | None:
    """通过规范化标题或 key（去符号空格）匹配 songlist 中的曲目，支持 key 前缀匹配。"""
    norm = normalize_title(title)
    if norm and norm in title_to_song:
        return title_to_song[norm]
    key = normalize_key(title)
    if not key:
        return None
    if key in key_to_song:
        return key_to_song[key]
    # 前缀匹配：如 "The Mountain Eater" -> themountaineater 匹配 "The Mountain Eater from MUSYNC"
    if len(key) >= 4:
        for song in data:
            sk = normalize_key(song.get("标题") or "")
            if sk.startswith(key) or key.startswith(sk):
                return (data.index(song), song)
    return None


def load_songlist(path: Path) -> tuple[list, dict, list, dict]:
    """加载 songlist.json，返回 (data, title_to_song, packs_ordered, key_to_song)。"""
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    data = obj.get("data", [])
    title_to_song = {}
    key_to_song = {}
    for i, song in enumerate(data):
        title = normalize_title(song.get("标题") or "")
        if title:
            title_to_song[title] = (i, song)
        key = normalize_key(song.get("标题") or "")
        if key and key not in key_to_song:
            key_to_song[key] = (i, song)
        for alias in song.get("别称") or []:
            a = normalize_title(alias or "")
            if a and a not in title_to_song:
                title_to_song[a] = (i, song)
            ak = normalize_key(alias or "")
            if ak and ak not in key_to_song:
                key_to_song[ak] = (i, song)
    packs_ordered = []
    seen = set()
    for song in data:
        pack = song.get("曲包") or ""
        if pack and pack not in seen:
            seen.add(pack)
            packs_ordered.append(pack)
    return data, title_to_song, packs_ordered, key_to_song


def pack_to_id_prefix(pack_name: str) -> str:
    """将曲包显示名转为 ID 前缀（与现有规则一致：空格/连字符变下划线，合并连续下划线）。"""
    s = (pack_name or "").strip()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "Pack"


def last_index_of_pack(data: list, pack_name: str) -> int:
    """返回 data 中该曲包最后一条的索引，若无则返回 -1。"""
    last = -1
    for i, song in enumerate(data):
        if (song.get("曲包") or "") == pack_name:
            last = i
    return last


def get_pack_prefix_and_next_num(data: list, pack_name: str) -> tuple[str, int]:
    """根据 songlist 中该曲包已有 id 推断前缀与下一个序号。"""
    prefix = pack_to_id_prefix(pack_name)
    max_num = 0
    for song in data:
        if (song.get("曲包") or "") != pack_name:
            continue
        sid = song.get("id") or ""
        m = re.match(r"^(.+)_(\d+)$", sid)
        if m:
            p, n = m.group(1), int(m.group(2))
            if n > max_num:
                max_num = n
                prefix = p
    return prefix, max_num + 1


def load_difficulty_tsv(path: Path) -> dict:
    """
    加载 difficulty.tsv：第一列为 曲目key.制谱者，后面 3 个或 4 个数字对应 ez, hd, in [, at]。
    返回 key (normalize_key(曲目部分)) -> {"ez", "hd", "in", "at"?}。
    同一曲目多行时优先保留有 at 的那条。
    """
    result = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            title_part = parts[0].split(".", 1)[0]
            key = normalize_key(title_part)
            try:
                ez, hd, in_val = float(parts[1]), float(parts[2]), float(parts[3])
            except (ValueError, IndexError):
                continue
            at_val = None
            if len(parts) >= 5:
                try:
                    at_val = float(parts[4])
                except ValueError:
                    pass
            diff = {"ez": ez, "hd": hd, "in": in_val}
            if at_val is not None:
                diff["at"] = at_val
            if key not in result or ("at" in diff and "at" not in result.get(key, {})):
                result[key] = diff
    return result


def find_difficulty_for_song(song_title: str, difficulty_map: dict, data: list) -> dict | None:
    """根据曲目标题找到 difficulty_map 中对应的难度（key 或前缀匹配）。"""
    key = normalize_key(song_title or "")
    if not key:
        return None
    if key in difficulty_map:
        return difficulty_map[key]
    if len(key) >= 4:
        for diff_key, diff_val in difficulty_map.items():
            if diff_key.startswith(key) or key.startswith(diff_key):
                return diff_val
    return None


def apply_difficulties(data: list, difficulty_map: dict) -> int:
    """用 difficulty.tsv 的难度覆盖 songlist 中每条曲目的 难度，返回更新条数。"""
    updated = 0
    for song in data:
        diff = find_difficulty_for_song(song.get("标题") or "", difficulty_map, data)
        if diff is None:
            continue
        target = song.get("难度")
        if not isinstance(target, dict):
            song["难度"] = {}
            target = song["难度"]
        target["ez"] = diff["ez"]
        target["hd"] = diff["hd"]
        target["in"] = diff["in"]
        if "at" in diff:
            target["at"] = diff["at"]
        else:
            target["at"] = ""
        updated += 1
    return updated


def load_info_tsv(path: Path) -> list[dict]:
    """加载 info.tsv，每行：第一列 key，第二列标题，其余列保留。返回 [{"title": str, "row": list}, ...]"""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line:
                continue
            parts = line.split("\t")
            title = (parts[1] if len(parts) > 1 else "").strip()
            rows.append({"title": title, "row": parts})
    return rows


def new_song_entry(title: str, pack_name: str, new_id: str) -> dict:
    """生成一条新曲目条目。"""
    return {
        "标题": title,
        "bpm": 0,
        "难度": {"ez": 0, "hd": 0, "in": 0, "at": 0},
        "曲包": pack_name,
        "攻略链接": {"ez": "", "hd": "", "in": "", "at": ""},
        "id": new_id,
        "别称": [],
    }


def main():
    base = Path(__file__).resolve().parent
    songlist_path = base / "songlist.json"
    info_path = base / "info.tsv"

    if not songlist_path.exists():
        print(f"未找到 {songlist_path}")
        return
    if not info_path.exists():
        print(f"未找到 {info_path}")
        return

    difficulty_path = base / "difficulty.tsv"
    difficulty_map = {}
    if difficulty_path.exists():
        difficulty_map = load_difficulty_tsv(difficulty_path)

    data, title_to_song, packs_ordered, key_to_song = load_songlist(songlist_path)
    info_rows = load_info_tsv(info_path)

    missing = []
    for rec in info_rows:
        raw_title = rec["title"]
        title = normalize_title(raw_title)
        if not title:
            continue
        if find_song_by_title(title, title_to_song, data, key_to_song) is None:
            rec["normalized_title"] = title
            missing.append(rec)

    new_entries = []
    if missing:
        for rec in missing:
            print(f"  曲目: {rec.get('normalized_title', rec['title'])}")
        print("\n曲包列表（按序号选择）：")
        for idx, pack in enumerate(packs_ordered, start=1):
            print(f"  {idx}. {pack}")
        print("  0. 【创建新曲包】")
        pack_choice_map = {str(i): packs_ordered[i - 1] for i in range(1, len(packs_ordered) + 1)}

        for rec in missing:
            title = rec.get("normalized_title", rec["title"])
            while True:
                try:
                    choice = input(f"\n为「{title}」选择曲包序号 (0=新曲包): ").strip()
                except EOFError:
                    print("已跳过剩余曲目。")
                    break
                if choice == "0":
                    pack_name = input("请输入新曲包名称: ").strip()
                    if not pack_name:
                        print("曲包名不能为空，请重试。")
                        continue
                    if pack_name not in packs_ordered:
                        packs_ordered.append(pack_name)
                        pack_choice_map[str(len(packs_ordered))] = pack_name
                    prefix = pack_to_id_prefix(pack_name)
                    existing_in_new = sum(1 for e in new_entries if e.get("曲包") == pack_name)
                    next_num = existing_in_new + 1
                    for s in data:
                        if (s.get("曲包") or "") == pack_name:
                            sid = s.get("id") or ""
                            m = re.match(r"^.+_(\d+)$", sid)
                            if m:
                                next_num = max(next_num, int(m.group(1)) + 1)
                    new_id = f"{prefix}_{next_num}"
                    entry = new_song_entry(title, pack_name, new_id)
                    new_entries.append(entry)
                    last_i = last_index_of_pack(data, pack_name)
                    if last_i >= 0:
                        data.insert(last_i + 1, entry)
                    else:
                        data.append(entry)
                    print(f"  已加入新曲包「{pack_name}」，ID: {new_id}")
                    break
                if choice in pack_choice_map:
                    pack_name = pack_choice_map[choice]
                    prefix, next_num = get_pack_prefix_and_next_num(data, pack_name)
                    new_id = f"{prefix}_{next_num}"
                    entry = new_song_entry(title, pack_name, new_id)
                    new_entries.append(entry)
                    last_i = last_index_of_pack(data, pack_name)
                    data.insert(last_i + 1, entry)
                    print(f"  已加入曲包「{pack_name}」，ID: {new_id}")
                    break
                print("无效序号，请重新输入。")
    else:
        print("info.tsv 中所有曲目均已在 songlist 中存在。")

    updated_diff = 0
    if difficulty_map:
        updated_diff = apply_difficulties(data, difficulty_map)
        print(f"已从 difficulty.tsv 更新 {updated_diff} 首曲目的难度（ez/hd/in/at）。")

    if new_entries or updated_diff > 0:
        out = {
            "version": "1.0.0",
            "lastUpdate": date.today().isoformat(),
            "data": data,
        }
        with open(songlist_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=4)
        parts = []
        if new_entries:
            parts.append(f"新增 {len(new_entries)} 首曲目")
        if updated_diff > 0:
            parts.append(f"更新 {updated_diff} 条难度")
        print(f"\n已写回 songlist.json（{', '.join(parts)}）。")
    elif not missing:
        print("难度已是最新，未修改文件。")


if __name__ == "__main__":
    main()
