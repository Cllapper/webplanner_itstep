import os
from functools import wraps
from datetime import date, datetime

import requests
from flask import Flask, render_template, request, redirect, url_for, flash, session

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret-change-me")

BACKEND_BASE = os.getenv("BACKEND_BASE", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 7


def backend_url(path: str) -> str:
    return BACKEND_BASE + path


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


def normalize_datetime_local(dt_local: str) -> str | None:
    """input datetime-local => ISO строка с секундами (Pydantic datetime хорошо ест ISO)"""
    if not dt_local:
        return None
    try:
        dt = datetime.fromisoformat(dt_local)
        return dt.isoformat(timespec="seconds")
    except ValueError:
        return dt_local


def call_backend(method: str, path: str, *, params=None, json=None):
    """Запрос к бэку с user_token в query (как у тебя в FastAPI)."""
    params = dict(params or {})
    if is_logged_in():
        params.setdefault("user_token", session["user_token"])

    return requests.request(
        method=method,
        url=backend_url(path),
        params=params,
        json=json,
        timeout=TIMEOUT,
    )


def pick_done_from_form(prefix: str = "done") -> bool:
    """
    Для чекбокса:
      <input type="hidden" name="done" value="0">
      <input type="checkbox" name="done" value="1">
    Тогда request.form.getlist("done") = ["0"] или ["0","1"].
    """
    vals = request.form.getlist(prefix)
    return "1" in vals


def get_tasks_view(view: str, d: str) -> list[dict]:
    r = call_backend("GET", "/api/tasks", params={"view": view, "date": d})
    data = r.json() if "application/json" in r.headers.get("content-type", "") else {"raw": r.text}

    if isinstance(data, dict) and data.get("result") == "User token is incorrect":
        session.pop("user_token", None)
        flash("Сессия истекла. Войди заново.", "error")
        return []

    if isinstance(data, dict) and data.get("result") is True:
        return data.get("tasks", []) or []

    flash(f"Не удалось получить задачи: {data}", "error")
    return []


def find_task_in_list(tasks: list[dict], task_id: str) -> dict | None:
    for t in tasks:
        if t.get("_id") == task_id:
            return t
    return None


# ---------------- AUTH ----------------

@app.get("/")
def home():
    return redirect(url_for("tasks_list") if is_logged_in() else url_for("login"))


@app.get("/register")
def register():
    if is_logged_in():
        return redirect(url_for("tasks_list"))
    return render_template("register.html")


@app.post("/register")
def register_submit():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    if not username or not password:
        flash("Введите логин и пароль", "error")
        return redirect(url_for("register"))

    try:
        r = requests.post(backend_url("/registration"), json={"username": username, "password": password}, timeout=TIMEOUT)
        data = r.json() if "application/json" in r.headers.get("content-type", "") else {"raw": r.text}
        if isinstance(data, dict) and data.get("error"):
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
        return redirect(url_for("tasks_list"))
    return render_template("login.html")


@app.post("/login")
def login_submit():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    if not username or not password:
        flash("Введите логин и пароль", "error")
        return redirect(url_for("login"))

    try:
        r = requests.post(backend_url("/login"), json={"username": username, "password": password}, timeout=TIMEOUT)
        data = r.json() if "application/json" in r.headers.get("content-type", "") else {"raw": r.text}

        # /login возвращает {"ok": True, "token": "..."} :contentReference[oaicite:3]{index=3}
        if isinstance(data, dict) and data.get("ok") is False:
            flash(f"Логин: {data.get('error', 'Ошибка')}", "error")
            return redirect(url_for("login"))

        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            flash(f"Логин: бэкенд не вернул token. Ответ: {data}", "error")
            return redirect(url_for("login"))

        session["user_token"] = token
        session["user"] = {"username": username}
        flash("Вход выполнен ✅", "ok")
        return redirect(url_for("tasks_list"))

    except requests.RequestException as e:
        flash(f"Ошибка подключения к бэкенду: {e}", "error")
        return redirect(url_for("login"))


@app.get("/logout")
def logout():
    session.pop("user_token", None)
    session.pop("user", None)
    flash("Вы вышли из аккаунта", "ok")
    return redirect(url_for("login"))


# ---------------- LIST: view/day/week/month/year ----------------

@app.get("/tasks")
@login_required
def tasks_list():
    view = request.args.get("view", "day")
    d = request.args.get("date", date.today().isoformat())
    tasks = get_tasks_view(view, d)
    return render_template("tasks.html", tasks=tasks, view=view, d=d, mode="view")


# ---------------- LIST ALL (через склейку year-представлений) ----------------

@app.get("/tasks/all")
@login_required
def tasks_all():
    year_from = int(request.args.get("year_from", date.today().year - 5))
    year_to = int(request.args.get("year_to", date.today().year + 1))

    all_tasks = []
    seen = set()

    for y in range(year_from, year_to + 1):
        tasks = get_tasks_view("year", f"{y}-01-01")
        for t in tasks:
            tid = t.get("_id")
            if tid and tid not in seen:
                seen.add(tid)
                all_tasks.append(t)

    # сортировка: due_date (пустые в конец)
    def sort_key(t):
        dd = t.get("due_date")
        return (dd is None, dd or "")
    all_tasks.sort(key=sort_key)

    return render_template(
        "tasks_all.html",
        tasks=all_tasks,
        year_from=year_from,
        year_to=year_to,
        mode="all"
    )


# ---------------- CREATE TASK ----------------

@app.get("/tasks/new")
@login_required
def task_new_form():
    return render_template("task_form.html")


@app.post("/tasks/new")
@login_required
def task_new_submit():
    title = request.form.get("title", "").strip()
    if not title:
        flash("Название обязательно", "error")
        return redirect(url_for("task_new_form"))

    payload = {
        "title": title,
        "priority": int(request.form.get("priority", "3")),
        "due_date": normalize_datetime_local(request.form.get("due_date", "").strip()),
        "description": (request.form.get("description", "").strip() or None),
        "comment": (request.form.get("comment", "").strip() or None),
        "tags": [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()],
        # на создании можно задать подзадачи списком (как в моделях) :contentReference[oaicite:4]{index=4}
        "subtasks": [
            {"title": line.strip(), "done": False}
            for line in request.form.get("subtasks", "").splitlines()
            if line.strip()
        ],
        "attachment": None,
    }

    try:
        r = call_backend("POST", "/tasks", json=payload)
        data = r.json() if "application/json" in r.headers.get("content-type", "") else {"raw": r.text}
        task_id = data.get("task_id") if isinstance(data, dict) else None
        if not task_id:
            flash(f"Создание: {data}", "error")
            return redirect(url_for("task_new_form"))

        flash("Задача создана ✅", "ok")
        return redirect(url_for("tasks_list"))
    except requests.RequestException as e:
        flash(f"Ошибка запроса к бэкенду: {e}", "error")
        return redirect(url_for("task_new_form"))


# ---------------- EDIT TASK (с подтягиванием из текущего списка) ----------------

@app.get("/tasks/<task_id>/edit")
@login_required
def task_edit_form(task_id: str):
    # чтобы показать подзадачи, тянем задачу из списка (передаем view/date из списка)
    view = request.args.get("view", "day")
    d = request.args.get("date", date.today().isoformat())

    tasks = get_tasks_view(view, d)
    task = find_task_in_list(tasks, task_id)

    # fallback: если не нашли — попробуем год
    if task is None:
        tasks_y = get_tasks_view("year", f"{date.today().year}-01-01")
        task = find_task_in_list(tasks_y, task_id)

    # если всё равно не нашли — покажем пустую болванку (редактирование полей всё равно работает)
    if task is None:
        task = {"_id": task_id, "title": "", "priority": 3, "done": False, "tags": [], "subtasks": []}
        flash("Не смог найти задачу в выбранном диапазоне (возможно due_date пустая или другой период).", "error")

    return render_template("task_edit.html", task=task, view=view, d=d)


@app.post("/tasks/<task_id>/edit")
@login_required
def task_edit_submit(task_id: str):
    updates = {}

    title = request.form.get("title", "").strip()
    if title:
        updates["title"] = title

    pr = request.form.get("priority", "").strip()
    if pr:
        updates["priority"] = int(pr)

    dd = normalize_datetime_local(request.form.get("due_date", "").strip())
    if dd:
        updates["due_date"] = dd

    desc = request.form.get("description", "").strip()
    if desc:
        updates["description"] = desc

    com = request.form.get("comment", "").strip()
    if com:
        updates["comment"] = com

    tags_raw = request.form.get("tags", "").strip()
    if tags_raw:
        updates["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]

    # done чекбокс — отправляем всегда, чтобы можно было и true и false
    updates["done"] = pick_done_from_form("done")

    try:
        r = call_backend("PATCH", f"/tasks/{task_id}", json=updates)
        data = r.json() if "application/json" in r.headers.get("content-type", "") else {"raw": r.text}

        if isinstance(data, dict) and data.get("result") is True:
            flash("Сохранено ✅", "ok")
        else:
            flash(f"Редактирование: {data}", "error")

        # возвращаемся на edit с тем же view/date
        view = request.form.get("view", "day")
        d = request.form.get("date", date.today().isoformat())
        return redirect(url_for("task_edit_form", task_id=task_id, view=view, date=d))

    except requests.RequestException as e:
        flash(f"Ошибка запроса к бэкенду: {e}", "error")
        return redirect(url_for("task_edit_form", task_id=task_id))


@app.post("/tasks/<task_id>/delete")
@login_required
def task_delete(task_id: str):
    try:
        r = call_backend("DELETE", f"/tasks/{task_id}")
        data = r.json() if "application/json" in r.headers.get("content-type", "") else {"raw": r.text}

        if isinstance(data, dict) and data.get("result") is True:
            flash("Удалено ✅", "ok")
        else:
            flash(f"Удаление: {data}", "error")

        return redirect(url_for("tasks_list"))
    except requests.RequestException as e:
        flash(f"Ошибка запроса к бэкенду: {e}", "error")
        return redirect(url_for("tasks_list"))


# ---------------- SUBTASKS (+ / – / чекбоксы) ----------------

@app.post("/tasks/<task_id>/subtasks/add")
@login_required
def subtask_add(task_id: str):
    title = request.form.get("title", "").strip()
    view = request.form.get("view", "day")
    d = request.form.get("date", date.today().isoformat())

    if not title:
        flash("Подзадача: название пустое", "error")
        return redirect(url_for("task_edit_form", task_id=task_id, view=view, date=d))

    try:
        r = call_backend("POST", f"/tasks/{task_id}/subtasks", json={"title": title})
        data = r.json() if "application/json" in r.headers.get("content-type", "") else {"raw": r.text}

        if isinstance(data, dict) and data.get("result") is True:
            flash("Подзадача добавлена ✅", "ok")
        else:
            flash(f"Подзадача add: {data}", "error")

        return redirect(url_for("task_edit_form", task_id=task_id, view=view, date=d))
    except requests.RequestException as e:
        flash(f"Ошибка запроса к бэкенду: {e}", "error")
        return redirect(url_for("task_edit_form", task_id=task_id, view=view, date=d))


@app.post("/tasks/<task_id>/subtasks/<subtask_id>/edit")
@login_required
def subtask_edit(task_id: str, subtask_id: str):
    view = request.form.get("view", "day")
    d = request.form.get("date", date.today().isoformat())

    title = request.form.get("title", "").strip()
    done = pick_done_from_form("sub_done")

    updates = {"done": done}
    if title:
        updates["title"] = title

    try:
        r = call_backend("PATCH", f"/tasks/{task_id}/subtasks/{subtask_id}", json=updates)
        data = r.json() if "application/json" in r.headers.get("content-type", "") else {"raw": r.text}

        if isinstance(data, dict) and data.get("result") is True:
            flash("Подзадача сохранена ✅", "ok")
        else:
            flash(f"Подзадача edit: {data}", "error")

        return redirect(url_for("task_edit_form", task_id=task_id, view=view, date=d))
    except requests.RequestException as e:
        flash(f"Ошибка запроса к бэкенду: {e}", "error")
        return redirect(url_for("task_edit_form", task_id=task_id, view=view, date=d))


@app.post("/tasks/<task_id>/subtasks/<subtask_id>/delete")
@login_required
def subtask_delete(task_id: str, subtask_id: str):
    view = request.form.get("view", "day")
    d = request.form.get("date", date.today().isoformat())

    try:
        r = call_backend("DELETE", f"/tasks/{task_id}/subtasks/{subtask_id}")
        data = r.json() if "application/json" in r.headers.get("content-type", "") else {"raw": r.text}

        if isinstance(data, dict) and data.get("result") is True:
            flash("Подзадача удалена ✅", "ok")
        else:
            flash(f"Подзадача delete: {data}", "error")

        return redirect(url_for("task_edit_form", task_id=task_id, view=view, date=d))
    except requests.RequestException as e:
        flash(f"Ошибка запроса к бэкенду: {e}", "error")
        return redirect(url_for("task_edit_form", task_id=task_id, view=view, date=d))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
