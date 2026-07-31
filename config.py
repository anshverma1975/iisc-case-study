import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    else:
        database_url = f"sqlite:///{os.path.join(BASE_DIR, 'edutracker.db')}"
    
    SQLALCHEMY_DATABASE_URI = database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

    SCHOOLS = ["A", "B", "C"]