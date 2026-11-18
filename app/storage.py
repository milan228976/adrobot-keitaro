from sqlalchemy import JSON, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class StreamDraft(Base):
    __tablename__ = "stream_drafts"

    stream_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    baseline: Mapped[list[dict]] = mapped_column(JSON)
    pending: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    pins: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    pending_pins: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
