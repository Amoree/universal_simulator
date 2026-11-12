from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    session_token: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    projects: Mapped[list["Project"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    owner: Mapped[User] = relationship(back_populates="projects")

    requirements: Mapped[list["Requirement"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    scenarios: Mapped[list["Scenario"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    category: Mapped[str] = mapped_column(String(40), default="system", nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), default="high", nullable=False)
    confirmed: Mapped[bool] = mapped_column(default=True, nullable=False)

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    project: Mapped[Project] = relationship(back_populates="requirements")


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    overrides: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    project: Mapped[Project] = relationship(back_populates="scenarios")
