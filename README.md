# DocVault AI

Persistent document vault with AI chat and smart retrieval.
Upload your documents once — your AI finds them in every conversation automatically.

## Stack (100% free, no billing account needed)
- **LLM**: Ollama + Llama 3.2 (runs locally on your M2 Mac)
- **Embeddings**: sentence-transformers (local)
- **Vector DB**: ChromaDB (local, persists to disk)
- **Backend**: FastAPI + LangChain
- **Frontend**: React + Vite + Tailwind
- **Database**: SQLite (built into Python)
- **DevOps**: Docker Compose

---

## Setup (M2 Mac)

### Step 1 — Install Ollama
```bash
brew install ollama
ollama pull llama3.2
ollama serve   # keep this running in a terminal tab
```

### Step 2 — Clone and open in VS Code
```bash
cd docvault
code .
```

### Step 3 — Backend setup
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload
# API runs at http://localhost:8000
# API docs at http://localhost:8000/docs
```

### Step 4 — Frontend setup (new terminal tab)
```bash
cd frontend
npm install
npm run dev
# UI runs at http://localhost:5173
```

### OR — Run everything with Docker
```bash
# Make sure Ollama is running first (step 1)
docker compose up --build
# UI: http://localhost:5173
# API: http://localhost:8000
```

---

## Project structure
```
docvault/
├── docker-compose.yml
├── backend/
│   ├── main.py               # FastAPI entry point
│   ├── requirements.txt
│   ├── .env.example
│   ├── vault/
│   │   └── ingest.py         # Parse → chunk → embed → store pipeline
│   ├── agents/
│   │   └── chat_agent.py     # RAG retrieval + Ollama response
│   ├── api/
│   │   ├── vault_routes.py   # Upload, list, delete documents
│   │   ├── chat_routes.py    # Send messages, get history
│   │   └── project_routes.py # Create/manage projects
│   └── db/
│       └── database.py       # SQLite models
└── frontend/
    ├── src/
    │   ├── App.jsx
    │   ├── api.js             # All API calls
    │   └── components/
    │       ├── Sidebar.jsx
    │       ├── ChatWindow.jsx
    │       └── VaultPanel.jsx
    └── package.json
```

---

## How it works

### Document ingestion (upload once)
1. User uploads PDF/DOCX/TXT to vault
2. PyMuPDF / python-docx extracts text
3. LangChain splits into 500-token chunks
4. sentence-transformers embeds each chunk locally
5. ChromaDB stores vectors + text to disk
6. Done — never upload again

### Chat retrieval (every message)
1. User sends a message
2. Message embedded to same vector space
3. ChromaDB finds top 5 most relevant chunks
4. Chunks injected into Ollama prompt as context
5. Llama 3.2 generates a response using your actual documents
6. Response shows which docs were used

---

## Switching to Groq (if Ollama is slow)
1. Sign up at groq.com (email only, no card)
2. Get a free API key
3. In `.env`: set `LLM_PROVIDER=groq` and `GROQ_API_KEY=your_key`
4. In `agents/chat_agent.py`: swap `OllamaLLM` for `ChatGroq`

```python
from langchain_groq import ChatGroq
llm = ChatGroq(model="llama-3.3-70b-versatile", api_key=os.getenv("GROQ_API_KEY"))
```

---

## Todo / next features
- [ ] Streaming responses (SSE)
- [ ] Document preview in vault panel
- [ ] Export chat as PDF
- [ ] Multi-user support
- [ ] Jenkins CI/CD pipeline
