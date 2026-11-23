import json
import secrets
import threading

from flask import Flask, Response, abort, render_template, request

from geometry import analyze
from merge import merge_documents

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 上传 JSON 上限 16MB

# 下载暂存（署名 CSV / 合稿 JSON），容量有限，与画布像素数无关
_store = {}
_store_lock = threading.Lock()
_STORE_CAP = 32


def _stash(item):
    """暂存 (文件名, 文本内容, MIME)，返回下载令牌。"""
    token = secrets.token_urlsafe(12)
    with _store_lock:
        while len(_store) >= _STORE_CAP:
            _store.pop(next(iter(_store)))
        _store[token] = item
    return token


def _load_json(fileobj, label=""):
    """读取一个上传的 JSON 文件，返回 (数据, 错误消息)。"""
    prefix = f"{label} " if label else ""
    try:
        return json.load(fileobj), None
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, f"{prefix}JSON 解析失败：{e}"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze_route():
    f = request.files.get("file")
    if f is None or f.filename == "":
        return render_template("index.html", error="请选择一个 JSON 文件"), 400
    data, err = _load_json(f)
    if err:
        return render_template("index.html", error=err), 400
    try:
        report = analyze(data)
    except ValueError as e:
        return render_template("index.html", error=f"输入不合法：{e}"), 400
    token = _stash(("credits.csv", report["csv"], "text/csv")) if report["clean"] else None
    return render_template("result.html", report=report, token=token)


@app.route("/merge")
def merge_form():
    return render_template("merge.html")


@app.route("/merge", methods=["POST"])
def merge_route():
    drafts = {}
    for key, label in (("base", "底稿"), ("draft_a", "修改稿甲"), ("draft_b", "修改稿乙")):
        f = request.files.get(key)
        if f is None or f.filename == "":
            return render_template("merge.html", error=f"请选择{label}的 JSON 文件"), 400
        data, err = _load_json(f, label)
        if err:
            return render_template("merge.html", error=err), 400
        drafts[key] = data
    try:
        result = merge_documents(drafts["base"], drafts["draft_a"], drafts["draft_b"])
    except ValueError as e:
        return render_template("merge.html", error=f"输入不合法：{e}"), 400
    report = token = None
    if result["merged"] is not None:
        report = analyze(result["merged"])  # 合稿后重新核对刊用范围
        if report["clean"]:
            text = json.dumps(result["merged"], ensure_ascii=False, indent=2)
            token = _stash(("merged.json", text, "application/json"))
    return render_template("merge_result.html", result=result, report=report, token=token)


@app.route("/download/<token>")
def download(token):
    with _store_lock:
        item = _store.get(token)
    if item is None:
        abort(404)
    filename, text, mimetype = item
    body = text.encode("utf-8-sig") if mimetype == "text/csv" else text.encode("utf-8")
    return Response(
        body,
        mimetype=mimetype,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
