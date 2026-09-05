import os
from dotenv import load_dotenv
from groq import Groq

# Load the API key from your .env file
load_dotenv()

try:
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    print("✅ Successfully connected to Groq! Here are your available models:\n")
    
    # Fetch and print the list of models your key can access
    models = client.models.list()
    for m in models.data:
        print(f"- {m.id}")
        
except Exception as e:
    print(f"Error connecting to Groq: {e}")