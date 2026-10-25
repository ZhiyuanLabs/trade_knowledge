"""
Step 1 — Clone the Next.js repository (shallow clone).
Skips if repo already exists.
"""

import os
import git
from dotenv import load_dotenv
from app.utils.logger import get_logger

load_dotenv()

REPO_URL = "https://github.com/vercel/next.js"
REPO_PATH = os.getenv("NEXTJS_REPO_PATH", "./data/nextjs-repo")
log = get_logger(__name__)


def clone_repo(repo_path: str = REPO_PATH) -> str:
    """
    Shallow-clone the Next.js repository.
    Returns the absolute path to the cloned repo.
    """
    abs_path = os.path.abspath(repo_path)

    if os.path.isdir(abs_path) and os.path.exists(os.path.join(abs_path, ".git")):
        log.info("clone.skip_existing_repo", path=abs_path)
        return abs_path

    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    log.info("clone.start", repo_url=REPO_URL, path=abs_path, branch="canary", depth=1)
    git.Repo.clone_from(
        REPO_URL,
        abs_path,
        depth=1,
        single_branch=True,
        branch="canary",
    )
    log.info("clone.done", path=abs_path)
    return abs_path


if __name__ == "__main__":
    clone_repo()
