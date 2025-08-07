import os
import time
import shutil
import requests
import fitz  # PyMuPDF
import docx
import chromadb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.responses import Response, HTMLResponse, RedirectResponse

# ========== FastAPI App Setup ==========
app = FastAPI(title="HackRX Railway-Ready API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# ========== Serve HTML ==========
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open("index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)

# ========== Handle Favicon Gracefully ==========
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/favicon.ico")


# ========== ENV & ChromaDB ==========
load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "hackrx_collection")

chroma_client = chromadb.Client()
collection = chroma_client.get_or_create_collection(name=CHROMA_COLLECTION_NAME)

doc_store: dict[str, str] = {}

# ========== HuggingFace Embedding ==========
def get_embedding(texts):
    url = "https://api-inference.huggingface.co/embeddings/sentence-transformers/all-MiniLM-L6-v2"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    response = requests.post(url, json={"inputs": texts}, headers=headers)
    if response.status_code != 200:
        raise Exception("Embedding API failed: " + response.text)
    return response.json()

# ========== Models ==========
class QueryRequest(BaseModel):
    documents: str
    questions: list[str]

class SummarizeRequest(BaseModel):
    clauses: list[str]

# ========== Helpers ==========
def parse_document(path: str) -> str:
    if path.endswith(".pdf"):
        with fitz.open(path) as d:
            return "\n".join(page.get_text() for page in d)
    elif path.endswith(".docx"):
        doc = docx.Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    words = text.split()
    return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]

def rule_based_summary(clause: str) -> str:
    cl = clause.lower()
    if "pre-approve" in cl:
        return "Allowed with prior approval."
    if "not covered" in cl or "excluded" in cl:
        return "This clause excludes coverage."
    if "if" in cl and ("must" in cl or "require" in cl):
        return "Allowed under conditions."
    if "only if" in cl:
        return "Limited coverage depending on criteria."
    return clause.strip()[:120] + "..."

async def generate_answer(question, chunks):
    return {"answer": f"Answer to: '{question}' (dummy)"}


# ========== Endpoints ==========
@app.post("/hackrx/upload")
async def upload_doc(file: UploadFile = File(...), request: Request = None):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token != API_TOKEN:
        raise HTTPException(401, "Unauthorized")

    ext = os.path.splitext(file.filename)[1]
    temp_path = f"temp_{int(time.time())}{ext}"
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    doc_id = os.path.basename(temp_path)
    doc_store[doc_id] = temp_path

    raw_text = parse_document(temp_path)
    chunks = chunk_text(raw_text)
    embeddings = get_embedding(chunks)

    ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
    metadatas = [{"doc_id": doc_id} for _ in chunks]

    collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=chunks)
    return {"doc_id": doc_id}

@app.post("/hackrx/run")
async def run_question(body: QueryRequest, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token != API_TOKEN:
        raise HTTPException(401, "Unauthorized")

    try:
        local_path = download_document(body.documents)
    except Exception as e:
        raise HTTPException(400, f"Failed to download document: {e}")

    doc_id = os.path.basename(local_path)
    if doc_id not in doc_store:
        raw_text = parse_document(local_path)
        chunks = chunk_text(raw_text)
        embeddings = get_embedding(chunks)

        ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
        metadatas = [{"doc_id": doc_id} for _ in chunks]

        collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=chunks)
        doc_store[doc_id] = local_path

    answers = []
    for question in body.questions:
        q_emb = get_embedding([question])
        result = collection.query(query_embeddings=q_emb, n_results=3, where={"doc_id": doc_id})
        chunks_ = result["documents"][0]
        raw = await generate_answer(question, chunks_)
        answers.append(raw.get("answer") if isinstance(raw, dict) and "answer" in raw else str(raw))

    return {"answers": answers}

@app.post("/hackrx/summarize")
async def summarize_endpoint(body: SummarizeRequest, request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token != API_TOKEN:
        raise HTTPException(401, "Unauthorized")
    return {"summaries": [rule_based_summary(c) for c in body.clauses]}

# Downloader
def download_document(url: str, save_dir: str = ".", prefix: str = "remote_") -> str:
    local_filename = prefix + os.path.basename(url.split("?")[0])
    local_path = os.path.join(save_dir, local_filename)
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return local_path
