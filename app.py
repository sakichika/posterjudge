from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import asyncio

import os
import json

app = Flask(__name__)
app.secret_key = "your_secret_key"

# Admin credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"

# File to store judges
JUDGES_FILE = "judges.json"
POSTERS_FILE = "posters.json"

# Default settings
app.config["MAX_POSTERS_PER_JUDGE"] = 3

# Load posters from JSON
def load_posters():
    if os.path.exists(POSTERS_FILE):
        with open(POSTERS_FILE, "r") as f:
            return json.load(f)
    return [{"id": i, "title": f"Poster {i}", "max_judges": 3, "current_judges": 0} for i in range(1, 11)]

# Save posters to JSON
def save_posters(posters):
    with open(POSTERS_FILE, "w") as f:
        json.dump(posters, f)

# Load judges from JSON
def load_judges():
    if os.path.exists(JUDGES_FILE):
        with open(JUDGES_FILE, "r") as f:
            return json.load(f)
        return {}

# Save judges to JSON
def save_judges(judges):
    with open(JUDGES_FILE, "w") as f:
        json.dump(judges, f)

# Initialize judges dictionary
judges = load_judges()
posters = load_posters()

# Generate random token
def generate_token():
    import random
    import string
    return ''.join(random.choices(string.ascii_letters + string.digits, k=10))

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
        username = request.form["username"]
        password = request.form["password"]
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            return render_template("admin_login.html", error="Invalid credentials.")
    return render_template("admin_login.html")

@app.route("/admin/dashboard", methods=["GET", "POST"])
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    # POSTリクエストで審査員またはポスターを操作
    if request.method == "POST":
        action = request.form["action"]

        if action == "add_judge":
            name = request.form["name"]
            token = generate_token()
            judges[token] = {"name": name, "selected_posters": []}
            save_judges(judges)
        elif action == "delete_judge":
            token = request.form["token"]
            if token in judges:        
                # 審査員が選択したポスターのカウントを減少
                for poster_id in judges[token]["selected_posters"]:
                    poster = next((p for p in posters if p["id"] == poster_id), None)
                    if poster:
                        poster["current_judges"] -= 1
                del judges[token]
                save_judges(judges)
                save_posters(posters)
        elif action == "remove_poster_from_judge":
            token = request.form["token"]
            poster_id = int(request.form["poster_id"])
            if token in judges and poster_id in judges[token]["selected_posters"]:
                judges[token]["selected_posters"].remove(poster_id)
                poster = next((p for p in posters if p["id"] == poster_id), None)
                if poster:
                    poster["current_judges"] -= 1
                save_judges(judges)
                save_posters(posters)
        
        elif action == "add_poster":
            title = request.form["title"]
            max_judes = int(request.form["max_judges"])    
            new_id = max(p["id"] for p in posters) + 1 if posters else 1
            posters.append({"id": new_id, "title": title, "max_judges": max_judges, "current_judges": 0})
            save_posters(posters)

        elif action == "delete_poster":
            poster_id = int(request.form["poster_id"])
            posters[:] = [p for p in posters if p["id"] != poster_id]
            # 削除したポスターを選択していた審査員のリストを更新
            for token in judges:
                if poster_id in judges[token]["selected_posters"]:
                    judges[token]["selected_posters"].remove(poster_id)
            save_poters(posters)
            save_judges(judges)

        elif action == "edit_poster":
            poster_id = int(request.form["poster_id"])
            new_title = request.form["title"]
            new_max_judges = int(request.form["max_judges"])
            poster = next((p for p in posters if p["id"] == poster_id), None)
            if poster:
                poser["title"] = new_title
                poster["max_judges"] = new_max_judges
                save_posters(posters)

    # 審査状況の作成
    poster_assignments = {p["id"]: {"title": p["title"], "judges": []} for p in posters}
    for token, data in judges.items():
        for poster_id in data["selected_posters"]:
            if poster_id in poster_assignments:
                poster_assignments[poster_id]["judges"].append(judges[token]["name"])

    return render_template(
            "admin.html",
            posters=posters,
            judges=judges,
            poster_assignments=poster_assignments,
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
async def judge_page(token):
    if token not in judges:
        return "Invalid token", 403
    
    judge_data = judges[token]
    message = None
    
    if request.method == "POST":
        action = request.form.get("action")
        poster_id = int(request.form.get("poster_id",0))

        if action == "select":
            # Check if already selected
            if poster_id in judge_data["selected_posters"]:
                message = "You have already selected this poster."
            # Check if selection limit is reached
            elif len(judge_data["selected_posters"]) >= app.config["MAX_POSTERS_PER_JUDGE"]:
                message = "You have reached your selection limit."
            else:
                # Fetch poster and check if it's available
                poster = next((p for p in posters if p["id"] == poster_id), None)
                if poster and poster["current_judges"] < poster["max_judges"]:
                    # Update poster and judge data
                    async with asyncio.Lock():  # Ensures synchronous updates
                        poster["current_judges"] += 1
                        judge_data["selected_posters"].append(poster_id)
                        save_judges(judges)
                        save_posters(posters)
                    message = "Poster selected successfully!"
                else:
                    message = "This poster has reached its selection limit."

        elif action == "deselect":
            if poster_id in judge_data["selected_posters"]:
                async with asyncio.Lock():
                    judge_data["selected_posters"].remove(poster_id)
                    poster = next((p for p in posters if p["id"] == poster_id), None)
                    if poster:
                        poster["current_judges"] -= 1
                        save_judges(judges)
                        save_posters(posters)
                message = "Poster deselected successfully!"
            else:
                message = "You have not selected this poster."
    

     # Exclude already selected posters from available posters
    available_posters = [
            p for p in posters if p["current_judges"] < p["max_judges"] and p["id"] not in judge_data["selected_posters"]
            ]
    return render_template("judge.html", judge=judge_data, posters=available_posters, message=message)

@app.route("/judge_logout")
def judge_logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)

