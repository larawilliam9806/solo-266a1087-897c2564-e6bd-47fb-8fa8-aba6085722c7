"""三稿合稿：底稿 + 两份修改稿 → 一份可送印的稿件。

三稿沿用展板核查的 JSON 格式，但每片裁片必须带唯一 id，
同一裁片在三稿中沿用同一个 id。合并规则：

- 展板尺寸、原片清单、裁片编号集合、各裁片所用的原片必须一致，否则无法合稿；
- 裁框（crop）与落版位置（at）按裁片编号逐字段三方合并：
  只有一方改动、或两方改得一样 → 采用；两方都改且新值不同 → 记录冲突；
- 层序：任意两片，只要有一稿调换了上下关系就按调换后的顺序，
  两稿都没调换就保留底稿顺序；若这些关系成环，指出环上的裁片编号。

层序合并只使用位置表、入度数组等线性结构，不建立两两关系矩阵，
额外内存随裁片数线性增长（O(n)），时间 O(n²)。
"""

from collections import deque

from geometry import parse_input

# 参与三方合并的字段及其展示名
FIELD_NAMES = {
    "crop.x": "裁框 x",
    "crop.y": "裁框 y",
    "crop.w": "裁框宽 w",
    "crop.h": "裁框高 h",
    "at.x": "落版位置 x",
    "at.y": "落版位置 y",
}


def parse_draft(data, label):
    """解析一稿展板 JSON；合稿要求每片裁片都有唯一 id。"""
    try:
        board, photos, pieces = parse_input(data)
    except ValueError as e:
        raise ValueError(f"{label}：{e}") from e
    for i, pc in enumerate(pieces):
        if pc["id"] is None:
            raise ValueError(
                f"{label}：pieces[{i}] 缺少裁片编号 id，合稿要求每片裁片都有唯一 id")
    return board, photos, pieces


def _photo_map(photos):
    return {p["id"]: (p["credit"], p["permit"]) for p in photos}


def _consistency_errors(base, da, db):
    """核对三稿的展板尺寸、原片清单、裁片编号集合、各裁片所用原片。"""
    errors = []
    b_board, b_photos, b_pieces = base
    a_board, a_photos, a_pieces = da
    c_board, c_photos, c_pieces = db

    if a_board != b_board or c_board != b_board:
        errors.append(
            "展板尺寸不一致：底稿 %d×%d，修改稿甲 %d×%d，修改稿乙 %d×%d"
            % (b_board[2], b_board[3], a_board[2], a_board[3], c_board[2], c_board[3]))

    b_ph = _photo_map(b_photos)
    for label, photos in (("修改稿甲", a_photos), ("修改稿乙", c_photos)):
        m = _photo_map(photos)
        if set(m) != set(b_ph):
            parts = []
            missing = sorted(set(b_ph) - set(m))
            extra = sorted(set(m) - set(b_ph))
            if missing:
                parts.append("缺少原片 " + "、".join(missing))
            if extra:
                parts.append("多出原片 " + "、".join(extra))
            errors.append(f"原片清单不一致：{label}" + "，".join(parts))
        else:
            diff = [pid for pid in b_ph if m[pid] != b_ph[pid]]
            if diff:
                errors.append("原片清单不一致：{}中原片 {} 的署名或可刊矩形与底稿不同"
                              .format(label, "、".join(diff)))

    b_ids = [pc["id"] for pc in b_pieces]
    b_owner = {pc["id"]: pc["photo"] for pc in b_pieces}
    for label, pieces in (("修改稿甲", a_pieces), ("修改稿乙", c_pieces)):
        ids = [pc["id"] for pc in pieces]
        if set(ids) != set(b_ids):
            parts = []
            missing = sorted(set(b_ids) - set(ids))
            extra = sorted(set(ids) - set(b_ids))
            if missing:
                parts.append("缺少裁片 " + "、".join(missing))
            if extra:
                parts.append("多出裁片 " + "、".join(extra))
            errors.append(f"裁片编号集合不一致：{label}" + "，".join(parts))
        else:
            owner = {pc["id"]: pc["photo"] for pc in pieces}
            diff = [pid for pid in b_owner if owner[pid] != b_owner[pid]]
            if diff:
                errors.append("裁片所用原片不一致：{}中裁片 {} 的原片与底稿不同"
                              .format(label, "、".join(diff)))
    return errors


def _piece_fields(pc):
    """取一片裁片参与合并的六个数值字段。"""
    x0, y0, x1, y1 = pc["crop"]
    ax, ay = pc["at"]
    return {"crop.x": x0, "crop.y": y0, "crop.w": x1 - x0, "crop.h": y1 - y0,
            "at.x": ax, "at.y": ay}


def _merge_fields(base, da, db):
    """裁框与落版位置按编号逐字段三方合并。

    返回 (merged, conflicts)：
    merged    —— {裁片 id: {字段名: 合并值}}；
    conflicts —— [{"id", "field", "label", "base", "a", "b"}]，
                  两方都改且新值不同的字段。
    """
    a_map = {pc["id"]: pc for pc in da[2]}
    b_map = {pc["id"]: pc for pc in db[2]}
    merged = {}
    conflicts = []
    for pc in base[2]:
        pid = pc["id"]
        vf = _piece_fields(pc)
        va = _piece_fields(a_map[pid])
        vb = _piece_fields(b_map[pid])
        out = {}
        for name, label in FIELD_NAMES.items():
            v0, v1, v2 = vf[name], va[name], vb[name]
            if v1 == v2:        # 两方改得一样（或都没改）
                out[name] = v1
            elif v1 == v0:      # 只有乙改了
                out[name] = v2
            elif v2 == v0:      # 只有甲改了
                out[name] = v1
            else:               # 两方都改且新值不同
                conflicts.append({"id": pid, "field": name, "label": label,
                                  "base": v0, "a": v1, "b": v2})
        merged[pid] = out
    return merged, conflicts


def merge_order(base_ids, a_ids, b_ids):
    """合并三稿层序（id 列表，从下到上）。

    规则：任意两片，只要有一稿调换了上下关系就按调换后的顺序，
    两稿都没调换就保留底稿顺序。

    返回 (order, cycle)：
    - 关系无环：order 为合并后的 id 列表（从下到上），cycle 为 None；
    - 关系成环：order 为 None，cycle 为环上裁片 id（按环的顺序排列，
      相邻两个前者在下、后者在上，末尾与开头也相邻）。

    额外内存 O(n)：只保存位置表、入度数组、访问标记等线性结构，
    不建立两两关系矩阵。
    """
    n = len(base_ids)
    pos_base = {pid: i for i, pid in enumerate(base_ids)}
    pos_a = {pid: i for i, pid in enumerate(a_ids)}
    pos_b = {pid: i for i, pid in enumerate(b_ids)}

    def swapped(u, v):
        """底稿中 u 在 v 之下时，是否有修改稿调换了二者的上下关系。"""
        return pos_a[u] > pos_a[v] or pos_b[u] > pos_b[v]

    def is_below(u, v):
        """合并后的关系中 u 是否在 v 之下。"""
        if pos_base[u] < pos_base[v]:
            return not swapped(u, v)
        return swapped(v, u)

    # 每片之下压着的裁片数（合并关系的入度）。两两比较，只存计数。
    deg = [0] * n
    for i in range(n):
        for j in range(i + 1, n):
            if swapped(base_ids[i], base_ids[j]):
                deg[i] += 1   # 调换后 base_ids[j] 压到 base_ids[i] 之下
            else:
                deg[j] += 1

    # 竞赛图可传递 ⟺ 入度恰好是 0..n-1；此时按入度升序即合并层序
    if sorted(deg) == list(range(n)):
        order = [base_ids[k] for k in sorted(range(n), key=lambda k: deg[k])]
        return order, None

    # 关系成环。按入度升序排列后必存在"逆序对"：靠后的片反而压在靠前的片
    # 之下，且从被压者沿"在下→在上"的边必能走回压它者，拼成一个环
    # （非传递竞赛图的标准性质）。
    perm = sorted(range(n), key=lambda k: deg[k])
    start = goal = None
    for x in range(n):
        for y in range(x + 1, n):
            if is_below(base_ids[perm[y]], base_ids[perm[x]]):
                start, goal = perm[x], perm[y]
                break
        if start is not None:
            break

    # 从 start 沿"在下 → 在上"的边广度优先搜索到 goal
    prev = [-2] * n
    prev[start] = -1
    dq = deque([start])
    while dq:
        cur = dq.popleft()
        if cur == goal:
            break
        u = base_ids[cur]
        for k in range(n):
            if prev[k] == -2 and is_below(u, base_ids[k]):
                prev[k] = cur
                dq.append(k)

    path = []
    node = goal
    while node != -1:
        path.append(node)
        node = prev[node]
    path.reverse()
    # path 为 start→…→goal 的链，goal 又压在 start 之下，正好成环
    return None, [base_ids[k] for k in path]


def _merged_json(base, fields, order):
    """按合并结果生成展板 JSON（保留裁片编号，可回传原核查页）。"""
    board, photos, pieces = base
    owner = {pc["id"]: pc["photo"] for pc in pieces}
    out_photos = []
    for p in photos:
        x0, y0, x1, y1 = p["permit"]
        out_photos.append({"id": p["id"], "credit": p["credit"],
                           "permit": {"x": x0, "y": y0,
                                      "w": x1 - x0, "h": y1 - y0}})
    out_pieces = []
    for pid in order:
        f = fields[pid]
        out_pieces.append({
            "id": pid,
            "photo": owner[pid],
            "crop": {"x": f["crop.x"], "y": f["crop.y"],
                     "w": f["crop.w"], "h": f["crop.h"]},
            "at": {"x": f["at.x"], "y": f["at.y"]},
        })
    return {"board": {"width": board[2], "height": board[3]},
            "photos": out_photos, "pieces": out_pieces}


def merge_documents(base_data, a_data, b_data):
    """三稿合稿。输入为底稿、修改稿甲、修改稿乙的 JSON 数据。

    返回结果字典：
    - errors    ：三稿不一致的问题列表（非空则无法合稿）；
    - conflicts ：字段冲突列表，每项指出裁片编号、字段及三稿的值；
    - cycle     ：层序成环时环上的裁片编号列表，否则为 None；
    - merged    ：无冲突且无环时的合稿 JSON（保留裁片编号），否则为 None。

    输入不合法（JSON 结构错误、裁片缺 id 等）抛 ValueError。
    """
    base = parse_draft(base_data, "底稿")
    da = parse_draft(a_data, "修改稿甲")
    db = parse_draft(b_data, "修改稿乙")

    result = {"errors": _consistency_errors(base, da, db),
              "conflicts": [], "cycle": None, "merged": None}
    if result["errors"]:
        return result

    fields, conflicts = _merge_fields(base, da, db)
    result["conflicts"] = conflicts

    order, cycle = merge_order([pc["id"] for pc in base[2]],
                               [pc["id"] for pc in da[2]],
                               [pc["id"] for pc in db[2]])
    result["cycle"] = cycle

    if not conflicts and cycle is None:
        result["merged"] = _merged_json(base, fields, order)
    return result
