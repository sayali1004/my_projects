import os
import json
import asyncio
from langchain_ollama import OllamaLLM
from langchain.prompts import PromptTemplate
from vault.ingest import retrieve_relevant_chunks

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3.2")

# Initialise Ollama LLM — connects to your local Ollama instance
llm = OllamaLLM(
    base_url=OLLAMA_BASE_URL,
    model=OLLAMA_MODEL,
    temperature=0.7,
)

RAG_PROMPT_WITH_CONTEXT = PromptTemplate(
    input_variables=["context", "chat_history", "question"],
    template="""You are DocVault AI, a smart general-purpose assistant that also has access to the user's personal document vault.

RELEVANT DOCUMENTS FROM VAULT:
{context}

CONVERSATION SO FAR:
{chat_history}

USER: {question}

Instructions:
- Use the vault documents above to answer if they're relevant; cite the source (e.g. "Based on your resume…").
- If the documents aren't relevant to the question, ignore them and answer from your general knowledge.
- Be conversational, helpful, and concise — like ChatGPT.

ASSISTANT:"""
)

RAG_PROMPT_NO_CONTEXT = PromptTemplate(
    input_variables=["chat_history", "question"],
    template="""You are DocVault AI, a smart general-purpose assistant.

CONVERSATION SO FAR:
{chat_history}

USER: {question}

Be conversational, helpful, and concise — like ChatGPT.

ASSISTANT:"""
)


def build_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a readable context block. Returns empty string when no chunks."""
    if not chunks:
        return ""

    context_parts = []
    for chunk in chunks:
        context_parts.append(
            f"[From: {chunk['file_name']} | Relevance: {chunk['score']}]\n{chunk['content']}"
        )
    return "\n\n---\n\n".join(context_parts)


def build_prompt(context: str, history_text: str, question: str) -> str:
    """Pick the right prompt template: with vault context or plain general-purpose."""
    if context:
        return RAG_PROMPT_WITH_CONTEXT.format(
            context=context, chat_history=history_text, question=question
        )
    return RAG_PROMPT_NO_CONTEXT.format(
        chat_history=history_text, question=question
    )


def build_chat_history(messages: list[dict]) -> str:
    """Format recent chat history for context."""
    if not messages:
        return ""

    # Only use last 6 messages to keep context window manageable
    recent = messages[-6:]
    history_parts = []
    for msg in recent:
        role = "User" if msg["role"] == "user" else "Assistant"
        history_parts.append(f"{role}: {msg['content']}")
    return "\n".join(history_parts)


async def generate_response(
    question: str,
    project_id: str = None,
    chat_history: list[dict] = None
) -> dict:
    """
    Full RAG pipeline:
    1. Retrieve relevant chunks from vault
    2. Build augmented prompt
    3. Generate response with Ollama
    4. Return response + sources used
    """
    # Step 1: Retrieve relevant document chunks
    chunks = retrieve_relevant_chunks(
        query=question,
        project_id=project_id,
        top_k=5
    )

    # Step 2: Build context and history
    context      = build_context(chunks)
    history_text = build_chat_history(chat_history or [])

    # Step 3: Build the prompt (uses general-purpose template when vault has no relevant docs)
    prompt = build_prompt(context, history_text, question)

    # Step 4: Call Ollama in a thread so we don't block the async event loop
    response_text = await asyncio.to_thread(llm.invoke, prompt)

    # Step 5: Collect unique source documents used
    sources = list({chunk["file_name"] for chunk in chunks})

    return {
        "answer":  response_text,
        "sources": sources,
        "chunks_used": len(chunks)
    }


async def generate_response_stream(
    question: str,
    project_id: str = None,
    chat_history: list[dict] = None
):
    """
    Streaming RAG pipeline — async generator that yields events:
      {"type": "start",  "sources": [...], "chunks_used": N}
      {"type": "token",  "content": "..."}   (one per Ollama token)
    """
    chunks       = retrieve_relevant_chunks(query=question, project_id=project_id, top_k=5)
    context      = build_context(chunks)
    history_text = build_chat_history(chat_history or [])
    prompt       = build_prompt(context, history_text, question)
    sources      = list({chunk["file_name"] for chunk in chunks})

    yield {"type": "start", "sources": sources, "chunks_used": len(chunks)}

    # llm.astream() runs llm._stream() in a thread pool under the hood
    async for token in llm.astream(prompt):
        yield {"type": "token", "content": token}
