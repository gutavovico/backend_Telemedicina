
import sys
import os
sys.path.append(os.getcwd())
from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
result = db.execute(text('SELECT column_name FROM information_schema.columns WHERE table_name = ''usuarios'';')).fetchall()
for row in result:
    print(row[0])

