"""
LangGraph グラフ可視化スクリプト。

実行方法（プロジェクトルートで）:
    docker compose exec api python draw_graph.py

出力先（コンテナ内）:
    /app/data/graph.mmd   Mermaidテキスト（オフラインで生成）
    /app/data/graph.png   グラフ画像（mermaid.ink利用、ネット接続が必要）

PNGの生成に失敗したら、graph.mmdの中身を https://mermaid.live に貼れば同じ図が見られます。
"""
from pathlib import Path

from app.graph.builder import get_graph

OUTPUT_DIR = Path("/app/data")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    view = get_graph().get_graph(xray=True)

    # Mermaid text — offline, always works
    mmd_path = OUTPUT_DIR / "graph.mmd"
    mmd_path.write_text(view.draw_mermaid(), encoding="utf-8")
    print(f"Mermaid saved: {mmd_path}")

    # PNG — rendered through mermaid.ink, needs network
    try:
        png_path = OUTPUT_DIR / "graph.png"
        png_path.write_bytes(view.draw_mermaid_png())
        print(f"PNG saved: {png_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"PNG generation failed (network?): {exc}")
        print("Open https://mermaid.live and paste graph.mmd instead.")


if __name__ == "__main__":
    main()
