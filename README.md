# P&ID Table Extractor

This repository is organized to deploy on Streamlit Community Cloud from GitHub.

## Repo Layout

- Entrypoint: `app.py`
- Python dependencies: `requirements.txt`
- Linux dependencies: `packages.txt`
- Streamlit config: `.streamlit/config.toml`
- Example secrets: `.streamlit/secrets.toml.example`

## Local Run

Run Streamlit from the repository root so local behavior matches Community Cloud:

```powershell
.\venv\Scripts\python.exe -m streamlit run app.py
```

## Streamlit Community Cloud Deploy

1. Push this repository to GitHub.
2. In Streamlit Community Cloud, create a new app from that repository.
3. Set the entrypoint file to `app.py`.
4. In `Advanced settings`, choose Python `3.10` so deployment matches the environment this app is currently tested with.
5. If you want Gemini-based adjacent-table extraction, paste the contents of `.streamlit/secrets.toml.example` into the app's Secrets field and replace the placeholder value with your real key.
6. Deploy.

## Notes

- `packages.txt` installs `libgl1`, which is required for the OpenCV-based OCR path on Streamlit Community Cloud.
- `GOOGLE_API_KEY` is read only from Streamlit secrets. If it is not configured there, the main extraction flow still runs, but adjacent-table Gemini extraction is skipped gracefully.
