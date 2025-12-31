import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re

# --- CONFIGURATION ---
GOOGLE_SHEET_NAME = "Ninja_Student_Output"

st.set_page_config(page_title="Ninja Park Processor", layout="wide")

def clean_name(name):
    """
    Standardizes names to ensure they match between files.
    Removes extra whitespace and converts to Title Case.
    """
    if not isinstance(name, str):
        return ""
    # Replace multiple spaces with single space, strip edges, title case
    return re.sub(r'\s+', ' ', name).strip().title()

def parse_roll_sheet(uploaded_file):
    """Parses the Roll Sheet HTML from memory buffer."""
    soup = BeautifulSoup(uploaded_file, 'lxml')
    data = []
    
    tables = soup.find_all('table')
    for table in tables:
        # Find Class Name (preceding header)
        class_name = "Unknown Class"
        previous = table.find_previous(['h1', 'h2', 'h3', 'h4', 'div', 'span'], class_=True)
        if previous:
            class_name = previous.get_text(strip=True)

        rows = table.find_all('tr')
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 2:
                raw_name = cols[0].get_text(strip=True)
                details_text = cols[1].get_text(strip=True).lower()
                
                # Skip header rows
                if "student" in raw_name.lower() or "level" in details_text:
                    continue

                # Extract Skill Level
                skill_level = "s0"
                skill_match = re.search(r's([0-9]|10)\b', details_text)
                if skill_match:
                    skill_level = skill_match.group(0)
                
                if raw_name:
                    data.append({
                        "Student Name": clean_name(raw_name),
                        "Skill Level": skill_level,
                        "Class Name": class_name
                    })
    
    # Remove duplicates if a student appears multiple times in the same class list
    df = pd.DataFrame(data)
    if not df.empty:
        df = df.drop_duplicates(subset=["Student Name"], keep='first')
    return df

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
                raw_name = cols[0].get_text(strip=True)
                
                # Skip header rows
                if raw_name.lower() == "student" or "keyword" in raw_name.lower(): 
                    continue
                
                age = cols[2].get_text(strip=True)
                keywords_raw = cols[3].get_text(strip=True).lower()
                
                # Filter Keywords: Only keep Group 1, Group 2, or Group 3
                group_match = re.search(r'(group\s*[1-3])', keywords_raw)
                clean_keyword = group_match.group(0).capitalize() if group_match else ""

                if raw_name:
                    data.append({
                        "Student Name": clean_name(raw_name),
                        "Age": age,
                        "Student Keyword": clean_keyword
                    })
    
    df = pd.DataFrame(data)
    if not df.empty:
        df = df.drop_duplicates(subset=["Student Name"])
    return df

def update_google_sheet(df):
    """Connects to Google Sheets using Streamlit Secrets."""
    # Check if secrets exist
    if "gcp_service_account" not in st.secrets:
        st.error("Secrets not found! Please check your Streamlit settings.")
        return None

    creds_dict = st.secrets["gcp_service_account"]
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    try:
        sheet = client.open(GOOGLE_SHEET_NAME).sheet1
    except gspread.exceptions.SpreadsheetNotFound:
        try:
            sh = client.create(GOOGLE_SHEET_NAME)
            sheet = sh.sheet1
            sh.share(creds_dict['client_email'], perm_type='user', role='owner')
        except Exception as e:
            st.error(f"Could not create sheet: {e}")
            return None

    sheet.clear()
    sheet.update([df.columns.values.tolist()] + df.values.tolist())
    return f"https://docs.google.com/spreadsheets/d/{sheet.spreadsheet.id}"

# --- MAIN APP UI ---
st.title("🥷 Ninja Park Data Processor")
st.write("Upload your iClassPro HTML files below.")

col1, col2 = st.columns(2)
with col1:
    roll_file = st.file_uploader("1. Upload Roll Sheet (HTML)", type=['html', 'htm'])
with col2:
    list_file = st.file_uploader("2. Upload Student List (HTML)", type=['html', 'htm'])

if roll_file and list_file:
    st.divider()
    with st.spinner('Processing...'):
        try:
            # 1. Parse both files
            df_roll = parse_roll_sheet(roll_file.read())
            df_list = parse_student_list(list_file.read())
            
            # Check for empty data
            if df_roll.empty:
                st.warning("⚠️ No students found in Roll Sheet. Please check the file.")
            if df_list.empty:
                st.warning("⚠️ No students found in Student List. Please check the file.")

            # 2. Merge Data
            # 'left' merge keeps everyone from the Student List
            merged_df = pd.merge(df_list, df_roll, on="Student Name", how="left")
            
            # Fill missing values for students not found in roll sheet
            merged_df["Skill Level"] = merged_df["Skill Level"].fillna("s0")
            merged_df["Class Name"] = merged_df["Class Name"].fillna("Not Found")
            
            # 3. Final Columns
            final_df = merged_df[["Student Name", "Age", "Student Keyword", "Skill Level", "Class Name"]]
            
            st.success(f"Matched {len(final_df)} students!")
            st.dataframe(final_df, use_container_width=True)
            
            col_a, col_b = st.columns(2)
            
            # DOWNLOAD BUTTON
            with col_a:
                csv_data = final_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download CSV",
                    data=csv_data,
                    file_name='ninja_output.csv',
                    mime='text/csv',
                    use_container_width=True
                )
            
            # GOOGLE SHEET BUTTON
            with col_b:
                if st.button("Update Master Google Sheet", use_container_width=True):
                    link = update_google_sheet(final_df)
                    if link:
                        st.success("Google Sheet Updated!")
                        # This HTML link prevents the app from resetting
                        st.markdown(f'''
                            <a href="{link}" target="_blank" style="
                                display: inline-block;
                                padding: 0.5em 1em;
                                color: white;
                                background-color: #0083B8;
                                border-radius: 5px;
                                text-decoration: none;
                                font-weight: bold;">
                                Open Google Sheet ⬈
                            </a>
                            ''', unsafe_allow_html=True)

        except Exception as e:
            st.error(f"An error occurred: {e}")
