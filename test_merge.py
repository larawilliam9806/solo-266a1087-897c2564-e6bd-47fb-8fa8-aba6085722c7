"""merge 模块的单元测试：python3 test_merge.py"""
import json
import random

import geometry
import merge


def photo(pid, permit, credit="某"):
    return {"id": pid, "credit": credit,
            "permit": {"x": permit[0], "y": permit[1],
                       "w": permit[2] - permit[0], "h": permit[3] - permit[1]}}


def piece(pid, photo_id, crop, at):
    return {"id": pid, "photo": photo_id,
            "crop": {"x": crop[0], "y": crop[1],
                     "w": crop[2] - crop[0], "h": crop[3] - crop[1]},
            "at": {"x": at[0], "y": at[1]}}


def draft(photos, pieces, board=(1000, 800)):
    return {"board": {"width": board[0], "height": board[1]},
            "photos": photos, "pieces": pieces}


PHOTOS = [photo("P1", (0, 0, 100, 100), "甲"), photo("P2", (0, 0, 100, 100), "乙")]
BASE_PIECES = [
    piece("c1", "P1", (0, 0, 10, 10), (0, 0)),
    piece("c2", "P2", (0, 0, 20, 20), (50, 50)),
    piece("c3", "P1", (5, 5, 15, 15), (100, 100)),
]
BASE = draft(PHOTOS, BASE_PIECES)


def with_pieces(pieces, board=(1000, 800), photos=PHOTOS):
    return draft(photos, pieces, board)


def merged_piece(result, pid):
    return next(p for p in result["merged"]["pieces"] if p["id"] == pid)


# 1. 只有一方改动 → 采用改动后的值
a = with_pieces([
    piece("c1", "P1", (2, 3, 12, 13), (0, 0)),   # 甲改了 c1 的裁框
    piece("c2", "P2", (0, 0, 20, 20), (50, 50)),
    piece("c3", "P1", (5, 5, 15, 15), (100, 100)),
])
r = merge.merge_documents(BASE, a, BASE)
assert r["errors"] == [] and r["conflicts"] == [] and r["cycle"] is None
c1 = merged_piece(r, "c1")
assert c1["crop"] == {"x": 2, "y": 3, "w": 10, "h": 10}
assert c1["at"] == {"x": 0, "y": 0}
assert merged_piece(r, "c2")["crop"] == {"x": 0, "y": 0, "w": 20, "h": 20}

# 2. 两方改得一样 → 采用
b = with_pieces([
    piece("c1", "P1", (0, 0, 10, 10), (7, 8)),   # 甲乙都把 c1 挪到 (7,8)
    piece("c2", "P2", (0, 0, 20, 20), (50, 50)),
    piece("c3", "P1", (5, 5, 15, 15), (100, 100)),
])
r = merge.merge_documents(BASE, b, b)
assert r["conflicts"] == [] and r["merged"] is not None
assert merged_piece(r, "c1")["at"] == {"x": 7, "y": 8}

# 3. 两方都改且新值不同 → 指出裁片和字段
a = with_pieces([
    piece("c1", "P1", (0, 0, 10, 10), (1, 0)),
    piece("c2", "P2", (0, 0, 20, 20), (50, 50)),
    piece("c3", "P1", (5, 5, 15, 15), (100, 100)),
])
b = with_pieces([
    piece("c1", "P1", (0, 0, 10, 10), (2, 0)),
    piece("c2", "P2", (0, 0, 20, 20), (50, 50)),
    piece("c3", "P1", (5, 5, 15, 15), (100, 100)),
])
r = merge.merge_documents(BASE, a, b)
assert r["merged"] is None
assert len(r["conflicts"]) == 1
c = r["conflicts"][0]
assert c["id"] == "c1" and c["field"] == "at.x"
assert (c["base"], c["a"], c["b"]) == (0, 1, 2)

# 4. 三稿一致性核对
# 4a. 展板尺寸不一致
bad = with_pieces(BASE_PIECES, board=(1200, 800))
r = merge.merge_documents(BASE, bad, BASE)
assert r["merged"] is None and any("展板尺寸" in e for e in r["errors"])

# 4b. 原片清单不一致（可刊矩形不同 / 编号集合不同）
bad = draft([photo("P1", (0, 0, 100, 100), "甲"), photo("P2", (0, 0, 90, 90), "乙")],
            BASE_PIECES)
r = merge.merge_documents(BASE, BASE, bad)
assert any("原片清单" in e for e in r["errors"])
bad = draft([photo("P1", (0, 0, 100, 100), "甲"), photo("P9", (0, 0, 100, 100), "乙")],
            [piece("c1", "P1", (0, 0, 10, 10), (0, 0)),
             piece("c2", "P9", (0, 0, 20, 20), (50, 50)),
             piece("c3", "P1", (5, 5, 15, 15), (100, 100))])
r = merge.merge_documents(BASE, bad, BASE)
assert any("原片清单" in e for e in r["errors"])

# 4c. 裁片编号集合不一致
bad = with_pieces([
    piece("c1", "P1", (0, 0, 10, 10), (0, 0)),
    piece("c2", "P2", (0, 0, 20, 20), (50, 50)),
    piece("c9", "P1", (5, 5, 15, 15), (100, 100)),   # c3 变成了 c9
])
r = merge.merge_documents(BASE, BASE, bad)
assert any("裁片编号集合" in e for e in r["errors"])

# 4d. 各裁片所用原片不一致
bad = with_pieces([
    piece("c1", "P1", (0, 0, 10, 10), (0, 0)),
    piece("c2", "P1", (0, 0, 20, 20), (50, 50)),     # c2 的原片被换成 P1
    piece("c3", "P1", (5, 5, 15, 15), (100, 100)),
])
r = merge.merge_documents(BASE, bad, BASE)
assert any("所用原片" in e for e in r["errors"])

# 5. 层序：只有一稿调换了一对 → 按调换后的顺序
a = with_pieces([BASE_PIECES[1], BASE_PIECES[0], BASE_PIECES[2]])  # 甲调换 c1/c2
r = merge.merge_documents(BASE, a, BASE)
assert r["cycle"] is None and r["merged"] is not None
assert [p["id"] for p in r["merged"]["pieces"]] == ["c2", "c1", "c3"]

# 6. 层序：两稿调换了同一对 → 仍按调换后的顺序
r = merge.merge_documents(BASE, a, a)
assert [p["id"] for p in r["merged"]["pieces"]] == ["c2", "c1", "c3"]

# 7. 层序：两稿都没调换 → 保留底稿顺序
r = merge.merge_documents(BASE, BASE, BASE)
assert [p["id"] for p in r["merged"]["pieces"]] == ["c1", "c2", "c3"]

# 8. 层序成环 → 指出环上的裁片编号
# 底稿 c1<c2<c3；甲调换 c1/c2，乙调换 c2/c3 → c2<c1、c3<c2、c1<c3 成环
b = with_pieces([BASE_PIECES[0], BASE_PIECES[2], BASE_PIECES[1]])
r = merge.merge_documents(BASE, a, b)
assert r["merged"] is None and r["cycle"] is not None
assert set(r["cycle"]) == {"c1", "c2", "c3"}

# 9. 随机验证：合并结果要么满足全部两两规则，要么给出真实存在的环
rng = random.Random(20261123)
for _ in range(40):
    n = rng.randint(2, 60)
    ids = [f"c{i}" for i in range(n)]
    pa = ids[:]
    rng.shuffle(pa)
    pb = ids[:]
    rng.shuffle(pb)
    order, cycle = merge.merge_order(ids, pa, pb)
    pos0 = {p: i for i, p in enumerate(ids)}
    posa = {p: i for i, p in enumerate(pa)}
    posb = {p: i for i, p in enumerate(pb)}

    def below(u, v):  # 按规则直接计算的两两关系
        if pos0[u] < pos0[v]:
            return not (posa[u] > posa[v] or posb[u] > posb[v])
        return posa[v] > posa[u] or posb[v] > posb[u]

    if order is not None:
        assert cycle is None
        assert sorted(order) == sorted(ids)
        for i in range(n):
            for j in range(i + 1, n):
                assert below(order[i], order[j])
                assert not below(order[j], order[i])
    else:
        assert len(cycle) >= 3
        for k in range(len(cycle)):
            u, v = cycle[k], cycle[(k + 1) % len(cycle)]
            assert below(u, v), f"环上边 {u}->{v} 不成立"

# 10. 合稿 JSON 可直接核查：JSON 往返后 analyze 接受，id 保留
a = with_pieces([
    piece("c1", "P1", (0, 0, 10, 10), (7, 8)),
    piece("c2", "P2", (0, 0, 20, 20), (50, 50)),
    piece("c3", "P1", (5, 5, 15, 15), (100, 100)),
])
r = merge.merge_documents(BASE, a, BASE)
again = json.loads(json.dumps(r["merged"], ensure_ascii=False))
assert all(isinstance(p["id"], str) for p in again["pieces"])
rep = geometry.analyze(again)
assert rep["piece_count"] == 3 and rep["clean"]

# 11. 合稿后重新核对刊用范围：改动造成缺口时能被发现
a = with_pieces([
    piece("c1", "P1", (0, 0, 10, 10), (0, 0)),
    piece("c2", "P2", (0, 0, 20, 20), (50, 50)),
    piece("c3", "P1", (90, 90, 130, 130), (100, 100)),  # 裁框越出 P1 的可刊矩形
])
r = merge.merge_documents(BASE, a, BASE)
assert r["merged"] is not None
rep = geometry.analyze(r["merged"])
assert not rep["clean"] and rep["total_unlicensed"] > 0

# 12. 无 id 的旧格式仍可核查，但不能合稿
old = draft(PHOTOS, [
    {"photo": "P1", "crop": {"x": 0, "y": 0, "w": 5, "h": 5}, "at": {"x": 0, "y": 0}},
])
assert geometry.analyze(old)["clean"]
try:
    merge.merge_documents(old, old, old)
except ValueError as e:
    assert "id" in str(e)
else:
    raise AssertionError("合稿应当拒绝缺少裁片 id 的稿件")

# 13. 核查拒绝重复的裁片 id
dup = draft(PHOTOS, [
    piece("c1", "P1", (0, 0, 5, 5), (0, 0)),
    piece("c1", "P1", (0, 0, 5, 5), (1, 1)),
])
try:
    geometry.analyze(dup)
except ValueError as e:
    assert "重复" in str(e)
else:
    raise AssertionError("应当拒绝重复的裁片编号")

print("全部测试通过")
