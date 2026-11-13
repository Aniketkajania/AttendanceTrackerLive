import os
from dotenv import load_dotenv

load_dotenv()

def _flag(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")

# ---- SQL Server ----
DB_SERVER = os.getenv("DB_SERVER", r"localhost\FaceDB")     # SQL Server named instance
DB_NAME = os.getenv("DB_NAME", "AttendanceTracker")
DB_USER = os.getenv("DB_USER", "")                          # Not used with Windows Auth
DB_PASSWORD = os.getenv("DB_PASSWORD", "")                  # Not used with Windows Auth
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")
DB_ENCRYPT = _flag("DB_ENCRYPT", True)                      # Driver 18 defaults to encrypted connections
DB_TRUST_CERT = _flag("DB_TRUST_CERT", True)                # Set True for local instances without formal SSL certs
DB_TRUSTED = _flag("DB_TRUSTED", True)                      # Enables Windows Auth (Trusted_Connection=yes)

# ---- storage: absolute paths so services started from any folder still work ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("DATA_DIR", BASE_DIR)
PHOTOS_DIR = os.path.join(DATA_DIR, "enrollment_photos")
SNAPSHOTS_DIR = os.path.join(DATA_DIR, "snapshots")

# ---- web ----
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
COOKIE_SECURE = _flag("COOKIE_SECURE", False)

# ---- engine ----
SHOW_PREVIEW = _flag("SHOW_PREVIEW", False)
ENGINE_DEVICE = os.getenv("ENGINE_DEVICE", "auto").strip().lower()
GPU_MEM_LIMIT_MB = int(os.getenv("GPU_MEM_LIMIT_MB", "1200"))
API_USE_GPU = _flag("API_USE_GPU", False)

os.makedirs(PHOTOS_DIR, exist_ok=True)
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

LOCATIONS = ["HO", "ICD PIYALA", "ICD GARHI", "ICD SAHNEWAL", "ICD KASHIPUR", "ICD VIRAMGAM"]

JWT_SECRET = os.environ["JWT_SECRET"]
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.45"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "180"))
DB_SYNC_INTERVAL = 60

SMTP_ENABLED = _flag("SMTP_ENABLED", True)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "")