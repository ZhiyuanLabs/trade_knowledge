import os
import sys

# Ensure the root of the project is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

from app.graph.builder import run_query
from datasets import Dataset
import pandas as pd

# Langchain and Ragas wrappers
from langchain_openai import ChatOpenAI
from langchain_community.embeddings import HuggingFaceEmbeddings

try:
    # Ragas 0.4.x wraps LLMs and Embeddings
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas import evaluate
    from ragas.metrics import faithfulness, answer_relevancy, context_precision
    RAGAS_SUPPORTED = True
except ImportError:
    print("Warning: Ensure ragas is installed.")
    RAGAS_SUPPORTED = False

def get_ragas_models():
    """Build Langchain models and wrap them for Ragas."""
    llm = ChatOpenAI(
        model_name=os.getenv("LLM_MODEL", "grok-4-fast-non-reasoning"),
        api_key=os.getenv("AZURE_FOUNDRY_API_KEY"),
        base_url=os.getenv("AZURE_FOUNDRY_BASE_URL"),
        default_query={"api-version": os.getenv("AZURE_FOUNDRY_API_VERSION", "2024-05-01-preview")},
        temperature=0.0
    )
    ragas_llm = LangchainLLMWrapper(llm)

    lc_embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    ragas_embeddings = LangchainEmbeddingsWrapper(lc_embeddings)
    
    return ragas_llm, ragas_embeddings

def main():
    if not RAGAS_SUPPORTED:
        return

    # Gold Standard Test Dataset
    test_questions = [
        "How does the App Router handle Server Components caching in Next.js?",
        "What is the difference between static and dynamic rendering in the App Router?",
        "How can I use the 'use-cache' directive effectively?"
    ]

    print("========================================")
    print("Starting trade_knowledge Evaluation Pipeline")
    print("========================================")

    data = {
        "question": [], 
        "answer": [], 
        "contexts": []
    }

    for i, q in enumerate(test_questions):
        print(f"\n[Test {i+1}/{len(test_questions)}] Querying: '{q}'")
        try:
            # Run the Agentic RAG Graph
            state = run_query(q)
            
            answer = state.get("final_answer", "")
            # Extract the raw text from the final evidence items
            contexts = [ev["content"] for ev in state.get("evidence_items", [])]
            
            print(f"   -> Result: {len(contexts)} evidence items collected.")
            
            data["question"].append(q)
            data["answer"].append(answer)
            data["contexts"].append(contexts)
        except Exception as e:
            print(f"Error processing query '{q}': {e}")
            # Insert empty/failed data to keep structure
            data["question"].append(q)
            data["answer"].append("Error")
            data["contexts"].append([""])

    print("\n[Evaluate] Building dataset...")
    # New Ragas versions prefer user_input, response, retrieved_contexts
    mapped_data = {
        "user_input": data["question"],
        "response": data["answer"],
        "retrieved_contexts": data["contexts"]
    }
    dataset = Dataset.from_dict(mapped_data)

    print("[Evaluate] Running Ragas Evaluation...")
    ragas_llm, ragas_embeddings = get_ragas_models()

    # context_precision requires ground truth in older ragas, but we will exclude it if unsupported
    # we'll stick to referenceless metrics: faithfulness and answer_relevancy
    metrics = [faithfulness, answer_relevancy]

    eval_result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=ragas_llm,
        embeddings=ragas_embeddings,
    )

    print("\n========================================")
    print("Scores:")
    print("========================================")
    df = eval_result.to_pandas()
    # Print average scores across dataset
    if "faithfulness" in df.columns:
        print(f"Average Faithfulness:     {df['faithfulness'].mean():.2f}")
    if "answer_relevancy" in df.columns:
        print(f"Average Answer Relevancy: {df['answer_relevancy'].mean():.2f}")
    
    print("\nDetailed DataFrame:")
    print(df[["user_input", "faithfulness", "answer_relevancy"]].to_string())
    
    os.makedirs("data/eval", exist_ok=True)
    df.to_csv("data/eval/ragas_scores.csv", index=False)
    print("\nResults saved to data/eval/ragas_scores.csv")

if __name__ == "__main__":
    main()
