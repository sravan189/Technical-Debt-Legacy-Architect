# Technical Debt & Legacy Architect

An AI-powered Streamlit chatbot for analyzing legacy software systems and technical debt.

## What it can analyze
- Source code and source-code screenshots
- Architecture, block, C4 and sequence diagrams
- UML diagrams
- Database schemas and ER diagrams
- SQL DDL
- API designs and OpenAPI/Swagger material
- API requests and responses
- Error messages and logs
- Deployment screenshots and configuration
- Docker/Kubernetes/YAML/JSON/TOML configuration
- Technical documentation, READMEs and design documents

## Key features
- Gemini-powered technical analysis
- Vision analysis for diagrams and screenshots
- Structured technical-debt findings
- Security, performance and maintainability analysis
- Practical fixes and modernization roadmap
- Telegram report delivery

## Project structure
```text
.
├── app.py
├── prompts.py
├── requirements.txt
├── README.md
├── .gitignore
└── .streamlit/
    └── secrets.toml.example
```

## Run locally
1. Create and activate a Python virtual environment.
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Create `.streamlit/secrets.toml` and add your own real credentials. Never commit this file.
4. Start:
```bash
streamlit run app.py
```

## Deployment
Deploy the repository with Streamlit Community Cloud. Add the contents of your local `.streamlit/secrets.toml` to the app's **Secrets** settings. Never upload real secrets to GitHub.

## Submission
Submit the GitHub repository URL and the live Streamlit Community Cloud URL.
