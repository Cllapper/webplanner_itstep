import json
import sys
import urllib.parse
import urllib.request
import urllib.error
from getpass import getpass
from datetime import datetime

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def request_json(method: str, url: str, payload: dict | None = None, timeout: int = 10) -> tuple[int, dict]:
    """
    Делает HTTP запрос (POST/PATCH/DELETE/GET) с JSON телом (если нужно).
    Возвращает (status_code, dict). Если ответ не JSON -> {"raw": "..."}.
    """
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, {"raw": body}

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body}

    except Exception as e:
        return 0, {"error": str(e)}


def input_nonempty(prompt: str) -> str:
    while True:
        s = input(prompt).strip()
        if s:
            return s
        print("Пусто. Попробуй ещё раз.")


def input_optional(prompt: str) -> str | None:
    s = input(prompt).strip()
    return s if s else None


def input_int(prompt: str, default: int, min_v: int, max_v: int) -> int:
    s = input(prompt).strip()
    if not s:
        return default
    try:
        v = int(s)
        if v < min_v or v > max_v:
            raise ValueError
        return v
    except ValueError:
        print(f"Нужно число {min_v}..{max_v}. Взял по умолчанию: {default}")
        return default


def parse_due_date(s: str | None) -> str | None:
    """
    Принимает:
      - None / пусто -> None
      - "YYYY-MM-DD" -> "YYYY-MM-DDT00:00:00"
      - "YYYY-MM-DD HH:MM" -> "YYYY-MM-DDTHH:MM:00"
      - "YYYY-MM-DDTHH:MM:SS" -> как есть
    Возвращает ISO строку или None.
    """
    if not s:
        return None

    s = s.strip()

    # Уже ISO?
    try:
        dt = datetime.fromisoformat(s)
        return dt.isoformat()
    except ValueError:
        pass

    # YYYY-MM-DD
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.isoformat()
    except ValueError:
        pass

    # YYYY-MM-DD HH:MM
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        return dt.isoformat()
    except ValueError:
        pass

    print("Не смог распарсить due_date. Примеры: 2026-01-20 или 2026-01-20 18:30")
    return None


def ensure_logged_in(state: dict) -> bool:
    if not state.get("token"):
        print("❌ Сначала войди в аккаунт (пункт 2).")
        return False
    return True


def action_register(state: dict):
    print("\n=== Регистрация ===")
    username = input_nonempty("Username: ")
    password = getpass("Password: ")

    status, data = request_json("POST", f"{state['base_url']}/registration", {"username": username, "password": password})
    print(f"HTTP: {status}")
    print("Ответ:", data)


def action_login(state: dict):
    print("\n=== Вход ===")
    username = input_nonempty("Username: ")
    password = getpass("Password: ")

    status, data = request_json("POST", f"{state['base_url']}/login", {"username": username, "password": password})
    print(f"HTTP: {status}")
    print("Ответ:", data)

    # Совместимо с:
    # {"ok": true, "token": "..."} или {"result": true, "token": "..."}
    ok = False
    if isinstance(data, dict) and "token" in data:
        if data.get("ok") is True or data.get("result") is True:
            ok = True

    if status == 200 and ok:
        state["user"] = username
        state["token"] = data["token"]
        print(f"✅ Успешный вход как: {username}")
        print("Token:", state["token"])
    else:
        state["user"] = None
        state["token"] = None
        print("❌ Вход не выполнен.")
        if isinstance(data, dict) and data.get("error"):
            print("Причина:", data["error"])
        elif isinstance(data, dict) and isinstance(data.get("result"), str):
            print("Причина:", data["result"])


def action_whoami(state: dict):
    user = state.get("user")
    token = state.get("token")
    if user and token:
        print(f"Ты вошёл как: {user}")
        print(f"Token: {token}")
    else:
        print("Ты не вошёл в аккаунт.")


def action_set_url(state: dict):
    url = input_nonempty("Новый BASE_URL (например http://127.0.0.1:8000): ")
    state["base_url"] = url.rstrip("/")
    print("BASE_URL установлен:", state["base_url"])


def action_create_task(state: dict):
    print("\n=== Создать таску ===")
    if not ensure_logged_in(state):
        return

    title = input_nonempty("Title: ")
    priority = input_int("Priority (1..5, default 3): ", default=3, min_v=1, max_v=5)
    due_raw = input_optional("Due date (YYYY-MM-DD или YYYY-MM-DD HH:MM) [enter = пусто]: ")
    due_date = parse_due_date(due_raw)
    description = input_optional("Description [enter = пусто]: ")
    comment = input_optional("Comment [enter = пусто]: ")
    tags_raw = input_optional("Tags через пробел (например #study #work) [enter = пусто]: ")
    tags = tags_raw.split() if tags_raw else []

    subtasks = []
    add_sub = input_optional("Добавить подзадачи? (y/n) [enter = n]: ")
    if add_sub and add_sub.lower().startswith("y"):
        while True:
            st = input_optional("  Subtask title [enter = закончить]: ")
            if not st:
                break
            subtasks.append({"title": st, "done": False})

    payload = {
        "title": title,
        "priority": priority,
        "due_date": due_date,
        "description": description,
        "tags": tags,
        "comment": comment,
        "subtasks": subtasks,
        "attachment": None,
    }

    url = f"{state['base_url']}/tasks?{urllib.parse.urlencode({'user_token': state['token']})}"
    status, data = request_json("POST", url, payload)
    print(f"HTTP: {status}")
    print("Ответ:", data)

    # если сервер вернул task_id — покажем
    if isinstance(data, dict) and data.get("task_id"):
        print("✅ Task ID:", data["task_id"])


def action_edit_task(state: dict):
    print("\n=== Редактировать таску (PATCH) ===")
    if not ensure_logged_in(state):
        return

    task_id = input_nonempty("Task ID: ")

    print("Оставь поле пустым, если не хочешь менять.")
    title = input_optional("New title: ")
    prio_raw = input_optional("New priority (1..5): ")
    due_raw = input_optional("New due_date (YYYY-MM-DD или YYYY-MM-DD HH:MM): ")
    desc = input_optional("New description: ")
    comment = input_optional("New comment: ")
    tags_raw = input_optional("New tags через пробел (например #a #b): ")
    done_raw = input_optional("Done? (true/false): ")

    updates = {}

    if title is not None:
        updates["title"] = title

    if prio_raw is not None:
        try:
            p = int(prio_raw)
            if 1 <= p <= 5:
                updates["priority"] = p
            else:
                print("priority вне 1..5 — пропускаю")
        except ValueError:
            print("priority не число — пропускаю")

    if due_raw is not None:
        updates["due_date"] = parse_due_date(due_raw)

    if desc is not None:
        updates["description"] = desc

    if comment is not None:
        updates["comment"] = comment

    if tags_raw is not None:
        updates["tags"] = tags_raw.split() if tags_raw else []

    if done_raw is not None:
        v = done_raw.strip().lower()
        if v in ("true", "1", "yes", "y"):
            updates["done"] = True
        elif v in ("false", "0", "no", "n"):
            updates["done"] = False
        else:
            print("done не распознан (true/false) — пропускаю")

    if not updates:
        print("❌ Нечего обновлять.")
        return

    url = f"{state['base_url']}/tasks/{task_id}?{urllib.parse.urlencode({'user_token': state['token']})}"
    status, data = request_json("PATCH", url, updates)
    print(f"HTTP: {status}")
    print("Ответ:", data)


def action_delete_task(state: dict):
    print("\n=== Удалить таску (DELETE) ===")
    if not ensure_logged_in(state):
        return

    task_id = input_nonempty("Task ID: ")
    confirm = input_optional("Точно удалить? (y/n) [enter = n]: ")
    if not (confirm and confirm.lower().startswith("y")):
        print("Отмена.")
        return

    url = f"{state['base_url']}/tasks/{task_id}?{urllib.parse.urlencode({'user_token': state['token']})}"
    status, data = request_json("DELETE", url, payload=None)
    print(f"HTTP: {status}")
    print("Ответ:", data)


def menu():
    print("\n===== Mini CLI =====")
    print("1) Регистрация")
    print("2) Вход")
    print("3) Кто я?")
    print("4) Поменять BASE_URL")
    print("5) Создать таску")
    print("6) Редактировать таску (PATCH)")
    print("7) Удалить таску (DELETE)")
    print("0) Выход")


def main():
    state = {
        "base_url": DEFAULT_BASE_URL,
        "user": None,
        "token": None,
    }

    if len(sys.argv) >= 2:
        state["base_url"] = sys.argv[1].rstrip("/")

    print("BASE_URL:", state["base_url"])

    while True:
        menu()
        choice = input("Выбор: ").strip()

        if choice == "1":
            action_register(state)
        elif choice == "2":
            action_login(state)
        elif choice == "3":
            action_whoami(state)
        elif choice == "4":
            action_set_url(state)
        elif choice == "5":
            action_create_task(state)
        elif choice == "6":
            action_edit_task(state)
        elif choice == "7":
            action_delete_task(state)
        elif choice == "0":
            print("Пока!")
            break
        else:
            print("Не понял. Введи 0-7.")


if __name__ == "__main__":
    main()
