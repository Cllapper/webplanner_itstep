# main.py
from fastapi import FastAPI
from database import DBManager

from config import db_client
import models

from services import hash_utils
import uuid
from fastapi import Query


app = FastAPI(title="Mini FastAPI")

db = DBManager(db_client)

@app.get("/")
def root():
    return {"message": "Hello from FastAPI"}

@app.get("/health")
def ping():
    return {"status": "ok"}


@app.post("/registration")
def registration(payload: models.user_auth):
    inserted_id = db.create_user(payload.username, payload.password)
    if inserted_id is None:
        return {"error": "User already exists"}
    return {"inserted_id": inserted_id}


@app.post("/login")
def login(payload: models.user_auth):
    user = db.get_user(payload.username)
    if user is None:
        return {"ok": False, "error": "User not found"}

    is_authed = hash_utils.check_password(
        password=payload.password,
        stored_hash=user["password_hash"]
    )
    if not is_authed:
        return {"ok": False, "error": "Incorrect password"}

    return db.update_user_token(user["username"])


@app.post("/tasks")
def create_task(payload: models.TaskCreate, user_token: str):
    user = db.get_user_by_token(user_token)
    if user == None: return {"result": "User token is incorrect"}

    task_id = db.create_task(user_id=str(user["_id"]), task_data=payload.model_dump())
    return {"task_id": task_id}


@app.patch("/tasks/{task_id}")
def edit_task(task_id: str, payload: models.TaskUpdate, user_token: str):
    user = db.get_user_by_token(user_token)
    if user is None:
        return {"result": "User token is incorrect"}

    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        return {"result": "No fields to update"}

    result = db.edit_task(user_id=str(user["_id"]), task_id=task_id, updates=updates)

    if not result.get("ok"):
        return {"result": result.get("error", "Edit failed")}

    return {"result": True, "modified": result.get("modified", 0)}


@app.delete("/tasks/{task_id}")
def delete_task(task_id: str, user_token: str):
    user = db.get_user_by_token(user_token)
    if user is None:
        return {"result": "User token is incorrect"}

    result = db.delete_task(user_id=str(user["_id"]), task_id=task_id)

    if not result.get("ok"):
        return {"result": result.get("error", "Delete failed")}

    return {"result": True, "deleted": result.get("deleted", 0)}


@app.get("/api/tasks")
def api_tasks(
    view: str = Query("day", pattern="^(day|week|month|year)$"),
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user_token: str = Query(...)
):
    user = db.get_user_by_token(user_token)
    if user is None:
        return {"result": "User token is incorrect"}

    tasks = db.get_tasks_view(user_id=str(user["_id"]), view=view, date_str=date)
    return {"result": True, "view": view, "date": date, "tasks": tasks}



@app.post("/tasks/{task_id}/subtasks")
def add_subtask(task_id: str, payload: models.SubTaskCreate, user_token: str = Query(...)):
    user = db.get_user_by_token(user_token)
    if user is None:
        return {"result": "User token is incorrect"}

    r = db.add_subtask(user_id=str(user["_id"]), task_id=task_id, title=payload.title)
    if not r.get("ok"):
        return {"result": r.get("error")}
    return {"result": True, "subtask_id": r["subtask_id"]}


@app.patch("/tasks/{task_id}/subtasks/{subtask_id}")
def edit_subtask(task_id: str, subtask_id: str, payload: models.SubTaskUpdate, user_token: str = Query(...)):
    user = db.get_user_by_token(user_token)
    if user is None:
        return {"result": "User token is incorrect"}

    updates = payload.model_dump(exclude_unset=True)
    r = db.edit_subtask(user_id=str(user["_id"]), task_id=task_id, subtask_id=subtask_id, updates=updates)
    if not r.get("ok"):
        return {"result": r.get("error")}
    return {"result": True}


@app.delete("/tasks/{task_id}/subtasks/{subtask_id}")
def delete_subtask(task_id: str, subtask_id: str, user_token: str = Query(...)):
    user = db.get_user_by_token(user_token)
    if user is None:
        return {"result": "User token is incorrect"}

    r = db.delete_subtask(user_id=str(user["_id"]), task_id=task_id, subtask_id=subtask_id)
    if not r.get("ok"):
        return {"result": r.get("error")}
    return {"result": True}
