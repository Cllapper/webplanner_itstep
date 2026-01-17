import os
from dotenv import load_dotenv
load_dotenv()


from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = 'webplanner'
from pymongo import MongoClient

db = MongoClient(MONGO_URI)
db.admin.command("ping")
print("MongoDB OK")
db_client = db[DB_NAME]

