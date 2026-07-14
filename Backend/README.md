# MarketMind AI — Backend (FastAPI)

Quick start (recommended inside a Python virtual environment):

```powershell
cd Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Endpoints:
- `GET /health` — health check
- `GET /predict?asset=gold` — placeholder prediction endpoint

Next steps:
- Add data connectors and model serving endpoints
- Add authentication and API token handling
