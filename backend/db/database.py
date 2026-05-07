from sqlalchemy import Column, String, DateTime, Text, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./docvault.db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String, default="#185FA5")
    created_at = Column(DateTime, default=datetime.utcnow)

    documents = relationship("Document", back_populates="project")
    chats = relationship("Chat", back_populates="project")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    file_type = Column(String, nullable=False)      # pdf, docx, txt, png
    file_path = Column(String, nullable=False)      # path on disk
    scope = Column(String, default="project")       # "project" or "global"
    project_id = Column(String, ForeignKey("projects.id"), nullable=True)
    chunk_count = Column(String, default="0")
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="documents")


class Chat(Base):
    __tablename__ = "chats"

    id = Column(String, primary_key=True)
    title = Column(String, default="New chat")
    project_id = Column(String, ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="chats")
    messages = relationship("Message", back_populates="chat")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True)
    chat_id = Column(String, ForeignKey("chats.id"), nullable=False)
    role = Column(String, nullable=False)           # "user" or "assistant"
    content = Column(Text, nullable=False)
    sources = Column(Text, nullable=True)           # JSON list of doc sources used
    created_at = Column(DateTime, default=datetime.utcnow)

    chat = relationship("Chat", back_populates="messages")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
