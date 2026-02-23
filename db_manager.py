import streamlit as st
import asyncio
import libsql_client
import bcrypt

URL = st.secrets["turso"]["TURSO_URL"]
TOKEN = st.secrets["turso"]["TURSO_TOKEN"]

if not URL or not TOKEN:
    raise ValueError(
        "TURSO_URL o TURSO_TOKEN no están configurados. "
        "Si estás en local, revisa tu archivo .env. "
        "Si estás en Streamlit Cloud, asegúrate de haber configurado los 'Secrets'."
    )

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
            first_saved_at TIMESTAMP,
            FOREIGN KEY (church_id) REFERENCES churches(id)
        )
        """)
        # Migration: Add new columns if they don't exist
        try:
            await client.execute("ALTER TABLE respondents ADD COLUMN first_saved_at TIMESTAMP")
        except:
            pass # Already exists
        try:
            await client.execute("ALTER TABLE respondents ADD COLUMN welcome_sent INTEGER DEFAULT 0")
        except:
            pass
        try:
            await client.execute("ALTER TABLE respondents ADD COLUMN last_reminder_at TIMESTAMP")
        except:
            pass
        try:
            await client.execute("ALTER TABLE respondents ADD COLUMN extension_deadline TIMESTAMP")
        except:
            pass
        await client.execute("""
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            respondent_id INTEGER,
            area_id INTEGER,
            question_id INTEGER,
            score INTEGER,
            comment TEXT,
            FOREIGN KEY (respondent_id) REFERENCES respondents(id),
            UNIQUE(respondent_id, area_id, question_id)
        )
        """)
        # Migration: Add UNIQUE index if not exists (for existing tables)
        try:
            await client.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_responses_user_q ON responses(respondent_id, area_id, question_id)")
        except:
            pass
        await client.execute("""
        CREATE TABLE IF NOT EXISTS recovery_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            respondent_id INTEGER,
            code TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER DEFAULT 0,
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
        # Fetch password and full user row
        res = await client.execute("SELECT * FROM respondents WHERE username = ?", (username,))
        if not res.rows:
            return None
        
        user_row = res.rows[0]
        # user_row structure: id, church_id, username, password_hash, name, whatsapp, gender, age_range, role, ministerios, created_at, first_saved_at, welcome_sent, last_reminder_at, extension_deadline
        if check_password(password, user_row[3]):
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

# --- Recovery Logic ---

async def get_username_by_whatsapp_async(whatsapp):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        result = await client.execute("SELECT username FROM respondents WHERE whatsapp = ?", (whatsapp,))
        return result.rows[0][0] if result.rows else None

def get_username_by_whatsapp(whatsapp):
    return asyncio.run(get_username_by_whatsapp_async(whatsapp))

async def generate_recovery_code_async(username, whatsapp):
    import random
    import datetime
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        # Verify both match
        result = await client.execute("SELECT id FROM respondents WHERE username = ? AND whatsapp = ?", (username, whatsapp))
        if not result.rows:
            return None
        
        respondent_id = result.rows[0][0]
        code = f"{random.randint(100000, 999999)}"
        expires_at = (datetime.datetime.now() + datetime.timedelta(minutes=15)).isoformat()
        
        await client.execute(
            "INSERT INTO recovery_tokens (respondent_id, code, expires_at) VALUES (?, ?, ?)",
            (respondent_id, code, expires_at)
        )
        return code

def generate_recovery_code(username, whatsapp):
    return asyncio.run(generate_recovery_code_async(username, whatsapp))

async def verify_recovery_code_async(username, code):
    import datetime
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        now = datetime.datetime.now().isoformat()
        sql = """
            SELECT t.id 
            FROM recovery_tokens t
            JOIN respondents r ON t.respondent_id = r.id
            WHERE r.username = ? AND t.code = ? AND t.used = 0 AND t.expires_at > ?
        """
        result = await client.execute(sql, (username, code, now))
        return result.rows[0][0] if result.rows else None

def verify_recovery_code(username, code):
    return asyncio.run(verify_recovery_code_async(username, code))

async def reset_password_with_code_async(username, code, new_password):
    token_id = await verify_recovery_code_async(username, code)
    if not token_id:
        return False
    
    pwd_hash = hash_password(new_password)
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        # Update password
        await client.execute("UPDATE respondents SET password_hash = ? WHERE username = ?", (pwd_hash, username))
        # Mark token as used
        await client.execute("UPDATE recovery_tokens SET used = 1 WHERE id = ?", (token_id,))
        return True

def reset_password_with_code(username, code, new_password):
    return asyncio.run(reset_password_with_code_async(username, code, new_password))

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
        # Use a batch to ensure atomicity and prevent race conditions
        statements = [
            ("DELETE FROM responses WHERE respondent_id = ?", (respondent_id,))
        ]
        for area_id, q_id, score, comment in responses_list:
            statements.append((
                "INSERT INTO responses (respondent_id, area_id, question_id, score, comment) VALUES (?, ?, ?, ?, ?)", 
                (respondent_id, area_id, q_id, score, comment)
            ))
        
        await client.batch(statements)
        
        # Set first_saved_at if not set
        check = await client.execute("SELECT first_saved_at FROM respondents WHERE id = ?", (respondent_id,))
        if check.rows and check.rows[0][0] is None:
            await client.execute("UPDATE respondents SET first_saved_at = CURRENT_TIMESTAMP WHERE id = ?", (respondent_id,))

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

async def get_respondents_for_messaging_async(church_name):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        result = await client.execute("""
            SELECT r.id, r.church_id, r.username, r.password_hash, r.name, r.whatsapp, 
                   r.gender, r.age_range, r.role, r.ministerios, r.created_at, 
                   r.first_saved_at, r.welcome_sent, r.last_reminder_at
            FROM respondents r
            JOIN churches c ON r.church_id = c.id
            WHERE c.name = ?
        """, (church_name,))
        return result.rows

def get_respondents_for_messaging(church_name):
    return asyncio.run(get_respondents_for_messaging_async(church_name))

async def update_respondent_messaging_status_async(respondent_id, welcome_sent=None, last_reminder_at=None):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        updates = []
        params = []
        if welcome_sent is not None:
            updates.append("welcome_sent = ?")
            params.append(welcome_sent)
        if last_reminder_at is not None:
            updates.append("last_reminder_at = ?")
            params.append(last_reminder_at)
        
        if not updates:
            return
        
        sql = f"UPDATE respondents SET {', '.join(updates)} WHERE id = ?"
        params.append(respondent_id)
        await client.execute(sql, tuple(params))

def update_respondent_messaging_status(respondent_id, welcome_sent=None, last_reminder_at=None):
    return asyncio.run(update_respondent_messaging_status_async(respondent_id, welcome_sent, last_reminder_at))

async def get_all_users_summary_async():
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        sql = """
            SELECT 
                c.name as church_name,
                r.name as user_name,
                r.whatsapp,
                r.created_at,
                (SELECT COUNT(*) FROM responses WHERE respondent_id = r.id AND score != 0) as response_count,
                (SELECT COUNT(*) FROM responses WHERE respondent_id = r.id AND comment IS NOT NULL AND comment != '') as comment_count,
                r.id,
                r.extension_deadline,
                r.first_saved_at
            FROM respondents r
            LEFT JOIN churches c ON r.church_id = c.id
            ORDER BY c.name, r.name
        """
        result = await client.execute(sql)
        return result.rows

def get_all_users_summary():
    return asyncio.run(get_all_users_summary_async())

async def get_all_detailed_responses_async():
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        sql = """
            SELECT 
                c.name as church_name,
                r.name as user_name,
                r.whatsapp,
                res.area_id,
                res.question_id,
                res.score,
                res.comment
            FROM responses res
            JOIN respondents r ON res.respondent_id = r.id
            LEFT JOIN churches c ON r.church_id = c.id
            ORDER BY c.name, r.name, res.area_id, res.question_id
        """
        result = await client.execute(sql)
        return result.rows

def get_all_detailed_responses():
    return asyncio.run(get_all_detailed_responses_async())

async def get_church_comments_async(church_id):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        sql = """
            SELECT 
                r.area_id,
                r.question_id,
                res.name as user_name,
                res.role,
                r.score,
                r.comment
            FROM responses r
            JOIN respondents res ON r.respondent_id = res.id
            WHERE res.church_id = ? AND r.comment IS NOT NULL AND r.comment != ''
            ORDER BY r.area_id, res.name
        """
        result = await client.execute(sql, (church_id,))
        return result.rows

def get_church_comments(church_id):
    return asyncio.run(get_church_comments_async(church_id))

async def update_user_extension_async(user_id, deadline_str):
    async with libsql_client.create_client(url=URL, auth_token=TOKEN) as client:
        sql = "UPDATE respondents SET extension_deadline = ? WHERE id = ?"
        await client.execute(sql, (deadline_str, user_id))

def update_user_extension(user_id, deadline_str):
    return asyncio.run(update_user_extension_async(user_id, deadline_str))

# Added comment to trigger file change detection: 2026-02-20T12:11:00
