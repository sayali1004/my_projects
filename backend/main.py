from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.vault_routes import router as vault_router
from api.chat_routes import router as chat_router
from api.project_routes import router as project_router
from db.database import init_db

app = FastAPI(
    title="DocVault AI",
    description="Persistent document vault with AI chat and smart retrieval",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(vault_router, prefix="/api/vault", tags=["vault"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
app.include_router(project_router, prefix="/api/projects", tags=["projects"])

@app.on_event("startup")
async def startup():
    await init_db()

@app.get("/")
def root():
    return {"message": "DocVault AI is running", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "ok"}
