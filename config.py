import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = "local_client_secret_key"
    CLOUD_SERVER_URL = "http://127.0.0.1:5001"
    LOCAL_DB_PATH = "local.db"
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo")
