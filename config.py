import os
from dotenv import load_dotenv

load_dotenv()

INSTAGRAM_USERNAME = os.getenv('INSTAGRAM_USERNAME')
INSTAGRAM_PASSWORD = os.getenv('INSTAGRAM_PASSWORD')

# Instagram scraping settings
DELAY_BETWEEN_REQUESTS = 5  # seconds
MAX_RETRIES = 5  # increased from 3 to 5
RETRY_DELAY = 10  # seconds to wait between retries 