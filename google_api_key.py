try:
    import streamlit as st
except ModuleNotFoundError:
    st = None

def get_google_api_key() -> str:
    if st is not None:
        try:
            secret_value = str(st.secrets["GOOGLE_API_KEY"]).strip()
            if secret_value:
                return secret_value
        except Exception:
            pass

    return ""
