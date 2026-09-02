from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    TIMESTAMP,
    ForeignKey,
    JSON,
    func
)
from sqlalchemy.dialects.postgresql import UUID
import uuid

Base = declarative_base()


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    senha_hash = Column(Text, nullable=True)
    google_id = Column(Text, unique=True, nullable=True)
    foto = Column(Text, nullable=True)
    criado_em = Column(TIMESTAMP, server_default=func.now())

    # Relacionamento com as conversas
    conversas = relationship(
        "Conversa",
        back_populates="usuario",
        cascade="all, delete"
    )


class Conversa(Base):
    __tablename__ = "conversas"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    usuario_id = Column(
        Integer,
        ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False
    )
    titulo = Column(Text, nullable=True)
    criado_em = Column(TIMESTAMP, server_default=func.now())
    atualizado_em = Column(
        TIMESTAMP,
        server_default=func.now(),
        onupdate=func.now()
    )

    usuario = relationship("Usuario", back_populates="conversas")
    mensagens = relationship(
        "Mensagem",
        back_populates="conversa",
        cascade="all, delete-orphan",
        order_by="Mensagem.horario"
    )


class Mensagem(Base):
    __tablename__ = "mensagens"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    conversa_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversas.id", ondelete="CASCADE"),
        nullable=False
    )
    remetente = Column(String(20), nullable=False)  # 'user' ou 'assistant'
    conteudo = Column(Text, nullable=False)
    fontes = Column(JSON, nullable=True)
    horario = Column(TIMESTAMP, server_default=func.now())

    conversa = relationship("Conversa", back_populates="mensagens")
