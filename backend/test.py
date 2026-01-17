import json
import sys
import urllib.parse
import urllib.request
import urllib.error
from getpass import getpass
from datetime import datetime

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def post_json(url: str, payload: dict, timeout: int = 8) -> tuple[int, dict]:
    """
    Делает POST JSON и возвращает (status_code, json_dict).
    Если сервер вернул не-JSON, вернёт {"raw": "..."}.
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

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
      - "YYYY-MM-DDTHH:MM:SS" -> как есть (если валидно)
    Возвращает ISO строку или None.
    """
    if not s:
        return None

    s = s.strip()

    # Попробуем уже ISO
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

    print("Не смог распарсить due_date. Оставил пустым. Примеры: 2026-01-20 или 2026-01-20 18:30")
    return None


def action_register(base_url: str):
    print("\n=== Регистрация ===")
    username = input_nonempty("Username: ")
    password = getpass("Password: ")

    status, data = post_json(f"{base_url}/registration", {"username": username, "password": password})
    print(f"HTTP: {status}")
    print("Ответ:", data)


def action_login(base_url: str, state: dict):
    print("\n=== Вход ===")
    username = input_nonempty("Username: ")
    password = getpass("Password: ")

    status, data = post_json(f"{base_url}/login", {"username": username, "password": password})
    print(f"HTTP: {status}")
    print("Ответ:", data)

    if status == 200 and isinstance(data, dict) and data.get("ok") is True and "token" in data:
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


def action_create_task(base_url: str, state: dict):
    print("\n=== Создать таску ===")

    token = state.get("token")
    if not token:
        print("❌ Сначала войди в аккаунт (пункт 2).")
        return

    title = input_nonempty("Title: ")
    priority = input_int("Priority (1..5, default 3): ", default=3, min_v=1, max_v=5)
    due_raw = input_optional("Due date (YYYY-MM-DD или YYYY-MM-DD HH:MM) [enter = пусто]: ")
    due_date = parse_due_date(due_raw)
    description = input_optional("Description [enter = пусто]: ")
    comment = input_optional("Comment [enter = пусто]: ")

    tags_raw = input_optional("Tags через пробел (например #study #work) [enter = пусто]: ")
    tags = tags_raw.split() if tags_raw else []

    # Подзадачи
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

    # Твой эндпоинт ждёт token как query параметр: /tasks?user_token=...
    # (лучше потом переделаешь на Authorization header, но под текущий код делаем так)
    url = f"{base_url}/tasks?{urllib.parse.urlencode({'user_token': token})}"

    status, data = post_json(url, payload)
    print(f"HTTP: {status}")
    print("Ответ:", data)


def menu():
    print("\n===== Mini CLI =====")
    print("1) Регистрация")
    print("2) Вход")
    print("3) Кто я?")
    print("4) Поменять BASE_URL")
    print("5) Создать таску")
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
            action_register(state["base_url"])
        elif choice == "2":
            action_login(state["base_url"], state)
        elif choice == "3":
            action_whoami(state)
        elif choice == "4":
            action_set_url(state)
        elif choice == "5":
            action_create_task(state["base_url"], state)
        elif choice == "0":
            print("Пока!")
            break
        else:
            print("Не понял. Введи 0-5.")


if __name__ == "__main__":
    main()
