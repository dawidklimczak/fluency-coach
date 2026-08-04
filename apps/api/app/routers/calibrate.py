import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..services import vad

router = APIRouter(prefix="/api", tags=["calibrate"])


@router.post("/calibrate")
async def calibrate(audio: UploadFile = File(...), db: Session = Depends(get_db)):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(await audio.read())
        tmp_path = Path(tmp.name)
    try:
        samples = vad.read_wav_mono16k(tmp_path)
        floor, threshold = vad.calibrate(samples)
    finally:
        tmp_path.unlink(missing_ok=True)

    user = db.get(User, 1)
    if user is not None:
        user.noise_floor_db = floor
        user.vad_threshold = threshold
        db.commit()

    return {"noise_floor_db": round(floor, 1), "vad_threshold": round(threshold, 3)}


@router.get("/calibrate/status")
def calibration_status(db: Session = Depends(get_db)):
    user = db.get(User, 1)
    return {
        "calibrated": user is not None and user.noise_floor_db is not None,
        "noise_floor_db": user.noise_floor_db if user else None,
        "vad_threshold": user.vad_threshold if user else 0.5,
    }
