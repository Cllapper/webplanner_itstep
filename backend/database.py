# mongo_demo.py
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
import uuid


from datetime import datetime

def _dt_now_iso() -> str:
    return datetime.utcnow().isoformat()


from services import hash_utils
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "demo_db"
COLL_NAME = "tasks"


class DBManager:
    def __init__(self, client):
        self.client = client
        self.users = client['users']
        self.tasks = client['tasks']

    def create_user(self, username, password):
        if self.get_user(username) is not None:
            return None

        password_hash = hash_utils.hash_password(password)
        res = self.users.insert_one({
            "username": username,
            "password_hash": password_hash,
            "tasks": [],
            "token": ""
        })
        return str(res.inserted_id)

    def get_user(self, username):
        return self.users.find_one({"username": username})
    def get_user_by_token(self, token: str):
        return self.users.find_one({"token": token})
    def delete_user(self, username):
        return self.users.delete_one({"username": username})

    def update_user_token(self, username):
        token = str(uuid.uuid4())
        result = self.users.update_one({"username": username}, {"$set": {"token": token}})

        if result.matched_count != 1:
            return {"ok": False, "error": "User not found"}

        return {"ok": True, "token": token}

    def create_task(self, user_id: str, task_data: dict) -> str:
        """
        Создать задачу для конкретного пользователя.
        task_data — словарь из модели TaskCreate (title, priority, due_date, description, tags, comment, subtasks, attachment)
        Возвращает id созданной задачи (строкой).
        """
        doc = dict(task_data)

        # Привязка к пользователю
        doc["user_id"] = user_id

        # Поля по умолчанию
        doc.setdefault("done", False)
        doc.setdefault("created_at", _dt_now_iso())
        doc.setdefault("updated_at", _dt_now_iso())

        res = self.tasks.insert_one(doc)
        return str(res.inserted_id)

