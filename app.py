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
    """Standardizes names (Title Case, no extra spaces)."""
    if not isinstance(name, str): return ""
    return re.sub(r'\s+', ' ', name).strip().title()

def find_header_indices(row_cells):
    """
    Scans a row of cells to see if it's a header row.
    Returns a dict of found columns: {'student': 0, 'age': 2, ...}
    """
    headers = {}
    for idx, cell in enumerate(row_cells):
        text = cell.get_text(strip=True).lower()
        if "student" in text: headers['student'] = idx
        elif "age" in text: headers['age'] = idx
        elif "keyword" in text: headers['keywords'] = idx
        elif "level" in text: headers['level'] = idx
    return headers

def parse_roll_sheet(uploaded_file):
    soup = BeautifulSoup(uploaded_file, 'lxml')
    data = []
    
    tables = soup.find_all('table')
    for table in tables:
        # 1. Try to find the Class Name (usually above the table)
        class_name = "Unknown Class"
        # Look for the nearest header or bold text preceding the table
        previous = table.find_previous(['h1', 'h2', 'h3', 'div', 'strong', 'span'], string=re.compile(r'.+'))
        if previous:
            class_name = previous.get_text(strip=True)

        rows = table.find_all('tr')
        
        # 2. Dynamic Header Detection
        col_map = {} 
        
        for row in rows:
            cols = row.find_all(['td', 'th'])
            # If we haven't found headers yet, check if this row is the header
            if not col_map:
                found = find_header_indices(cols)
                if 'student' in found: # Found the header row!
                    col_map = found
                    continue # Skip this row, it's just headers
            
            # 3. Extract Data using the map
            if col_map and len(cols) > max(col_map.values()):
                # Get Student Name
                raw_name = cols[col_map['student']].get_text(strip=True)
                
                # Get Skill Level (if 'level' column exists, use it; otherwise check col 1 as fallback)
                details_text = ""
                if 'level' in col_map:
                    details_text = cols[col_map['level']].get_text(strip=True).lower()
                elif len(cols) > 1: # Fallback: usually column 1 in roll sheets
                    details_text = cols[1].get_text(strip=True).lower()

                # Extract Skill (s0-s10)
                skill_level = "s0"
                skill_match = re.search(r's([0-9]|10)\b', details_text)
                if skill_match:
                    skill_level = skill_match.group(0)

                if raw_name and "student" not in raw_name.lower():
                    data.append({
                        "Student Name": clean_name(raw_name),
                        "Skill Level": skill_level,
                        "Class Name": class_name
                    })
    
    df = pd.DataFrame(data)
    if not df.empty:
        df = df.drop_duplicates(subset=["Student Name"], keep='first')
    return df

def parse_student_list(uploaded_file):
    soup = BeautifulSoup(uploaded_file, 'lxml')
    data = []
    tables = soup.find_all('table')
    
    for table in tables:
        rows = table.find_all('tr')
        col_map = {}
        
        for row in rows:
            cols = row.find_all(['td', 'th'])
            
            # 1. Find Headers dynamically
            if not col_map:
                found = find_header_indices(cols)
                if 'student' in found and 'age' in found:
                    col_map = found
                    continue
            
            # 2. Extract Data
            if col_map and len(cols) > max(col_map.values()):
                raw_name = cols[col_map['student']].get_text(strip=True)
                
                # Get Age
                age = cols[col_map['age']].get_text(strip=True)
                
                # Get Keyword (fallback to checking likely columns if not found)
                keywords_raw = ""
                if 'keywords' in col_map:
                    keywords_raw = cols[col_map['keywords']].get_text(strip=True).lower()
                elif len(cols) >= 4: # Fallback index
                    keywords_raw = cols[3].get_text(strip=True).lower()

                # Clean Keyword
                group_match = re.search(r'(group\s*[1-3])', keywords_raw)
                clean_keyword = group_match.group(0).capitalize() if group_match else ""

                if raw_name and "student" not in raw_name.lower():
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
    if "gcp_service_account" not in st.secrets:
        st.error("Secrets not found!")
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

# --- MAIN UI ---
st.title("🥷 Ninja Park Data Processor")

col1, col2 = st.columns(2)
with col1:
    roll_file = st.file_uploader("1. Upload Roll Sheet", type=['html', 'htm'])
with col2:
    list_file = st.file_uploader("2. Upload Student List", type=['html', 'htm'])

# --- DEBUG EXPANDER ---
# This lets you see the raw tables if something goes wrong
with st.expander("🕵️ Debug / Inspector (Click if data is missing)"):
    if roll_file:
        roll_file.seek(0)
        st.write("Preview of Roll Sheet Columns found:")
        try:
            debug_df = pd.read_html(roll_file)[0]
            st.write(debug_df.head())
        except: st.write("Could not auto-read HTML table.")

if roll_file and list_file:
    # Reset pointers for processing
    roll_file.seek(0)
    list_file.seek(0)
    
    st.divider()
    with st.spinner('Processing...'):
        try:
            df_roll = parse_roll_sheet(roll_file.read())
            df_list = parse_student_list(list_file.read())

            if df_roll.empty: st.warning("⚠️ No data found in Roll Sheet.")
            if df_list.empty: st.warning("⚠️ No data found in Student List.")

            # Merge (Left join keeps all students from the list)
            merged_df = pd.merge(df_list, df_roll, on="Student Name", how="left")
            
            # Fill blanks
            merged_df["Skill Level"] = merged_df["Skill Level"].fillna("s0")
            merged_df["Class Name"] = merged_df["Class Name"].fillna("Not Found")
            
            # Final Columns
            cols_needed = ["Student Name", "Age", "Student Keyword", "Skill Level", "Class Name"]
            # Ensure columns exist even if data is missing
            for c in cols_needed:
                if c not in merged_df.columns: merged_df[c] = ""
            
            final_df = merged_df[cols_needed]
            
            st.success(f"Matched {len(final_df)} students!")
            st.dataframe(final_df, use_container_width=True)
            
            c1, c2 = st.columns(2)
            with c1:
                # Fixed CSV output
                st.download_button(
                    label="Download CSV",
                    data=final_df.to_csv(index=False).encode('utf-8'),
                    file_name='ninja_output.csv',
                    mime='text/csv',
                    use_container_width=True
                )
            with c2:
                if st.button("Update Master Google Sheet", use_container_width=True):
                    link = update_google_sheet(final_df)
                    if link:
                        st.success("Google Sheet Updated!")
                        # FORCE NEW TAB LINK
                        st.markdown(f'<a href="{link}" target="_blank" style="background-color:#FF4B4B;color:white;padding:10px;text-decoration:none;border-radius:5px;display:block;text-align:center;">OPEN GOOGLE SHEET ⬈</a>', unsafe_allow_html=True)
                        
        except Exception as e:
            st.error(f"Error: {e}")
