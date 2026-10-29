"""Generate BOTWOK_MASTER_KEY and JWT_SECRET; --write updates .env in place if they are still placeholders."""
import base64, os, re, secrets, sys
from pathlib import Path

def gen_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()

def main() -> None:
    mk, js = gen_key(), secrets.token_urlsafe(48)
    if "--write" in sys.argv:
        env = Path(__file__).resolve().parents[1] / ".env"
        text = env.read_text() if env.exists() else ""
        text = re.sub(r"^BOTWOK_MASTER_KEY=change-me.*$", f"BOTWOK_MASTER_KEY={mk}", text, flags=re.M)
        text = re.sub(r"^JWT_SECRET=change-me.*$", f"JWT_SECRET={js}", text, flags=re.M)
        env.write_text(text)
        print("updated .env")
    else:
        print(f"BOTWOK_MASTER_KEY={mk}\nJWT_SECRET={js}")

if __name__ == "__main__":
    main()
