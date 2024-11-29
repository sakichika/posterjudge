from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from io import BytesIO
import pandas as pd
import threading, os, json, random, string
from redis import Redis
from math import ceil
from flask_session import Session

import logging

app = Flask(__name__)

# Redis URLを環境変数から取得
REDIS_URL = os.getenv("REDIS_URL")

# Redisクライアントを初期化
redis_client = Redis.from_url(REDIS_URL)

# 動作確認: 接続テスト
try:
    redis_client.ping()
    print("Connected to Redis successfully!")
except redis.exceptions.ConnectionError as e:
    print(f"Failed to connect to Redis: {e}")

# Flask-Sessionの設定
app.config["SESSION_TYPE"] = "redis"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"] = True
app.config["SESSION_KEY_PREFIX"] = "session:"
app.config["SESSION_COOKIE_NAME"] = "flask_session"
app.config["SESSION_REDIS"] = Redis.from_url(os.getenv("REDIS_URL"))

# Flask-Sessionを初期化
Session(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app.config["SESSION_TYPE"] = "redis"
logger.debug(f"Session Type: {app.config['SESSION_TYPE']}")
logger.debug(f"Session Redis: {app.config['SESSION_REDIS']}")

lock = threading.Lock()

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

def update_current_judges():
    for poster in posters:
        poster["current_judges"] = 0

    for judge in judges.values():
        for poster_id in judge["selected_posters"]:
            poster = next((p for p in posters if p["id"] == poster_id), None)
            if poster:
                poster["current_judges"] += 1

    save_posters(posters)

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

def save_judges(judges_data):
    try:
        with open(JUDGES_FILE, "w") as file:
            json.dump(judges_data, file, indent=4)
            print(f"Judges successfully saved to {JUDGES_FILE}")
    except Exception as e:
        print(f"Error saving judges: {e}")

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
            return redirect(url_for("admin_dashboard"))
        else:
            print("Login failed: Invalid credentials")
            return render_template("admin_login.html", error="Invalid credentials.")
    
    print("Rendering login page")
    return render_template("admin_login.html")

@app.route("/generate_login_links")
def generate_login_links():
    base_url = request.host_url
    login_links = {judge["name"]: f"{base_url}judge/{token}" for token, judge in judges.items()}

    return render_template("login_links.html", login_links=login_links)

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
        
        elif action == "delete_judge":
            token = request.form["token"]
            if token in judges:
                # 削除する審査員が選択したポスターを更新
                for poster_id in judges[token]["selected_posters"]:
                    poster = next((p for p in posters if p["id"] == poster_id), None)
                    if poster:
                        poster["current_judges"] -= 1  # 選択中のポスター数を減少
                # 審査員を削除
                del judges[token]
                save_judges(judges)
                save_posters(posters)

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

    # ページネーション関連
    page = int(request.args.get("page", 1))

    try:
        page = int(page)  # ページ番号を整数に変換
    except ValueError:
        page = 1  # ページ番号が無効な場合は1に戻す
    
    per_page = 10
    total_pages = ceil(len(posters) / per_page)

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    available_posters = posters[start_idx:end_idx]

    return render_template(
        "admin.html",
        judges=sorted_judges,
        posters=available_posters,
        current_page=page,
        total_pages=total_pages,
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

@app.route("/upload/judges", methods=["POST"])
def upload_judges():

    file = request.files.get("file")
    if not file:
        return "No file uploaded", 400

    try:
        # 読み込んだ Excel ファイルを DataFrame に変換
        df = pd.read_excel(file)
        for _, row in df.iterrows():
            name = row.get("Name")
            email = row.get("Email", "")
            if name:  # 名前が必須
                token = generate_token()
                judges[token] = {"name": name, "email": email, "selected_posters": []}
        save_judges(judges)
        return redirect(url_for("admin_dashboard"))
    except Exception as e:
        return f"Error processing file: {e}", 400

@app.route("/upload/posters", methods=["POST"])
def upload_posters():

    file = request.files.get("file")
    if not file:
        return "No file uploaded", 400

    try:
        # 読み込んだ Excel ファイルを DataFrame に変換
        df = pd.read_excel(file)
        for _, row in df.iterrows():
            number = row.get("Number")
            title = row.get("Title")
            presenter = row.get("Presenter")
            coauthors = [x.strip() for x in row.get("Coauthors", "").split(",")]
            affiliations = [x.strip() for x in row.get("Affiliations", "").split(",")]
            abstract = row.get("Abstract", "")
            max_judges = int(row.get("Max Judges", 0))

            if number and title and presenter:  # 必須項目をチェック
                new_id = max(p["id"] for p in posters) + 1 if posters else 1
                posters.append({
                    "id": new_id,
                    "number": number,
                    "title": title,
                    "presenter": presenter,
                    "coauthors": coauthors,
                    "affiliations": affiliations,
                    "abstract": abstract,
                    "max_judges": max_judges,
                    "current_judges": 0,
                })
        save_posters(posters)
        return redirect(url_for("admin_dashboard"))
    except Exception as e:
        return f"Error processing file: {e}", 400

@app.route("/export/judges", methods=["GET"])
def export_judges():
    # Prepare judges data
    judges_df = pd.DataFrame([
        {"Name": data["name"], 
         "Email": data.get("email", ""),
         "Selected Posters": data["selected_posters"],
        }
        for token, data in judges.items()
    ])

    # Export to Excel
    judges_file = BytesIO()
    with pd.ExcelWriter(judges_file, engine='openpyxl') as writer:
        judges_df.to_excel(writer, index=False, sheet_name="Judges")
    judges_file.seek(0)

    # Send file as attachment
    return send_file(
        judges_file,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="judges_list.xlsx"
    )

@app.route("/export/posters", methods=["GET"])
def export_posters():
    # Prepare posters data
    posters_df = pd.DataFrame([
        {
            "Number": poster["number"],
            "Title": poster["title"],
            "Presenter": poster["presenter"],
            "Coauthors": ", ".join(poster["coauthors"]),
            "Affiliations": ", ".join(poster["affiliations"]),
            "Abstract": poster["abstract"],
            "Max Judges": poster["max_judges"],
        }
        for poster in posters
    ])

    # Export to Excel
    posters_file = BytesIO()
    with pd.ExcelWriter(posters_file, engine='openpyxl') as writer:
        posters_df.to_excel(writer, index=False, sheet_name="Posters")
    posters_file.seek(0)

    # Send file as attachment
    return send_file(
        posters_file,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="posters_list.xlsx"
    )

@app.route("/export/ratings", methods=["GET"])
def export_ratings():
    # 各ポスターのデータを収集
    ratings_data = []
    all_judges = {judges[token]["name"]: token for token in judges}  # すべての審査員名を取得

    for poster in posters:
        # ポスターごとの基本情報
        poster_data = {
            "Poster Number": poster["number"],
            "Title": poster["title"],
            "Presenter": poster["presenter"],
        }

        # 審査員ごとのスコアを追加
        for judge_name, token in all_judges.items():
            score = judges[token]["scores"].get(str(poster["id"]), "")  # スコアを取得
            poster_data[judge_name] = score

        ratings_data.append(poster_data)

    # DataFrame に変換
    df = pd.DataFrame(ratings_data)

    # エクセル出力
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Ratings")

    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="rating.xlsx"
    )

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
    # トークンのバリデーション
    if token not in judges:
        return render_template("error.html", message="Invalid token.")

    judge_data = judges[token]
    judge_data["selected_posters"] = [int(poster_id) for poster_id in judge_data["selected_posters"]]

    # ページネーション関連
    page = int(request.args.get("page", 1))  # 現在のページ
    per_page = 10  # 1ページあたりのポスター数
    total_pages = ceil(len(posters) / per_page)

    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, len(posters))  # 範囲を安全に制限

    # ページごとのポスターを取得
    available_posters = [
        p for p in posters[start_idx:end_idx] if p["id"] not in judge_data["selected_posters"]
    ]

    # 選択済みポスター
    selected_posters = [
        p for p in posters if p["id"] in judge_data["selected_posters"]
    ]

    if request.method == "POST":
        action = request.form.get("action")
        try:
            poster_id = int(request.form.get("poster_id", 0))
        except ValueError:
            return render_template(
                "judge.html",
                judge=judge_data,
                selected_posters=selected_posters,
                available_posters=available_posters,
                current_page=page,
                total_pages=total_pages,
            )

        poster = next((p for p in posters if p["id"] == poster_id), None)

        if action == "select":
            if str(poster_id) in judge_data["selected_posters"]:
                return jsonify({"message": "You have already selected this poster."}), 400
            elif len(judge_data["selected_posters"]) >= app.config.get("MAX_POSTERS_PER_JUDGE", 5):
                return jsonify({"message": "You have reached your selection limit."}), 400
            elif poster and poster["current_judges"] >= poster["max_judges"]:
                return jsonify({"message": "This poster has reached its selection limit."}), 400
            elif poster and poster["current_judges"] < poster["max_judges"]:
                with lock:
                    poster["current_judges"] += 1
                    judge_data["selected_posters"].append(str(poster_id))
                save_posters(posters)
                save_judges(judges)
                update_current_judges()
                return jsonify({"message": f"Poster selected successfully!"}), 200

        elif action == "deselect":
            if poster_id in judge_data["selected_posters"]:
                judge_data["selected_posters"].remove(poster_id)

                score_key = str(poster_id)
                if score_key in judge_data["scores"]:
                    del judge_data["scores"][score_key]

                poster = next((p for p in posters if p["id"] == str(poster_id)), None)
                if poster:
                    poster["current_judges"] -= 1

                save_posters(posters)
                save_judges(judges)
                update_current_judges()
                return jsonify({"message": f"Poster deselected successfully!"}), 200
            else:
                return jsonify({"message": "You have not selected this poster."}), 400
        elif action == "rate":
            try:
                score = int(request.form.get("score", 0))
                if 1 <= score <= 10:
                    judge_data["scores"][str(poster_id)] = score
                    save_judges(judges)
                    return jsonify({"message": f"Rating for Poster {poster_id} submitted successfully!"}), 200
                else:
                    return jsonify({"message": "Invalid score. Please enter a value between 1 and 10."}), 400
            except ValueError:
                return jsonify({"message": "Invalid input. Please enter a valid score."}), 400

        selected_posters = [
            p for p in posters if p["id"] in judge_data["selected_posters"]
        ]
        available_posters = [
            p for p in posters[start_idx:end_idx] if p["id"] not in judge_data["selected_posters"]
        ]

    return render_template(
        "judge.html",
        judge=judge_data,
        selected_posters=selected_posters,
        available_posters=available_posters,
        current_page=page,
        total_pages=total_pages,
    )


@app.route("/judge_logout")
def judge_logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)