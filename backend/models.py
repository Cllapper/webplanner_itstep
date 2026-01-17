from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid

class user_auth(BaseModel):
    username: str
    password: str

class SubTask(BaseModel):
    subtask_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    done: bool = False

class SubTaskCreate(BaseModel):
    title: str

class SubTaskUpdate(BaseModel):
    title: Optional[str] = None
    done: Optional[bool] = None

class Attachment(BaseModel):
    file_id: str
    filename: str
    url: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    priority: int = Field(3, ge=1, le=5)
    due_date: Optional[datetime] = None # дата закінчення (ISO-формат краще), наприклад "2026-01-20T18:00:00"
    description: Optional[str] = Field(None, max_length=5000)
    tags: List[str] = Field(default_factory=list)
    comment: Optional[str] = Field(None, max_length=2000) # коментар до задачі
    subtasks: List[SubTask] = Field(default_factory=list) # список підзадач (якщо порожній — задача “кінцева”)
    attachment: Optional[Attachment] = None # прикріплений файл (метаінфа)

class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    priority: Optional[int] = Field(None, ge=1, le=5)
    due_date: Optional[datetime] = None
    description: Optional[str] = Field(None, max_length=5000)
    tags: Optional[List[str]] = None
    comment: Optional[str] = Field(None, max_length=2000)
    subtasks: Optional[List[SubTask]] = None
    attachment: Optional[Attachment] = None
    done: Optional[bool] = None
