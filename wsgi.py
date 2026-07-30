import sys
import os

BASE_DIR = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE_DIR, "backend"))
sys.path.insert(0, os.path.join(BASE_DIR, "backend", "notifications"))
sys.path.insert(0, BASE_DIR)

from app import app

if __name__ == "__main__":
    app.run()