"""Router de administración: `/api/v1/admin/*` (AGENTS.md §8.3).

`require_admin` se aplica a nivel de router: cualquier endpoint que se añada aquí queda protegido
aunque su función no lo declare. Sin token → 401; rol `user` → 403.
"""

from fastapi import APIRouter, Depends

from app.core.auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
