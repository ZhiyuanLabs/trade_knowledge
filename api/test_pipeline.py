import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from app.graph.builder import run_query

print("Starting query...")
try:
    final_state = run_query("What were the main events of World War II?")
    print("Done!")
    print("Citations:", final_state.get('citations'))
except Exception as e:
    print("Error:", e)
