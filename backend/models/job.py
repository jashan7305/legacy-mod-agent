from sqlalchemy import Column, String, Integer, Text, DateTime, func
from db import Base

class Job(Base):
    __tablename__ = "jobs"

    id          = Column(String, primary_key=True)   # uuid4 string
    repo_url    = Column(String, nullable=False)
    status      = Column(String, default="queued")   # queued|running|complete|failed
    summary     = Column(Text, nullable=True)
    pr_url      = Column(String, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

class FileResult(Base):
    __tablename__ = "file_results"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    job_id      = Column(String, nullable=False)
    file_path   = Column(String, nullable=False)
    debt_score  = Column(Integer, nullable=True)
    reasons     = Column(Text, nullable=True)         # JSON string
    diff        = Column(Text, nullable=True)
    line_count  = Column(Integer, nullable=True)