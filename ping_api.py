import os
import google.generativeai as genai
from google.api_core import exceptions

# Simple manual parser for .env file since python-dotenv is missing
if os.path.exists('.env'):
    with open('.env', 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip().strip('"\'')

api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')

if not api_key:
    print('Error Code: API Key not found in environment')
else:
    genai.configure(api_key=api_key)
    try:
        # Simple ping: try to list models
        models = list(genai.list_models())
        print('Connection Successful')
    except exceptions.GoogleAPIError as e:
        print(f'Error Code: {e}')
    except Exception as e:
        print(f'Error: {e}')
