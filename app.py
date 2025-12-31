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
    # Remove any leading numbers like "1. " or "1 " if they accidentally get caught
    # But usually parsing by column index avoids this.
    return re.sub(r'\s+', ' ', name).strip().title()

def parse_roll_sheet(uploaded_file):
    soup = BeautifulSoup(uploaded_file, 'lxml')
    data = []
    
    # The file consists of MANY small tables. 
    # We iterate through them to track the "Current Class" context.
    tables = soup.find_all('table')
    
    current_class_name = "Unknown Class"
    
    for table in tables:
        rows = table.find_all('tr')
        if not rows: continue
        
        # Check first row to see what kind of table this is
        first_row_cols = [c.get_text(strip=True) for c in rows[0].find_all(['td', 'th'])]
        
        # CASE 1: Class Header Table
        # Example: ['Advanced Ninja... | Thu: 6:00', '12/29...']
        # We identify it by the pipe "|" character or specific keywords
        if len(first_row_cols) > 0 and ("|" in first_row_cols[0] or "Ninja" in first_row_cols[0]):
            # Verify it's not a student row
            if "Student" not in first_row_cols[0]: 
                current_class_name = first_row_cols[0]
                continue

        # CASE 2: Student Data Table
        # Header row usually looks like: ['', 'Student', '', 'Details', 'Date...']
        # We look for "Student" in the header to confirm it's a data table
        is_student_table = False
        name_idx = 1 # Default based on inspection
        detail_idx = 3 # Default based on inspection
        
        # Check header row
        for idx, col_text in enumerate(first_row_cols):
            if "Student" in col_text:
                is_student_table = True
                name_idx = idx
                # usually Details is name_idx + 2, but let's find it
                for sub_idx, sub_text in enumerate(first_row_cols):
                    if "Details" in sub_text:
                        detail_idx = sub_idx
                break
        
        if is_student_table:
            # Iterate through the student rows (skip header)
            for row in rows[1:]:
                cols = row.find_all(['td', 'th'])
                if len(cols) > max(name_idx, detail_idx):
                    raw_name = cols[name_idx].get_text(strip=True)
                    details_text = cols[detail_idx].get_text(strip=True).lower()
                    
                    # Extract Skill Level (S1-S10)
                    skill_level = "s0"
                    skill_match = re.search(r's([0-9]|10)\b', details_text)
                    if skill_match:
                        skill_level = skill_match.group(0)
                    
                    if raw_name:
                        data.append({
                            "Student Name": clean_name(raw_name),
                            "Skill Level": skill_level,
                            "Class Name": current_class_name
                        })

    df = pd.DataFrame(data)
    if not df.empty:
        df = df.drop_duplicates(subset=["Student Name"], keep='first')
    return df

def parse_student_list(uploaded_file):
    soup = BeautifulSoup(uploaded_file, 'lxml')
    data = []
    tables = soup.find_all('table')
    
    # The student list is usually just ONE big table
    for table in tables:
        rows = table.find_all('tr')
        if not rows: continue
        
        # Detect Headers
        headers = [c.get_text(strip=True).lower() for c in rows[0].find_all(['td', 'th'])]
        
        # Default indices based on your file inspection
        # Row 0: ['', 'Student Name', 'Attendance...', 'Age', 'Student Keywords', ...]
        name_idx = 1
        age_idx = 3
        key_idx = 4
        
        # Try to find dynamic indices if headers exist
        for i, h in enumerate(headers):
            if "student name" in h: name_idx = i
            elif "age" in h: age_idx = i
            elif "keyword" in h: key_idx = i

        # Parse Data Rows
        for row in rows[1:]:
            cols = row.find_all(['td', 'th'])
            if len(cols) > max(name_idx, age_idx, key_idx):
                raw_name = cols[name_idx].get_text(strip=True)
                age = cols[age_idx].get_text(strip=True)
                keywords_raw = cols[key_idx].get_text(strip=True).lower()
                
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
st.write("Upload your iClassPro HTML files below.")

col1, col2 = st.columns(2)
with col1:
    roll_file = st.file_uploader("1. Upload Roll Sheet", type=['html', 'htm'])
with col2:
    list_file = st.file_uploader("2. Upload Student List", type=['html', 'htm'])

# --- DEBUG INFO ---
if roll_file and list_file:
    # Reset file pointers
    roll_file.seek(0)
    list_file.seek(0)
    
    st.divider()
    with st.spinner('Processing...'):
        try:
            # Parse
            df_roll = parse_roll_sheet(roll_file.read())
            df_list = parse_student_list(list_file.read())

            if df_roll.empty: st.warning("⚠️ No data found in Roll Sheet.")
            if df_list.empty: st.warning("⚠️ No data found in Student List.")

            # Merge (Left join keeps all students from the list)
            merged_df = pd.merge(df_list, df_roll, on="Student Name", how="left")
            
            # Fill blanks
            merged_df["Skill Level"] = merged_df["Skill Level"].fillna("s0")
            merged_df["Class Name"] = merged_df["Class Name"].fillna("Not Found")
            
            # Reorder
            final_df = merged_df[["Student Name", "Age", "Student Keyword", "Skill Level", "Class Name"]]
            
            st.success(f"Matched {len(final_df)} students!")
            st.dataframe(final_df, use_container_width=True)
            
            c1, c2 = st.columns(2)
            with c1:
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
                        st.markdown(f'<a href="{link}" target="_blank" style="background-color:#0083B8;color:white;padding:10px;text-decoration:none;border-radius:5px;display:inline-block;">OPEN GOOGLE SHEET ⬈</a>', unsafe_allow_html=True)
                        
        except Exception as e:
            st.error(f"Error: {e}")
