# Shared FREQ projects

This directory is shared by the master user and every FREQ-AI-SETUP agent.
Each direct child project should be its own Git repository.

Python projects should use a project-local virtual environment:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -U pip

JavaScript projects should keep dependencies project-local:

    npm install
    npm update

Do not store credentials, private keys, tokens, cookies, or production secrets
in this tree.
