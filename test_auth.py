import pytest
import uuid
from db_manager import (
    register_respondent, authenticate_respondent, save_responses, get_respondent_responses,
    add_church, add_campaign, reset_db_force, get_church_results
)

# Use a unique suffix to avoid collisions if DB isn't perfectly clean, 
# though we are calling reset_db_force in the fixture.

@pytest.fixture(scope="module")
def setup_db():
    print("Resetting DB for tests...")
    reset_db_force()
    # Create a church and campaign
    cid = add_church("Test Church", "Test Location", "123")
    token = str(uuid.uuid4())[:8]
    cmp_id = add_campaign(cid, token, "Online", "2025-12-31")
    return cid

def test_registration_and_login(setup_db):
    church_id = setup_db
    username = f"user_{uuid.uuid4()}"
    password = "securepassword"
    
    # 1. Register
    uid = register_respondent(
        church_id, username, password, 
        "Test User", "123456789", "Masculino", "18-30", "Miembro", "Alabanza"
    )
    assert uid is not None
    
    # 2. Login Logic (Authenticate)
    user_row = authenticate_respondent(username, password)
    assert user_row is not None
    assert user_row[2] == username # Index 2 is username
    
    # 3. Wrong Password
    bad_login = authenticate_respondent(username, "wrongpass")
    assert bad_login is None

def test_unique_username(setup_db):
    church_id = setup_db
    username = "unique_user"
    password = "password"
    
    # Register first time
    uid1 = register_respondent(church_id, username, password, "U1", "1", "M", "18", "M", "")
    assert uid1 is not None
    
    # Register second time (should fail)
    uid2 = register_respondent(church_id, username, password, "U2", "2", "M", "18", "M", "")
    assert uid2 is None

def test_save_and_update_responses(setup_db):
    church_id = setup_db
    username = f"user_survey_{uuid.uuid4()}"
    uid = register_respondent(church_id, username, "pass", "Survey User", "111", "M", "18", "Líder", "")
    
    # 1. Save Responses
    # responses list: (area_id, q_id, score, comment)
    data_v1 = [
        (1, 1, 8, "Good"),
        (1, 2, 9, "Great")
    ]
    save_responses(uid, data_v1)
    
    stored_v1 = get_respondent_responses(uid)
    assert len(stored_v1) == 2
    # Verify content. Row index 2 is score? in get_respondent_responses query: area, q, score, comment
    # So index 2 is score.
    scores = sorted([r[2] for r in stored_v1])
    assert scores == [8, 9]
    
    # 2. Update Responses (Edit Mode)
    # Changed scores
    data_v2 = [
        (1, 1, 10, "Improved"),
        (1, 2, 5, "Worse")
    ]
    save_responses(uid, data_v2)
    
    stored_v2 = get_respondent_responses(uid)
    assert len(stored_v2) == 2
    scores_v2 = sorted([r[2] for r in stored_v2])
    assert scores_v2 == [5, 10]
