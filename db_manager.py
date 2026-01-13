import os
import asyncio
import libsql_client
from dotenv import load_dotenv
import bcrypt

load_dotenv()

URL = os.getenv("TURSO_URL")
TOKEN = os.getenv("TURSO_TOKEN")

async def get_client():
    return libsql_client.create_client(url=URL, auth_token=TOKEN)

async def reset_db_force_async():
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        # Nuke everything
        await client.execute("DROP TABLE IF EXISTS responses")
        await client.execute("DROP TABLE IF EXISTS respondents")
        await client.execute("DROP TABLE IF EXISTS campaigns")
        await client.execute("DROP TABLE IF EXISTS churches")
        await init_db_async()

def reset_db_force():
    asyncio.run(reset_db_force_async())

async def init_db_async():
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        # Create tables
        await client.execute("""
        CREATE TABLE IF NOT EXISTS churches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT,
            access_key TEXT
        )
        """)
        await client.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            church_id INTEGER,
            token TEXT UNIQUE,
            scenario TEXT,
            deadline TEXT,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY (church_id) REFERENCES churches(id)
        )
        """)
        # NEW SCHEMA for respondents (Users)
        # Added church_id back to associate user with a church context
        await client.execute("""
        CREATE TABLE IF NOT EXISTS respondents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            church_id INTEGER,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            whatsapp TEXT,
            gender TEXT,
            age_range TEXT,
            role TEXT,
            ministerios TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (church_id) REFERENCES churches(id)
        )
        """)
        await client.execute("""
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            respondent_id INTEGER,
            area_id INTEGER,
            question_id INTEGER,
            score INTEGER,
            comment TEXT,
            FOREIGN KEY (respondent_id) REFERENCES respondents(id)
        )
        """)

def init_db():
    asyncio.run(init_db_async())

# --- User Auth ---

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

async def register_respondent_async(church_id, username, password, name, whatsapp, gender, age_range, role, ministerios):
    pwd_hash = hash_password(password)
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        # Check if username exists manually to prevent library crash on exception
        check = await client.execute("SELECT 1 FROM respondents WHERE username = ?", (username,))
        if check.rows:
            return None # Username taken

        result = await client.execute(
            """INSERT INTO respondents (church_id, username, password_hash, name, whatsapp, gender, age_range, role, ministerios) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
            (church_id, username, pwd_hash, name, whatsapp, gender, age_range, role, ministerios)
        )
        return result.last_insert_rowid

def register_respondent(church_id, username, password, name, whatsapp, gender, age_range, role, ministerios):
    return asyncio.run(register_respondent_async(church_id, username, password, name, whatsapp, gender, age_range, role, ministerios))

async def authenticate_respondent_async(username, password):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        result = await client.execute("SELECT * FROM respondents WHERE username = ?", (username,))
        if not result.rows:
            return None
        
        user_row = result.rows[0]
        # Schema: id, church_id, username, password_hash, name, whatsapp...
        # Indices: 0, 1, 2, 3...
        # Row 3 is password_hash
        stored_hash = user_row[3]
        
        if check_password(password, stored_hash):
            return user_row
        return None

def authenticate_respondent(username, password):
    return asyncio.run(authenticate_respondent_async(username, password))

async def get_respondent_responses_async(respondent_id):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        result = await client.execute("SELECT area_id, question_id, score, comment FROM responses WHERE respondent_id = ?", (respondent_id,))
        return result.rows

def get_respondent_responses(respondent_id):
    return asyncio.run(get_respondent_responses_async(respondent_id))

# --- Existing Church/Campaign Managers ---

async def add_church_async(name, location, access_key):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        result = await client.execute("INSERT INTO churches (name, location, access_key) VALUES (?, ?, ?)", (name, location, access_key))
        return result.last_insert_rowid

def add_church(name, location, access_key):
    return asyncio.run(add_church_async(name, location, access_key))

async def update_church_async(church_id, name, location, access_key):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        await client.execute("UPDATE churches SET name=?, location=?, access_key=? WHERE id=?", (name, location, access_key, church_id))

def update_church(church_id, name, location, access_key):
    return asyncio.run(update_church_async(church_id, name, location, access_key))

async def get_churches_async():
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        result = await client.execute("SELECT * FROM churches")
        return result.rows

def get_churches():
    return asyncio.run(get_churches_async())

async def add_campaign_async(church_id, token, scenario, deadline):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        result = await client.execute("INSERT INTO campaigns (church_id, token, scenario, deadline) VALUES (?, ?, ?, ?)", 
                                     (church_id, token, scenario, deadline))
        return result.last_insert_rowid

def add_campaign(church_id, token, scenario, deadline):
    return asyncio.run(add_campaign_async(church_id, token, scenario, deadline))

async def get_campaign_by_token_async(token_str):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        result = await client.execute("SELECT * FROM campaigns WHERE token = ?", (token_str,))
        return result.rows[0] if result.rows else None

def get_campaign_by_token(token_str):
    return asyncio.run(get_campaign_by_token_async(token_str))

async def get_campaigns_by_church_async(church_id):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        result = await client.execute("SELECT * FROM campaigns WHERE church_id = ?", (church_id,))
        return result.rows

def get_campaigns_by_church(church_id):
    return asyncio.run(get_campaigns_by_church_async(church_id))

# --- Submission Logic (Updated for Upsert/Replace) ---

async def save_responses_async(respondent_id, responses_list):
    """
    Deletes old responses for this user and inserts new ones.
    """
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        # Naive approach: delete all for this user and re-insert. 
        # Since we are sending the FULL survey every time (or at least the UI state has it), this is fine.
        await client.execute("DELETE FROM responses WHERE respondent_id = ?", (respondent_id,))
        for area_id, q_id, score, comment in responses_list:
            await client.execute("INSERT INTO responses (respondent_id, area_id, question_id, score, comment) VALUES (?, ?, ?, ?, ?)", 
                           (respondent_id, area_id, q_id, score, comment))

def save_responses(respondent_id, responses_list):
    return asyncio.run(save_responses_async(respondent_id, responses_list))

async def get_church_results_async(church_id, role_filter='all'):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        sql = """
            SELECT r.area_id, AVG(r.score) as avg_score
            FROM responses r
            JOIN respondents res ON r.respondent_id = res.id
            WHERE res.church_id = ?
        """
        params = [church_id]
        
        if role_filter == 'pastor':
            sql += " AND res.role = 'Pastor'"
        elif role_filter == 'non-pastor':
            sql += " AND res.role != 'Pastor'"
            
        sql += " GROUP BY r.area_id"
        
        result = await client.execute(sql, params)
        return result.rows

def get_church_results(church_id, role_filter='all'):
    return asyncio.run(get_church_results_async(church_id, role_filter))

async def get_church_stats_async(church_id):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        roles_res = await client.execute("""
            SELECT role, COUNT(*) as count 
            FROM respondents 
            WHERE church_id = ? 
            GROUP BY role
        """, (church_id,))
        
        dates_res = await client.execute("""
            SELECT MIN(created_at), MAX(created_at) 
            FROM respondents 
            WHERE church_id = ?
        """, (church_id,))
        
        return {
            "roles": {row[0]: row[1] for row in roles_res.rows},
            "date_range": dates_res.rows[0] if dates_res.rows else (None, None)
        }

def get_church_stats(church_id):
    return asyncio.run(get_church_stats_async(church_id))
