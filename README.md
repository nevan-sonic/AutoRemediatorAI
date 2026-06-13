# AutoRemediator AI - Backend (Member 1)

This repository contains the complete autonomous incident response backend for AutoRemediator AI. It is designed to run in Python 3.11+, without requiring Docker on the local developer machine for development and testing.

## Project Structure
- `services/`: Contains custom Python integrations for Groq, Telemetry, Governance, memory database, and Docker Compose subprocess interaction.
- `agents/`: Contains specialized incident handling agents (Detection, Safety, Investigation, Decision, Execution, Validation, RCA).
- `main.py`: Entrypoint exposing the REST API endpoints.

## Local Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment**:
   Copy `.env.example` to `.env` and fill in the required keys:
   ```bash
   cp .env.example .env
   ```
   *Note: Ensure `GROQ_API_KEY` and `MONGODB_URI` are set.*

3. **Run Backend App**:
   ```bash
   uvicorn main:app --reload
   ```
   The API will be available at `http://localhost:8000`. You can view the OpenAPI docs at `http://localhost:8000/docs`.
