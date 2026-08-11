"""NABH / FHIR handover export (Feature 5).

``GET /api/v1/cases/{case_id}/handover`` renders the case's prehospital
monitoring data as an interoperable handover document:

* ``format=fhir`` (default) -> FHIR R4 JSON ``Bundle`` of type ``document``
  (``application/fhir+json``).
* ``format=cda`` -> a simplified CDA R2-style XML envelope (``text/xml``).

Access rules mirror the ECG/vitals read path: the owning paramedic or any
hospital staff member. The document is an export of transportable monitoring
data with a research-prototype boundary statement, not a certified medical
record and not a diagnostic interpretation.
"""

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response

from ..dependencies import CurrentUser, DbSession
from ..services import handover as handover_service

router = APIRouter(prefix="/api/v1/cases", tags=["handover"])

_FORMATS = ("fhir", "cda")


@router.get("/{case_id}/handover")
def get_handover(
    case_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
    format: str = Query("fhir"),
) -> Response:
    if format not in _FORMATS:
        raise HTTPException(
            status_code=400, detail="format must be 'fhir' or 'cda'"
        )
    if format == "fhir":
        bundle = handover_service.build_fhir(db, case_id, current_user)
        return Response(
            content=json.dumps(bundle, indent=2),
            media_type="application/fhir+json",
        )
    xml = handover_service.build_cda(db, case_id, current_user)
    return Response(content=xml, media_type="text/xml; charset=utf-8")
