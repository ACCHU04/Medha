from sqlalchemy import select

from .database import SessionLocal
from .models import Ambulance, Hospital, User
from .models.enums import AmbulanceStatus, UserRole
from .security import hash_password

SEED_USERS = [
    {"username": "paramedic1", "password": "s3curepass", "role": UserRole.paramedic, "hospital": None},
    {"username": "doctor1", "password": "s3curepass", "role": UserRole.doctor, "hospital": "MEDHA City Hospital"},
    {"username": "admin1", "password": "s3curepass", "role": UserRole.hospital_admin, "hospital": "MEDHA City Hospital"},
]
SEED_HOSPITALS = [
    {
        "name": "MEDHA City Hospital",
        "city": "Pune",
        "latitude": 18.5204,
        "longitude": 73.8567,
        "capabilities": {"trauma": True, "icu": True},
    },
    {
        "name": "Ruby Hall Clinic",
        "city": "Pune",
        "latitude": 18.5285,
        "longitude": 73.8631,
        "capabilities": {"cardiology": True, "icu": True},
    },
    {
        "name": "Jehangir Hospital",
        "city": "Pune",
        "latitude": 18.5140,
        "longitude": 73.8770,
        "capabilities": {"general": True, "pediatric": True},
    },
]
SEED_AMBULANCE = "MH-01-AMB-001"


def _get_or_create_user(db, username, password, role, hospital_id=None) -> tuple[User, bool]:
    user = db.scalar(select(User).where(User.username == username))
    if user is not None:
        if hospital_id is not None and user.hospital_id is None:
            user.hospital_id = hospital_id
            db.flush()
        return user, False
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password(password),
        role=role,
        hospital_id=hospital_id,
    )
    db.add(user)
    db.flush()
    return user, True


def _get_or_create_hospital(db, spec) -> tuple[Hospital, bool]:
    hospital = db.scalar(
        select(Hospital).where(Hospital.name == spec["name"])
    )
    if hospital is not None:
        if hospital.latitude is None:
            hospital.latitude = spec["latitude"]
            hospital.longitude = spec["longitude"]
            hospital.capabilities = spec["capabilities"]
            db.flush()
        return hospital, False
    hospital = Hospital(
        name=spec["name"],
        city=spec["city"],
        latitude=spec["latitude"],
        longitude=spec["longitude"],
        capabilities=spec["capabilities"],
    )
    db.add(hospital)
    db.flush()
    return hospital, True


def _get_or_create_ambulance(
    db, vehicle_number, hospital_id, assigned_to_id
) -> tuple[Ambulance, bool]:
    ambulance = db.scalar(
        select(Ambulance).where(Ambulance.vehicle_number == vehicle_number)
    )
    if ambulance is not None:
        return ambulance, False
    ambulance = Ambulance(
        vehicle_number=vehicle_number,
        hospital_id=hospital_id,
        assigned_to_id=assigned_to_id,
        status=AmbulanceStatus.transporting,
    )
    db.add(ambulance)
    db.flush()
    return ambulance, True


def seed_dev() -> dict[str, list[str]]:
    created: dict[str, list[str]] = {"users": [], "hospital": [], "ambulance": []}
    db = SessionLocal()
    try:
        hospital_by_name: dict[str, Hospital] = {}
        for spec in SEED_HOSPITALS:
            hospital, is_new = _get_or_create_hospital(db, spec)
            hospital_by_name[spec["name"]] = hospital
            if is_new:
                created["hospital"].append(hospital.name)

        for spec in SEED_USERS:
            hospital_id = None
            if spec["hospital"]:
                hospital_id = hospital_by_name[spec["hospital"]].id
            user, is_new = _get_or_create_user(
                db, spec["username"], spec["password"], spec["role"], hospital_id
            )
            if is_new:
                created["users"].append(user.username)

        paramedic = db.scalar(
            select(User).where(User.username == "paramedic1")
        )
        ambulance, is_new = _get_or_create_ambulance(
            db, SEED_AMBULANCE, hospital_by_name["MEDHA City Hospital"].id, paramedic.id
        )
        if is_new:
            created["ambulance"].append(ambulance.vehicle_number)

        db.commit()
    finally:
        db.close()
    return created


if __name__ == "__main__":
    result = seed_dev()
    if any(result.values()):
        for kind, items in result.items():
            for item in items:
                print(f"created {kind}: {item}")
    else:
        print("seed up to date; nothing created")
