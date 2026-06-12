import os
import tomllib
from pathlib import Path
from supabase import create_client, Client

def _load_secrets():
    #env vars win; fall back to .streamlit/secrets.toml so both apps share one config
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if url and key:
        return url, key
    secrets_path = Path(__file__).resolve().parents[2] / ".streamlit" / "secrets.toml"
    if secrets_path.exists():
        with open(secrets_path, "rb") as f:
            secrets = tomllib.load(f)
        return url or secrets.get("SUPABASE_URL"), key or secrets.get("SUPABASE_KEY")
    return url, key

_url, _key = _load_secrets()
if not _url or not _key:
    raise RuntimeError("SUPABASE_URL / SUPABASE_KEY not set (env or .streamlit/secrets.toml)")

supabase: Client = create_client(_url, _key)
