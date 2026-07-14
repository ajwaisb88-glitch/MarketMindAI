from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="MarketMind AI Backend")

# Allow the desktop static server and typical localhost origins to call the API
origins = [
    "http://localhost:4000",
    "http://127.0.0.1:4000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/predict")
async def predict(asset: str = "gold"):
    # Placeholder predictive endpoint
    return {"asset": asset, "prediction": "neutral", "confidence": 0.5}
