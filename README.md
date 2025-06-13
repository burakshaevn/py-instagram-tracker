# Instagram Non-Followers Tracker

This Python application helps you identify Instagram users who don't follow you back. It uses the `instaloader` library to safely interact with Instagram.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the project root with your Instagram credentials:
```
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password
```

3. Run the program:
```bash
python main.py
```

## Features

- Safely authenticates with Instagram
- Downloads list of followers and following
- Identifies users who don't follow you back
- Uses proper design patterns for maintainable code
- Handles rate limiting and session management

## Note

Please use this tool responsibly and in accordance with Instagram's terms of service. Avoid making too many requests in a short period to prevent your account from being flagged. 