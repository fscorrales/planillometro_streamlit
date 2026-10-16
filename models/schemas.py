"""Modelos Pydantic para el sistema INVICO Planillometro."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Role(str, Enum):
    """Roles de usuario reconocidos por el sistema."""

    ADMIN = "admin"
    USER = "user"
    PENDING = "pending"


class PublicStoredUser(BaseModel):
    """Modelo de usuario devuelto por el backend (/users/me)."""

    id: str
    username: str
    role: Role


# -------------------------------------------------
class ObrasRecuperadasReport(BaseModel):
    ejercicio: int
    cod_barrio: str
    estructura: str
    importe: float
    notas: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# -------------------------------------------------
class ObrasDesactivadasReport(BaseModel):
    ejercicio: int
    cta_contable: str
    estructura: str
    importe: float
    notas: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# -------------------------------------------------
class SaldosBarriosEvolucionReport(BaseModel):
    ejercicio: int
    cod_barrio: str
    barrio: str
    saldo_inicial: float
    amortizacion: float
    cambios: float
    saldo_final: float

# -------------------------------------------------
class ReportePlanillometroReport(BaseModel):
    desc_programa: Optional[str] = None
    desc_subprograma: Optional[str] = None
    desc_proyecto: Optional[str] = None
    desc_actividad: Optional[str] = None
    estructura: Optional[str] = None
    partida: Optional[str] = None
    desc_obra: Optional[str] = None
    fuente: Optional[str] = None
    alta: str
    ejercicio: int
    ejecucion: float
    acum: float
    en_curso: float
    terminadas_ant: float
    terminadas_actual: float