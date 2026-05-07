import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.database import get_db, Project

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    color: str = "#185FA5"


@router.post("/")
async def create_project(req: ProjectCreate, db: AsyncSession = Depends(get_db)):
    project = Project(
        id=str(uuid.uuid4()),
        name=req.name,
        description=req.description,
        color=req.color
    )
    db.add(project)
    await db.commit()
    return {"id": project.id, "name": project.name, "color": project.color}


@router.get("/")
async def list_projects(db: AsyncSession = Depends(get_db)):
    result   = await db.execute(select(Project).order_by(Project.created_at))
    projects = result.scalars().all()
    return [
        {"id": p.id, "name": p.name, "description": p.description, "color": p.color}
        for p in projects
    ]


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    result  = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    await db.delete(project)
    await db.commit()
    return {"message": f"Project {project.name} deleted"}
