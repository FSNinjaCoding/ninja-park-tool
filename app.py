import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re
import json

# --- CONFIGURATION ---
GOOGLE_SHEET_NAME = "Ninja_Student_Output"
# We will load credentials from Streamlit Secrets (secure cloud storage)
# instead of a local file for safety.

st.set_page_config(page_title="Ninja Park Processor", layout="wide")

def parse_roll_sheet(uploaded_file):
    """Parses the Roll Sheet HTML from memory buffer."""
    soup = BeautifulSoup(uploaded_file, 'lxml')
    data = []
    
    tables = soup.find_all('table')
    for table in tables:
        # Find Class Name (preceding header)
        class_name = "Unknown Class"
        previous = table.find_previous(['h1', 'h2', 'h3', 'h4', 'div'], class_=True)
        if previous:
            class_name = previous.get_text(strip=True)

        rows = table.find_all('tr')
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 2:
                student_name = cols[0].get_text(strip=True)
                details_text = cols[1].get_text(strip=True).lower()
                
                if "student" in student_name.lower() and "level" in details_text:
                    continue

                skill_level = "s0"
                skill_match = re.search(r's([1-9]|10)\b', details_text)
                if skill_match:
                    skill_level = skill_match.group(0)
                
                if student_name:
                    data.append({
                        "Student Name": student_name,
                        "Skill Level": skill_level,
                        "Class Name": class_name
                    })
    return pd.DataFrame(data)

def parse_student_list(uploaded_file):
    """Parses the Student List HTML from memory buffer."""
    soup = BeautifulSoup(uploaded_file, 'lxml')
    data = []
    tables = soup.find_all('table')
    
    for table in tables:
        rows = table.find_all('tr')
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 4:
                name = cols[0].get_text(strip=True)
                if name.lower() == "student": 
                    continue
                
                age = cols[2].get_text(strip=True)
                keywords_raw = cols[3].get_text(strip=True).lower()
                
                group_match = re.search(r'(group\s*[1-3])', keywords_raw)
                clean_keyword = group_match.group(0).capitalize() if group_match else ""

                if name:
                    data.append({
                        "Student Name": name,
                        "Age": age,
                        "Student Keyword": clean_keyword
                    })
    return pd.DataFrame(data)

def update_google_sheet(df):
    """Connects to Google Sheets using Streamlit Secrets."""
    # Load credentials from Streamlit secrets (secure environment variables)
    creds_dict = st.secrets["gcp_service_account"]
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    try:
        sheet = client.open(GOOGLE_SHEET_NAME).sheet1
    except gspread.exceptions.SpreadsheetNotFound:
        st.warning(f"Sheet '{GOOGLE_SHEET_NAME}' not found. Attempting to create it...")
        try:
            sh = client.create(GOOGLE_SHEET_NAME)
            sheet = sh.sheet1
            # Note: You must share this new sheet with your personal email manually later
            # or print the service account email here to share it with.
            st.info(f"Created new sheet. Share it with: {creds_dict['client_email']}")
        except Exception as e:
            st.error(f"Could not create sheet: {e}")
            return

    sheet.clear()
    sheet.update([df.columns.values.tolist()] + df.values.tolist())
    return f"https://docs.google.com/spreadsheets/d/{sheet.spreadsheet.id}"

# --- MAIN APP UI ---
st.title("🥷 Ninja Park Data Processor")
st.write("Upload your iClassPro HTML files below to merge them.")

col1, col2 = st.columns(2)
with col1:
    roll_file = st.file_uploader("1. Upload Roll Sheet (HTML)", type=['html'])
with col2:
    list_file = st.file_uploader("2. Upload Student List (HTML)", type=['html'])

if roll_file and list_file:
    st.divider()
    with st.spinner('Crunching the numbers...'):
        # Parse
        try:
            df_roll = parse_roll_sheet(roll_file)
            df_list = parse_student_list(list_file)
            
            # Merge
            merged_df = pd.merge(df_list, df_roll, on="Student Name", how="inner")
            
            # Reorder
            final_df = merged_df[["Student Name", "Age", "Student Keyword", "Skill Level", "Class Name"]]
            
            st.success(f"Successfully matched {len(final_df)} students!")
            
            # Preview
            st.dataframe(final_df, use_container_width=True)
            
            col_a, col_b = st.columns(2)
            
            # Option 1: Download CSV (Immediate use)
            with col_a:
                csv = final_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download as CSV",
                    data=csv,
                    file_name='ninja_output.csv',
                    mime='text/csv',
                    use_container_width=True
                )
            
            # Option 2: Sync to Google Sheet
            with col_b:
                if st.button("Update Master Google Sheet", use_container_width=True):
                    try:
                        link = update_google_sheet(final_df)
                        st.success("Google Sheet Updated!")
                        st.markdown(f"[Click here to view Google Sheet]({link})")
                    except Exception as e:
                        st.error(f"Error updating Google Sheet: {e}")
                        st.info("Make sure you have set up the secrets correctly in Streamlit Cloud.")

        except Exception as e:
            st.error(f"An error occurred: {e}")
