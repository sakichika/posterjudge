from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import asyncio
import threading
from math import ceil

lock = threading.Lock()

import os
import json
import random
import string

app = Flask(__name__)
app.secret_key = "your_secret_key"

# Admin credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"

# File to store judges
JUDGES_FILE = "judges.json"
POSTERS_FILE = "posters.json"

# Default settings
app.config["MAX_POSTERS_PER_JUDGE"] = 6

# Load posters from JSON
def load_posters():
    if os.path.exists(POSTERS_FILE):
        with open(POSTERS_FILE, "r") as f:
            return json.load(f)
    return [{"id": i, "title": f"Poster {i}", "max_judges": 6, "current_judges": 0} for i in range(1, 21)]

# Save posters to JSON
def save_posters(posters):
    with open(POSTERS_FILE, "w") as f:
        json.dump(posters, f, indent=4)

# Load judges from JSON
def load_judges():
    if os.path.exists(JUDGES_FILE):
        with open(JUDGES_FILE, "r") as f:
            return json.load(f)
        return {}

# Save judges to JSON
def save_judges(judges_data):
    with open("judges.json", "w") as file:
        json.dump(judges_data, file, indent=4)

# Initialize judges dictionary
judges = load_judges()
posters = load_posters()

# Generate random token
def generate_token(length=16):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=length))

# Routes
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        token = request.form["token"]
        if token in judges:
            return redirect(url_for("judge_page", token=token))
        else:
            return render_template("index.html",error="Invalid token.")
    return render_template("index.html")

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            print("Login successful")
            return redirect(url_for("admin_dashboard"))  # 管理画面にリダイレクト
        else:
            print("Login failed: Invalid credentials")
            return render_template("admin_login.html", error="Invalid credentials.")
    
    print("Rendering login page")
    return render_template("admin_login.html")

@app.route("/admin/dashboard", methods=["GET", "POST"])
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    
    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_judge":
            name = request.form.get("name")
            token = generate_token()
            judges[token] = {"name": name, "selected_posters": []}
            save_judges(judges)

        elif action == "edit_judge_name":
            token = request.form.get("token")
            new_name = request.form.get("new_name")
            if token in judges:
                judges[token]["name"] = new_name
                save_judges(judges)

        elif action == "delete_poster":
            try:
                poster_id = int(request.form.get("poster_id", 0))  # デフォルト値を0に設定
                if poster_id == 0:
                    return "Invalid poster ID1", 400

                # ポスターの削除
                poster_to_delete = next((p for p in posters if p["id"] == poster_id), None)
                if not poster_to_delete:
                    return "Poster not found", 404

                posters.remove(poster_to_delete)

                # 削除したポスターを選択していた審査員からも削除
                for token in judges:
                    if poster_id in judges[token]["selected_posters"]:
                        judges[token]["selected_posters"].remove(poster_id)

                save_posters(posters)
                save_judges(judges)
                return "Poster deleted successfully", 200
            except ValueError:
                return "Invalid poster ID2", 400


        elif action == "regenerate_token":
            old_token = request.form.get("old_token")
            if old_token in judges:
                new_token = generate_token(16)
                while new_token in judges:
                    new_token = generate_token(16)
                judges[new_token] = judges.pop(old_token)
                save_judges(judges)

        elif action == "remove_poster_from_judge":
            token = request.form.get("token")
            poster_id = int(request.form.get("poster_id"))
            if token in judges and poster_id in judges[token]["selected_posters"]:
                judges[token]["selected_posters"].remove(poster_id)
                poster = next((p for p in posters if p["id"] == poster_id), None)
                if poster:
                    poster["current_judges"] -= 1
                save_judges(judges)
                save_posters(posters)

        elif action == "add_poster":
            title = request.form.get("title")
            max_judges = int(request.form.get("max_judges"))
            new_id = max(p["id"] for p in posters) + 1 if posters else 1
            posters.append({"id": new_id, "title": title, "max_judges": max_judges, "current_judges": 0})
            save_posters(posters)

        elif action == "delete_poster":
            poster_id = int(request.form.get("poster_id"))
            posters[:] = [p for p in posters if p["id"] != poster_id]
            for token in judges:
                if poster_id in judges[token]["selected_posters"]:
                    judges[token]["selected_posters"].remove(poster_id)
            save_posters(posters)
            save_judges(judges)

        elif action == "edit_poster":
            try:
                poster_id = int(request.form["poster_id"])
                poster = next((p for p in posters if p["id"] == poster_id), None)

                if poster:
                    # 更新されたデータを取得
                    poster["number"] = request.form["number"]
                    poster["title"] = request.form["title"]
                    poster["presenter"] = request.form["presenter"]
                    poster["coauthors"] = request.form["coauthors"].split(",")  # カンマ区切りの文字列をリストに変換
                    poster["affiliations"] = request.form["affiliations"].split(",")
                    poster["abstract"] = request.form["abstract"]
                    poster["max_judges"] = int(request.form["max_judges"])

                    # 保存
                    save_posters(posters)
                    message = f"Poster {poster_id} updated successfully!"
                else:
                    message = f"Poster {poster_id} not found."
            except Exception as e:
                message = f"Error updating poster: {str(e)}"

    # 名前順でソートされた審査員リストを生成
    sorted_judges = dict(sorted(judges.items(), key=lambda item: item[1]["name"]))

    # 審査状況を生成
    poster_assignments = {p["id"]: {"title": p["title"], "judges": []} for p in posters}
    for token, data in sorted_judges.items():
        for poster_id in data["selected_posters"]:
            if poster_id in poster_assignments:
                poster_assignments[poster_id]["judges"].append(data["name"])

    return render_template(
        "admin.html",
        judges=sorted_judges,
        posters=posters,
        poster_assignments=poster_assignments,
    )


@app.route("/admin", methods=["GET", "POST"])
def admin_panel():
    if request.method == "POST":
        action = request.form.get("action")
        
        # 審査員の名前を編集
        if action == "edit_judge_name":
            token = request.form.get("token")
            new_name = request.form.get("new_name")
            if token in judges:
                judges[token]["name"] = new_name
                save_judges(judges)

        # トークンを再生成
        elif action == "regenerate_token":
            old_token = request.form.get("old_token")
            if old_token in judges:
                new_token = generate_token(16)
                while new_token in judges:  # 一意性を保証
                    new_token = generate_token(16)
                judges[new_token] = judges.pop(old_token)
                save_judges(judges)

    # 名前順でソートされた審査員リストを作成
    sorted_judges = dict(sorted(judges.items(), key=lambda item: item[1]["name"]))

    # テンプレートにデータを渡す
    return render_template("admin.html", judges=sorted_judges, posters=posters)

@app.route("/admin/regenerate_token", methods=["POST"])
def regenerate_token():
    old_token = request.form.get("old_token")
    
    # トークンが存在しない場合の処理
    if old_token not in judges:
        print(f"Token {old_token} not found in judges.")
        return "Invalid token", 400

    # 新しいトークン生成
    new_token = generate_token(16)
    while new_token in judges:  # 一意性の保証
        new_token = generate_token(16)

    # データの更新
    judges[new_token] = judges.pop(old_token)
    print(f"Token regenerated: {old_token} -> {new_token}")

    # データ保存
    save_judges(judges)
    return redirect("/admin/dashboard")

@app.route("/admin_logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("index"))

@app.route("/generate_token", methods=["POST"])
def generate_judge_token():
    judge_name = request.form["name"]
    token = generate_token()
    judges[token] = {"name": judge_name, "selected_posters": []}
    save_judges(judges) # Save to JSON
    return jsonify({"token": token})

@app.route("/judge/<token>", methods=["GET", "POST"])
def judge_page(token):
    if token not in judges:
        return "Invalid token", 403

    judge_data = judges[token]
    judge_data["selected_posters"] = [int(poster_id) for poster_id in judge_data["selected_posters"]]

    # ページネーション関連
    page = int(request.args.get("page", 1))  # 現在のページ
    per_page = 10  # 1ページあたりのポスター数
    total_pages = ceil(len(posters) / per_page)

    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, len(posters))  # 範囲を安全に制限

    # ページごとのポスターを取得
    available_posters = posters[start_idx:end_idx]

    # 選択済みポスター
    selected_posters = [
        p for p in posters if p["id"] in judge_data["selected_posters"]
    ]

    message = None

    if request.method == "POST":
        action = request.form.get("action")
        try:
            poster_id = int(request.form.get("poster_id", 0))
        except ValueError:
            message = "Invalid poster ID."
            return render_template("judge.html", judge=judge_data, selected_posters=selected_posters_data, posters=available_posters, message=message)

        poster = next((p for p in posters if p["id"] == poster_id), None)

        if action == "select":
            if poster_id in judge_data["selected_posters"]:
                message = "You have already selected this poster."
            elif len(judge_data["selected_posters"]) >= app.config.get("MAX_POSTERS_PER_JUDGE", 5):
                message = "You have reached your selection limit."
            elif poster and poster["current_judges"] < poster["max_judges"]:
                with lock:
                    poster["current_judges"] += 1
                    judge_data["selected_posters"].append(poster_id)
                    save_posters(posters)
                    save_judges(judges)
                message = "Poster selected successfully!"
            else:
                message = "This poster has reached its selection limit."

        elif action == "deselect":
            if poster_id in judge_data["selected_posters"]:
                with lock:
                    judge_data["selected_posters"].remove(poster_id)
                    if poster:
                        poster["current_judges"] -= 1
                        save_posters(posters)
                        save_judges(judges)
                message = "Poster deselected successfully!"
            else:
                message = "You have not selected this poster."

        # 更新された選択済みポスターと利用可能ポスターを再計算
        selected_posters_data = [
            p for p in posters if p["id"] in judge_data["selected_posters"]
        ]
        available_posters = [
            p for p in posters if p["current_judges"] < p["max_judges"] and p["id"] not in judge_data["selected_posters"]
        ]
    
    # デバッグ用ログ
    print(f"Page: {page}, Start Index: {start_idx}, End Index: {end_idx}")
    print(f"Available Posters: {[p['id'] for p in available_posters]}")

    return render_template(
        "judge.html",
        judge=judge_data,
        selected_posters=selected_posters,
        available_posters=available_posters,  # 修正点: ページごとのポスターリストを渡す
        current_page=page,
        total_pages=total_pages,
        message=message
    )


@app.route("/judge_logout")
def judge_logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)

