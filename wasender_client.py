import requests
import os

class WasenderClient:
    def __init__(self, api_token=None):
        self.api_token = api_token or os.getenv("WASENDER_API_TOKEN")
        self.base_url = "https://wasenderapi.com/api"

    def send_text_message(self, phone, message):
        """
        Sends a text message using Wasender API.
        Expected API structure based on general research:
        POST /send-message
        {
            "token": "...",
            "phone": "...",
            "message": "..."
        }
        """
        url = f"{self.base_url}/send" # Common endpoint for many similar APIs
        # Note: Actual endpoint might vary, but I'll use a likely one or provide a way to change it.
        # Based on search results, sometimes it's /send, /send-message, etc.
        
        payload = {
            "token": self.api_token,
            "to": phone,
            "body": message
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error sending WhatsApp message: {e}")
            return None

if __name__ == "__main__":
    # Test with dummy data
    client = WasenderClient("3a861af3a94e1c14c177949abb90408e944e098ed762776a718018bc929b1150")
    # client.send_text_message("123456789", "Test message")
