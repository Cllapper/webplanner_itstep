import os
from functools import wraps
from datetime import datetime

import requests
from flask import Flask, render_template, request, redirect, url_for, flash, session

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret-change-me")

BACKEND_BASE = os.getenv("BACKEND_BASE", "http://127.0.0.1:8000")
TIMEOUT = 7


def is_logged_in() -> bool:
    return bool(session.get("user_token"))


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_user():
    return {"is_logged_in": is_logged_in(), "user": session.get("user")}


def backend_url(path: str) -> str:
    return BACKEND_BASE.rstrip("/") + path


def extract_token(data: dict) -> str | None:
    # db.update_user_token(...) может вернуть разные ключи — подстрахуемся
    for key in ("user_token", "token", "access_token"):
        if key in data and isinstance(data[key], str) and data[key].strip():
            return data[key].strip()
    # иногда токен могут положить внутрь другого объекта
    inner = data.get("data")
    if isinstance(inner, dict):
        for key in ("user_token", "token", "access_token"):
            if key in inner and isinstance(inner[key], str) and inner[key].strip():
                return inner[key].strip()
    return None


def normalize_datetime_local(dt_local: str) -> str | None:
    """
    input type="datetime-local" даёт строку вида: '2026-01-20T18:00'
    Pydantic datetime обычно нормально парсит ISO. Добавим секунды.
    """
    if not dt_local:
        return None
    try:
        # превращаем в 'YYYY-MM-DDTHH:MM:SS'
        dt = datetime.fromisoformat(dt_local)
        return dt.isoformat(timespec="seconds")
    except ValueError:
        # если пользователь руками ввёл криво
        return dt_local


@app.get("/")
def home():
    return redirect(url_for("dashboard") if is_logged_in() else url_for("login"))


# ---------- AUTH ----------
@app.get("/register")
def register():
    if is_logged_in():
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.post("/register")
def register_submit():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        flash("Введите логин и пароль", "error")
        return redirect(url_for("register"))

    try:
        r = requests.post(
            backend_url("/registration"),
            json={"username": username, "password": password},
            timeout=TIMEOUT,
        )

        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}

        if "error" in data:
            flash(f"Регистрация: {data['error']}", "error")
            return redirect(url_for("register"))

        flash("Аккаунт создан ✅ Теперь войди.", "ok")
        return redirect(url_for("login"))

    except requests.RequestException as e:
        flash(f"Ошибка подключения к бэкенду: {e}", "error")
        return redirect(url_for("register"))


@app.get("/login")
def login():
    if is_logged_in():
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.post("/login")
def login_submit():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        flash("Введите логин и пароль", "error")
        return redirect(url_for("login"))

    try:
        r = requests.post(
            backend_url("/login"),
            json={"username": username, "password": password},
            timeout=TIMEOUT,
        )

        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}

        # твой бэк при ошибках возвращает {"ok": False, "error": "..."} :contentReference[oaicite:2]{index=2}
        if isinstance(data, dict) and data.get("ok") is False:
            flash(f"Логин: {data.get('error', 'Ошибка')}", "error")
            return redirect(url_for("login"))

        if not isinstance(data, dict):
            flash("Логин: неожиданный формат ответа", "error")
            return redirect(url_for("login"))

        token = extract_token(data)
        if not token:
            flash("Логин: бэкенд не вернул user_token/token", "error")
            return redirect(url_for("login"))

        session["user_token"] = token
        session["user"] = {"username": username}
        flash("Вход выполнен ✅", "ok")
        return redirect(url_for("dashboard"))

    except requests.RequestException as e:
        flash(f"Ошибка подключения к бэкенду: {e}", "error")
        return redirect(url_for("login"))


@app.get("/logout")
def logout():
    session.pop("user_token", None)
    session.pop("user", None)
    flash("Вы вышли из аккаунта", "ok")
    return redirect(url_for("login"))


# ---------- DASHBOARD ----------
@app.get("/dashboard")
@login_required
def dashboard():
    created = session.get("created_tasks", [])
    return render_template("dashboard.html", created=created)


# ---------- TASKS ----------
@app.get("/tasks/new")
@login_required
def task_new_form():
    return render_template("task_create.html")


@app.post("/tasks/new")
@login_required
def task_new_submit():
    title = request.form.get("title", "").strip()
    if not title:
        flash("Название задачи обязательно", "error")
        return redirect(url_for("task_new_form"))

    priority = int(request.form.get("priority", "3"))
    due_date = normalize_datetime_local(request.form.get("due_date", "").strip())

    description = request.form.get("description", "").strip() or None
    comment = request.form.get("comment", "").strip() or None

    tags_raw = request.form.get("tags", "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    subtasks_raw = request.form.get("subtasks", "").strip()
    subtasks = [{"title": line.strip(), "done": False}
                for line in subtasks_raw.splitlines() if line.strip()] if subtasks_raw else []

    payload = {
        "title": title,
        "priority": priority,
        "due_date": due_date,        # ISO datetime или None :contentReference[oaicite:3]{index=3}
        "description": description,
        "tags": tags,
        "comment": comment,
        "subtasks": subtasks,
        "attachment": None,
    }

    try:
        r = requests.post(
            backend_url("/tasks"),
            params={"user_token": session["user_token"]},  # у тебя так ожидается :contentReference[oaicite:4]{index=4}
            json=payload,
            timeout=TIMEOUT,
        )

        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}

        # твой бэк может вернуть {"result": "..."} при неверном токене :contentReference[oaicite:5]{index=5}
        if isinstance(data, dict) and data.get("result") and data.get("result") is not True:
            # если там строка с ошибкой
            if isinstance(data["result"], str):
                flash(f"Создание: {data['result']}", "error")
                return redirect(url_for("task_new_form"))

        task_id = data.get("task_id") if isinstance(data, dict) else None
        if not task_id:
            flash(f"Создание: неожиданный ответ: {data}", "error")
            return redirect(url_for("task_new_form"))

        # локально запомним созданные task_id (так как GET списка нет)
        created = session.get("created_tasks", [])
        created.insert(0, {"task_id": task_id, "title": title})
        session["created_tasks"] = created[:50]

        flash(f"Задача создана ✅ id={task_id}", "ok")
        return redirect(url_for("dashboard"))

    except requests.RequestException as e:
        flash(f"Ошибка запроса к бэкенду: {e}", "error")
        return redirect(url_for("task_new_form"))


@app.get("/tasks/edit")
@login_required
def task_edit_form():
    # редактирование по ID (так как GET /tasks/{id} нет)
    task_id = request.args.get("task_id", "").strip()
    return render_template("task_edit.html", task_id=task_id)


@app.post("/tasks/edit")
@login_required
def task_edit_submit():
    task_id = request.form.get("task_id", "").strip()
    if not task_id:
        flash("Укажи task_id", "error")
        return redirect(url_for("task_edit_form"))

    # все поля опциональные: PATCH ожидает только обновления :contentReference[oaicite:6]{index=6}
    updates = {}

    title = request.form.get("title", "").strip()
    if title:
        updates["title"] = title

    pr_raw = request.form.get("priority", "").strip()
    if pr_raw:
        updates["priority"] = int(pr_raw)

    due_date = normalize_datetime_local(request.form.get("due_date", "").strip())
    if due_date:
        updates["due_date"] = due_date

    description = request.form.get("description", "").strip()
    if description:
        updates["description"] = description

    comment = request.form.get("comment", "").strip()
    if comment:
        updates["comment"] = comment

    tags_raw = request.form.get("tags", "").strip()
    if tags_raw:
        updates["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]

    subtasks_raw = request.form.get("subtasks", "").strip()
    if subtasks_raw:
        updates["subtasks"] = [{"title": line.strip(), "done": False}
                               for line in subtasks_raw.splitlines() if line.strip()]

    done_raw = request.form.get("done", "").strip()
    if done_raw in ("true", "false"):
        updates["done"] = (done_raw == "true")

    if not updates:
        flash("Нет полей для обновления", "error")
        return redirect(url_for("task_edit_form", task_id=task_id))

    try:
        r = requests.patch(
            backend_url(f"/tasks/{task_id}"),
            params={"user_token": session["user_token"]},
            json=updates,
            timeout=TIMEOUT,
        )

        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}

        if isinstance(data, dict) and data.get("result") is True:
            flash(f"Обновлено ✅ modified={data.get('modified', 0)}", "ok")
            return redirect(url_for("dashboard"))

        flash(f"Редактирование: {data}", "error")
        return redirect(url_for("task_edit_form", task_id=task_id))

    except requests.RequestException as e:
        flash(f"Ошибка запроса к бэкенду: {e}", "error")
        return redirect(url_for("task_edit_form", task_id=task_id))


@app.post("/tasks/delete")
@login_required
def task_delete():
    task_id = request.form.get("task_id", "").strip()
    if not task_id:
        flash("Укажи task_id", "error")
        return redirect(url_for("dashboard"))

    try:
        r = requests.delete(
            backend_url(f"/tasks/{task_id}"),
            params={"user_token": session["user_token"]},
            timeout=TIMEOUT,
        )

        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}

        if isinstance(data, dict) and data.get("result") is True:
            flash(f"Удалено ✅ deleted={data.get('deleted', 0)}", "ok")
            return redirect(url_for("dashboard"))

        flash(f"Удаление: {data}", "error")
        return redirect(url_for("dashboard"))

    except requests.RequestException as e:
        flash(f"Ошибка запроса к бэкенду: {e}", "error")
        return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
