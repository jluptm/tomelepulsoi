import datetime
import asyncio
from db_manager import get_respondents_for_messaging, update_respondent_messaging_status
from whatsapp_sender import send_whatsapp_message_async

class WhatsAppService:
    def __init__(self, api_token=None):
        # api_token is now handled inside whatsapp_sender.py via st.secrets
        self.survey_period_days = 20

    async def process_church_respondents(self, church_name):
        print(f"Processing respondents for church: {church_name}")
        rows = get_respondents_for_messaging(church_name)
        
        for row in rows:
            resp_id = row[0]
            name = row[4]
            whatsapp = row[5]
            role = row[8]
            created_at_str = row[10]
            welcome_sent = row[12]
            last_reminder_at_str = row[13]

            if not whatsapp:
                continue

            phone = whatsapp.strip().replace(" ", "").replace("-", "")
            now = datetime.datetime.now()
            created_at = datetime.datetime.fromisoformat(created_at_str)

            # 1. Welcome Message
            if not welcome_sent:
                message = f"Estimado {role}. Bienvenido 💛✨🔆\nHerman@ *{name}*. Esperamos pueda completar la encuesta *Tómele el pulso a su iglesia* en la brevedad posible"
                print(f"Sending welcome to {name} ({phone})")
                res = await send_whatsapp_message_async(phone, message)
                if res:
                    update_respondent_messaging_status(resp_id, welcome_sent=1)
                continue

            # 2. Reminder Logic
            days_since_start = (now - created_at).days
            days_remaining = self.survey_period_days - days_since_start

            if days_remaining > 0:
                should_send_reminder = False
                if last_reminder_at_str:
                    last_reminder = datetime.datetime.fromisoformat(last_reminder_at_str)
                    if (now - last_reminder).days >= 2:
                        should_send_reminder = True
                else:
                    if (now - created_at).days >= 2:
                        should_send_reminder = True

                if should_send_reminder:
                    message = f"Hola *{name}*, recordatorio: faltan {days_remaining} días para completar la encuesta *Tómele el pulso a su iglesia*. ¡Tu participación es valiosa! ✨"
                    print(f"Sending reminder to {name} ({phone}). Days remaining: {days_remaining}")
                    res = await send_whatsapp_message_async(phone, message)
                    if res:
                        update_respondent_messaging_status(resp_id, last_reminder_at=now.isoformat())

    async def send_recovery_code(self, phone, code):
        message = f"Tu código de recuperación para *Tómele el pulso a su iglesia* es: *{code}*. Válido por 15 minutos."
        print(f"Sending recovery code to {phone}")
        return await send_whatsapp_message_async(phone, message)

    async def send_forgotten_username(self, phone, username):
        message = f"Tu nombre de usuario para *Tómele el pulso a su iglesia* es: *{username}*."
        print(f"Sending username recovery to {phone}")
        return await send_whatsapp_message_async(phone, message)

    def simulate_processing(self, church_name):
        """For testing without sending real messages"""
        print(f"SIMULATION: Processing respondents for church: {church_name}")
        result = get_respondents_for_messaging(church_name)
        for row in result.rows:
            name = row[4]
            whatsapp = row[5]
            welcome_sent = row[12]
            print(f"Respondent: {name}, Phone: {whatsapp}, Welcome Sent: {welcome_sent}")

if __name__ == "__main__":
    # Usage example
    API_TOKEN = "3a861af3a94e1c14c177949abb90408e944e098ed762776a718018bc929b1150"
    service = WhatsAppService(API_TOKEN)
    # service.process_church_respondents("Test Church")
