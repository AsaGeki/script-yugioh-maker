import os

from dotenv import load_dotenv

load_dotenv()

PORT = int(os.environ.get("PORT", "3000"))
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
# HEADLESS=false abre a janela do Chrome pra debug visual (default: headless, sem janela)
HEADLESS = os.environ.get("HEADLESS", "true").strip().lower() not in ("false", "0", "")
